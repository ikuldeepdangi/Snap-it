from django.db import models
from django.contrib.auth.models import User

class Resume(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='resume')
    resume_storage_path = models.CharField(max_length=512, blank=True, null=True)
    resume_public_url = models.TextField(blank=True, null=True)
    extracted_text = models.TextField(blank=True, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    @property
    def filename(self):
        if not self.resume_storage_path:
            return ""
        return self.resume_storage_path.split('/')[-1]

    def __str__(self):
        return f"{self.user.email}'s Resume"

