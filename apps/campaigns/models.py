from django.db import models
from django.contrib.auth.models import User

from django.db import models
from django.contrib.auth.models import User

class Campaign(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='campaign_batches', null=True, blank=True)
    name = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    tech = models.CharField(max_length=100, null=True, blank=True)
    experience = models.CharField(max_length=50, null=True, blank=True)
    salary = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name or 'Campaign'} ({self.created_at.date()})"

class Company(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='targets', null=True, blank=True)
    
    # Core
    name = models.CharField(max_length=255)
    website = models.URLField(max_length=500, null=True, blank=True)
    logo_url = models.URLField(max_length=1024, null=True, blank=True)
    linkedin_url = models.URLField(max_length=1024, null=True, blank=True)
    employees = models.CharField(max_length=50, null=True, blank=True)
    founded = models.CharField(max_length=50, null=True, blank=True)
    industry = models.CharField(max_length=255, null=True, blank=True)
    location = models.CharField(max_length=255, null=True, blank=True)
    
    # Status & Scores
    is_hiring = models.BooleanField(default=False)
    tech_score = models.IntegerField(default=0)
    confidence_score = models.IntegerField(default=0)
    ranking = models.IntegerField(default=0)
    is_verified = models.BooleanField(default=False)
    
    # Contacts
    hr_email = models.EmailField(null=True, blank=True)
    founder_email = models.EmailField(null=True, blank=True)
    engineering_email = models.EmailField(null=True, blank=True)
    recruiter_email = models.EmailField(null=True, blank=True)
    linkedin_contact = models.URLField(max_length=1024, null=True, blank=True)
    
    # Evidence & Tracking
    evidence_url = models.URLField(max_length=1024, null=True, blank=True)
    verification_reason = models.TextField(null=True, blank=True)
    last_checked = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Backwards compatibility / Queue state
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('SEARCHING', 'Searching'),
        ('VERIFYING', 'Verifying'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    )
    campaign_status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='PENDING')

    def __str__(self):
        return self.name
