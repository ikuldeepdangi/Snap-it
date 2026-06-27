from django.db import models
from django.contrib.auth.models import User

class ProcessingJob(models.Model):
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='processing_jobs')
    screenshot = models.ImageField(upload_to='screenshots/')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    result_data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Job {self.id} - {self.user.email} - {self.status}"
