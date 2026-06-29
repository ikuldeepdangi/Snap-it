import time
import json
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.queue_manager.models import ProcessingJob
from apps.core.engine import analyze_screenshot_with_gemini, send_user_email
from apps.billing.utils import deduct_credit_atomically

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
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error fetching job: {e}"))
                time.sleep(5)
                continue
                
            if not job:
                # No jobs pending, sleep briefly
                time.sleep(2)
                continue
                
            self.stdout.write(f"Picked up Job {job.id} for {job.user.email}")
            
            try:
                # 2. Process job
                if not hasattr(job.user, 'resume') or not job.user.resume.file:
                    raise ValueError("User has no active resume.")
                
                resume_text = job.user.resume.extracted_text or ""
                screenshot_path = job.screenshot.path
                self.stdout.write(self.style.SUCCESS(f"[Step 1] Got active resume for {job.user.email} and saved screenshot {screenshot_path}"))
                
                # Use Gemini
                self.stdout.write(self.style.SUCCESS(f"[Step 2] Processing AI Image OCR using Gemini..."))
                
                profile = getattr(job.user, 'profile', None)
                prompt_template = profile.get_email_prompt() if profile else None
                
                result = analyze_screenshot_with_gemini(screenshot_path, resume_text, prompt_template=prompt_template)
                
                if "error" in result:
                    raise ValueError(f"Gemini AI Error: {result['error']}")
                
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
                        self.stdout.write(self.style.WARNING(f"Token expired for {job.user.email}, refreshing..."))
                        try:
                            new_tokens = refresh_access_token(profile.google_refresh_token)
                            profile.google_access_token = new_tokens['access_token']
                            profile.token_expiry = timezone.now() + timedelta(seconds=new_tokens.get('expires_in', 3600))
                            profile.save()
                            self.stdout.write(self.style.SUCCESS(f"Successfully refreshed token for {job.user.email}"))
                        except Exception as e:
                            raise ValueError(f"Failed to refresh Google token: {e}")
                    else:
                        raise ValueError("Token expired and no refresh token available.")
                    
                target_email = result.get('hr_email')
                if not target_email:
                    result['hr_email'] = job.user.email
                    self.stdout.write(self.style.WARNING(f"No HR email found, drafting to user {job.user.email} instead."))
                
                resume_file_path = job.user.resume.file.path
                self.stdout.write(self.style.SUCCESS(f"[Step 4] Dispatching email to {result['hr_email']} via Gmail API..."))
                if not send_user_email(profile, result, resume_file_path):
                    raise ValueError("Failed to dispatch email via Gmail API.")
                self.stdout.write(self.style.SUCCESS(f"[Step 5] Email successfully sent."))
                
                # 4. Deduct credit
                if deduct_credit_atomically(job.user.id, amount=1, description=f'Processed queue job {job.id}'):
                    job.status = 'COMPLETED'
                    job.save()
                    self.stdout.write(self.style.SUCCESS(f"[Step 6] Credit deducted. Job {job.id} COMPLETED successfully."))
                    
                    from apps.core.engine import send_async_telegram_alert
                    if hasattr(job.user, 'telegram_profile') and job.user.telegram_profile.is_verified:
                        # Refresh wallet from DB to get the new balance
                        job.user.credit_wallet.refresh_from_db()
                        rem_balance = job.user.credit_wallet.balance
                        
                        tg_id = job.user.telegram_profile.telegram_chat_id
                        notification_text = (
                            f"⚡ Job Application Dispatched Successfully!\n"
                            f"🏢 Company: {result.get('company')}\n"
                            f"🎯 Position: {result.get('role')}\n"
                            f"📬 Destination HR Address: {result.get('hr_email')}\n\n"
                            f"💸 Deducted 1 Credit. Remaining Balance: {rem_balance} credits."
                        )
                        send_async_telegram_alert(tg_id, notification_text)
                else:
                    raise ValueError("Insufficient credit balance during final processing step.")
                    
            except Exception as e:
                # 5. Handle Failure
                job.status = 'FAILED'
                error_msg = str(e)
                job.result_data = job.result_data or {}
                job.result_data['worker_error'] = error_msg
                job.save()
                self.stderr.write(self.style.ERROR(f"Job {job.id} FAILED: {error_msg}"))
                
                # Send error notification to Telegram
                try:
                    from apps.core.engine import send_async_telegram_alert
                    if hasattr(job.user, 'telegram_profile') and job.user.telegram_profile.is_verified:
                        tg_id = job.user.telegram_profile.telegram_chat_id
                        notification_text = (
                            f"❌ Job Processing Failed!\n\n"
                            f"An error occurred while processing your screenshot: {error_msg}\n"
                            f"Please make sure the screenshot clearly shows the HR email and try again."
                        )
                        send_async_telegram_alert(tg_id, notification_text)
                except Exception as alert_e:
                    self.stderr.write(self.style.ERROR(f"Failed to send Telegram error alert: {alert_e}"))
