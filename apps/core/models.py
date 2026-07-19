from django.db import models
from django.contrib.auth.models import User

class Resume(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='resume')
    resume_storage_path = models.CharField(max_length=512, blank=True, null=True)
    resume_public_url = models.TextField(blank=True, null=True)
    original_filename = models.CharField(max_length=255, blank=True, null=True)
    extracted_text = models.TextField(blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    @property
    def filename(self):
        if self.original_filename:
            return self.original_filename
        if self.resume_storage_path:
            return self.resume_storage_path.split('/')[-1]
        return ""

    def __str__(self):
        return f"{self.user.email}'s Resume"

