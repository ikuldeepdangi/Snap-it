from django.db import models
from django.contrib.auth.models import User

class Campaign(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='campaign_batches', null=True, blank=True)
    campaign_name = models.CharField(max_length=255, null=True, blank=True)
    campaign_inputs = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.campaign_name or 'Campaign'} ({self.created_at.date()})"

class TargetCompanyCampaign(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='targets', null=True, blank=True)
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('SENT', 'Sent'),
        ('FAILED', 'Failed'),
    )

    company_name = models.CharField(max_length=255)
    root_domain = models.CharField(max_length=255, unique=True, db_index=True)
    primary_recipient_hr = models.CharField(max_length=255)
    cc_founder = models.CharField(max_length=255, null=True, blank=True)
    cc_engineering_lead = models.CharField(max_length=255, null=True, blank=True)
    cc_senior_dev = models.CharField(max_length=255, null=True, blank=True)
    office_location = models.TextField(null=True, blank=True)
    target_tech_stack = models.CharField(max_length=255)
    evidence_url_hr = models.URLField(max_length=1024)
    evidence_url_cc = models.URLField(max_length=1024, null=True, blank=True)
    campaign_status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='PENDING')
    failure_reason = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.company_name} ({self.root_domain})"
