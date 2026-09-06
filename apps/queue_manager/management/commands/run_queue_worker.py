import time
import json
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.queue_manager.models import ProcessingJob
from apps.core.engine import analyze_screenshot_with_gemini, send_user_email
from apps.billing.utils import deduct_credit_atomically

def clean_error_message(error_msg: str) -> str:
    """Converts raw technical exception messages into user-friendly explanations."""
    error_msg_lower = error_msg.lower()
    
    # 1. Recipient/To header issues (invalid email or missing email)
    if "invalid to header" in error_msg_lower or "invalid_argument" in error_msg_lower:
        return (
            "Invalid recipient email address. The system could not extract a valid "
            "recruiter email address from the screenshot, or the extracted address is malformed. "
            "Please ensure the recruiter's email is visible and correct."
        )
        
    # 2. Resume missing
    if "resume attachment not found" in error_msg_lower:
        return "Your uploaded resume file could not be found. Please re-upload your resume on the dashboard and try again."
    if "user has no active resume" in error_msg_lower:
        return "No active resume found. Please upload your resume in PDF format on the dashboard before uploading job screenshots."
        
    # 3. Google/Gmail Auth issues
    if "credentials" in error_msg_lower or "token" in error_msg_lower or "auth" in error_msg_lower:
        return (
            "Google/Gmail authentication failed or expired. Please disconnect and "
            "reconnect your Google account on the dashboard to renew permissions."
        )
        
    # 4. Credit balance issues
    if "insufficient credit" in error_msg_lower or "credit balance" in error_msg_lower:
        return "Insufficient credits. Please check your wallet balance or purchase more credits to process this job."
        
    # 5. Snap-it AI parsing issues
    if "snapit ai error" in error_msg_lower or "ai could not read" in error_msg_lower:
        return (
            "AI analysis failed. We were unable to read or parse the job details "
            "from your screenshot. Please upload a clearer image."
        )
        
    # Fallback to a cleaner generic message if it's already short and readable
    if len(error_msg) < 100:
        return error_msg
        
    return "An unexpected error occurred while processing your request. Please try again with a clearer screenshot."


class Command(BaseCommand):
    help = 'Runs the persistent background queue worker for processing jobs.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting background queue worker...'))
        
        while True:
            job = None
            try:
                # 1. Fetch next pending job atomically
                with transaction.atomic():
                    job = ProcessingJob.objects.select_for_update(skip_locked=True).filter(
                        status='PENDING'
                    ).order_by('created_at').first()
                    
                    if job:
                        job.status = 'PROCESSING'
                        job.save()
                        is_campaign = False
                    else:
                        from apps.campaigns.models import Company
                        job = Company.objects.select_for_update(skip_locked=True).filter(
                            campaign_status='PENDING'
                        ).order_by('created_at').first()
                        if job:
                            job.campaign_status = 'PROCESSING'
                            job.save()
                            is_campaign = True

            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error fetching job: {e}"))
                time.sleep(5)
                continue
                
            if not job:
                # No jobs pending, sleep briefly
                time.sleep(2)
                continue
                
            if is_campaign:
                user = job.campaign.user if hasattr(job, 'campaign') and job.campaign else None
            else:
                user = getattr(job, 'user', None)
                
            if not user:
                # Fail campaign job if user is None
                if is_campaign:
                    job.campaign_status = 'FAILED'
                    job.verification_reason = "No user associated with this campaign."
                    job.save()
                time.sleep(2)
                continue

            if is_campaign:
                profile = getattr(user, 'profile', None)
                has_gmail_perm = profile and (profile.gmail_connected or bool(profile.google_refresh_token or profile.google_access_token))
                if not has_gmail_perm:
                    job.campaign_status = 'PENDING'
                    job.verification_reason = "Waiting for Gmail permission. Connect Google account to send."
                    job.save()
                    self.stdout.write(self.style.WARNING(f"Campaign target {job.id} for {user.email} kept PENDING: Waiting for Gmail permission."))
                    time.sleep(3)
                    continue

            self.stdout.write(f"Picked up Job {job.id} for {user.email}")
            
            screenshot_path = None
            resume_file_path = None
            try:
                try:
                    # 2. Process job
                    if not hasattr(user, 'resume') or not user.resume.resume_storage_path:
                        raise ValueError("User has no active resume.")
                    
                    resume_text = user.resume.extracted_text or ""
                    
                    from utils.storage import download_to_temp
                    self.stdout.write(f"Downloading files from storage...")
                    resume_file_path = download_to_temp(user.resume.resume_storage_path)
                    
                    if not is_campaign:
                        screenshot_path = download_to_temp(job.screenshot_storage_path)
                        self.stdout.write(self.style.SUCCESS(f"[Step 1] Got active resume for {user.email} and saved screenshot {screenshot_path}"))
                        
                        self.stdout.write(self.style.SUCCESS(f"[Step 2] Processing AI Image OCR using Snap-it Vision..."))
                        profile = getattr(user, 'profile', None)
                        prompt_template = profile.get_email_prompt() if profile else None
                        
                        result = analyze_screenshot_with_gemini(screenshot_path, resume_text, prompt_template=prompt_template)
                    else:
                        self.stdout.write(self.style.SUCCESS(f"[Step 1] Got active resume for {user.email}"))
                        
                        self.stdout.write(self.style.SUCCESS(f"[Step 2] Processing Campaign Draft using Snap-it AI..."))
                        profile = getattr(user, 'profile', None)
                        prompt_template = profile.get_email_prompt() if profile else None
                        
                        from apps.core.engine import generate_email_draft_from_text
                        result = generate_email_draft_from_text(
                            company=job.name,
                            role=job.campaign.tech if job.campaign else 'Tech Role',
                            hr_email=job.hr_email,
                            resume_content=resume_text,
                            prompt_template=prompt_template
                        )
                    
                    if "error" in result:
                        raise ValueError(f"Snapit AI Error: {result['error']}")
                    
                    if not is_campaign:
                        job.result_data = result
                    self.stdout.write(self.style.SUCCESS(f"[Step 3] AI processing complete. Generated draft to: {result.get('company')} - {result.get('role')}"))
                    
                    # 3. Dispatch Email via Gmail API
                    if not profile:
                        raise ValueError("User has no linked Google profile.")
                        
                    from django.utils import timezone
                    from datetime import timedelta
                    from apps.authentication.services import refresh_access_token
                    
                    # Refresh token if expiring within 5 minutes
                    if profile.token_expiry and profile.token_expiry <= timezone.now() + timedelta(minutes=5):
                        if profile.google_refresh_token:
                            self.stdout.write(self.style.WARNING(f"Token expired for {user.email}, refreshing..."))
                            try:
                                new_tokens = refresh_access_token(profile.google_refresh_token)
                                profile.google_access_token = new_tokens['access_token']
                                profile.token_expiry = timezone.now() + timedelta(seconds=new_tokens.get('expires_in', 3600))
                                profile.save()
                                self.stdout.write(self.style.SUCCESS(f"Successfully refreshed token for {user.email}"))
                            except Exception as e:
                                raise ValueError(f"Failed to refresh Google token: {e}")
                        else:
                            raise ValueError("Token expired and no refresh token available.")
                        
                    target_email = result.get('hr_email')
                    if not target_email or str(target_email).lower().strip() in ['none', 'null', 'none found', '']:
                        raise ValueError("No HR email found. Skipping outreach to save credits.")
                    
                    # 4. Check credit balance before attempting dispatch
                    wallet = getattr(user, 'credit_wallet', None)
                    if not wallet or wallet.balance < 1:
                        raise ValueError("Insufficient credit balance. Please recharge your wallet to dispatch emails.")
                        
                    self.stdout.write(self.style.SUCCESS(f"[Step 4] Dispatching email to {result['hr_email']} via Gmail..."))
                    original_resume_name = user.resume.filename if hasattr(user, 'resume') else None
                    if not send_user_email(profile, result, resume_file_path, original_filename=original_resume_name):
                        raise ValueError("Failed to dispatch email via Gmail API.")
                    
                    # 5. Deduct credit ONLY after successful email dispatch
                    if not deduct_credit_atomically(user.id, amount=1, description=f'Processed queue job {job.id}'):
                        raise ValueError("Insufficient credit balance during final deduction.")
                        
                    self.stdout.write(self.style.SUCCESS(f"[Step 5] Email successfully sent and 1 credit deducted."))
                    
                    if not is_campaign:
                        job.status = 'COMPLETED'
                    else:
                        job.campaign_status = 'SENT'
                    job.save()
                    self.stdout.write(self.style.SUCCESS(f"[Step 6] Job {job.id} COMPLETED successfully."))
                finally:
                    import os
                    for temp_file in [screenshot_path, resume_file_path]:
                        if temp_file and os.path.exists(temp_file):
                            try:
                                os.remove(temp_file)
                                self.stdout.write(self.style.SUCCESS(f"Cleaned up temporary file: {temp_file}"))
                            except Exception as clean_e:
                                self.stderr.write(self.style.ERROR(f"Failed to delete temp file {temp_file}: {clean_e}"))
                
                from apps.core.engine import send_async_telegram_alert
                if hasattr(user, 'telegram_profile') and user.telegram_profile.is_verified:
                    # Refresh wallet from DB to get the new balance
                    user.credit_wallet.refresh_from_db()
                    rem_balance = user.credit_wallet.balance
                    
                    tg_id = user.telegram_profile.telegram_chat_id
                    job_type_str = "Campaign Outreach" if is_campaign else "Job Application"
                    notification_text = (
                        f"⚡ {job_type_str} Dispatched Successfully!\n"
                        f"🏢 Company: {result.get('company')}\n"
                        f"🎯 Position: {result.get('role')}\n"
                        f"📬 Destination HR Address: {result.get('hr_email')}\n\n"
                        f"💸 Deducted 1 Credit. Remaining Balance: {rem_balance} credits."
                    )
                    send_async_telegram_alert(tg_id, notification_text)
                    
            except Exception as e:
                # 5. Handle Failure
                error_msg = str(e)
                clean_msg = clean_error_message(error_msg)
                if not is_campaign:
                    job.status = 'FAILED'
                    job.result_data = job.result_data or {}
                    job.result_data['worker_error'] = clean_msg
                else:
                    error_msg_lower = error_msg.lower()
                    if any(term in error_msg_lower for term in ["credentials", "token", "auth", "google profile", "linked google", "permission"]):
                        job.campaign_status = 'PENDING'
                        job.verification_reason = "Waiting for Gmail permission. Connect Google account to send."
                    else:
                        job.campaign_status = 'FAILED'
                        job.verification_reason = clean_msg
                job.save()
                self.stderr.write(self.style.ERROR(f"Job {job.id} FAILED: {error_msg}"))
                
                # Send error notification to Telegram
                try:
                    from apps.core.engine import send_async_telegram_alert
                    if hasattr(user, 'telegram_profile') and user.telegram_profile.is_verified:
                        tg_id = user.telegram_profile.telegram_chat_id
                        job_type_str = "Campaign Outreach" if is_campaign else "Job Processing"
                        context_msg = "while generating/sending the email" if is_campaign else "while processing your screenshot"
                        notification_text = (
                            f"❌ {job_type_str} Failed!\n\n"
                            f"An error occurred {context_msg}: {clean_msg}\n"
                        )
                        send_async_telegram_alert(tg_id, notification_text)
                except Exception as alert_e:
                    self.stderr.write(self.style.ERROR(f"Failed to send Telegram error alert: {alert_e}"))
