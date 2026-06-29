from django.db import models
from django.contrib.auth.models import User

DEFAULT_EMAIL_PROMPT = """You are an elite hiring strategist. Look at the ATTACHED IMAGE (a job posting) and use the CANDIDATE RESUME below.

CANDIDATE RESUME:
{resume_content}

TASK:
1. Extract: Company name, Job Role, and HR Email from the image.
2. Write a HIGH-CONVERSION application email (220-320 words) based on the matched resume context.
3. Generate a professional and catchy subject line tailored to the job description.

RETURN ONLY VALID JSON:
{{
  "company": "",
  "role": "",
  "hr_email": "",
  "email_subject": "",
  "email_body": ""
}}"""

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    google_refresh_token = models.TextField(null=True, blank=True)
    google_access_token = models.TextField(null=True, blank=True)
    token_expiry = models.DateTimeField(null=True, blank=True)
    custom_email_prompt = models.TextField(null=True, blank=True)

    def get_email_prompt(self):
        return self.custom_email_prompt if self.custom_email_prompt else DEFAULT_EMAIL_PROMPT

    def __str__(self):
        return self.user.username
