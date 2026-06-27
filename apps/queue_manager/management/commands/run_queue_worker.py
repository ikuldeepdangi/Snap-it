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
                result = analyze_screenshot_with_gemini(screenshot_path, resume_text)
                
                if "error" in result:
                    raise ValueError(f"Gemini AI Error: {result['error']}")
                
                job.result_data = result
                self.stdout.write(self.style.SUCCESS(f"[Step 3] AI processing complete. Generated draft to: {result.get('company')} - {result.get('role')}"))
                
                # 3. Dispatch Email via Gmail API
                profile = getattr(job.user, 'profile', None)
                if not profile:
                    raise ValueError("User has no linked Google profile.")
                    
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
