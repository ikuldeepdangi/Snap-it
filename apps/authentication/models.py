from django.db import models
from django.contrib.auth.models import User

DEFAULT_CUSTOM_INSTRUCTIONS = "Write a HIGH-CONVERSION application email (220-320 words) based on the matched resume context.\n3. Generate a professional and catchy subject line tailored to the job description."

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    google_refresh_token = models.TextField(null=True, blank=True)
    google_access_token = models.TextField(null=True, blank=True)
    token_expiry = models.DateTimeField(null=True, blank=True)
    custom_email_prompt = models.TextField(null=True, blank=True)
    gmail_connected = models.BooleanField(default=False)

    def get_email_prompt(self):
        instructions = self.custom_email_prompt if self.custom_email_prompt else DEFAULT_CUSTOM_INSTRUCTIONS
        return f"""You are an elite hiring strategist. Look at the ATTACHED IMAGE (a job posting) and use the CANDIDATE RESUME below.

CANDIDATE RESUME:
{{resume_content}}

TASK:
1. Extract: Company name, Job Role, and HR Email from the image.
2. {instructions}

RETURN ONLY VALID JSON:
{{{{
  "company": "",
  "role": "",
  "hr_email": "",
  "email_subject": "",
  "email_body": ""
}}}}"""

    def __str__(self):
        return self.user.username
