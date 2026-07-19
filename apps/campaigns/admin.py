from django.contrib import admin
from .models import Company, Campaign

@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'tech', 'created_at')

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'campaign_status', 'is_verified', 'confidence_score', 'ranking', 'created_at')
    search_fields = ('name', 'website', 'hr_email', 'industry')
    list_filter = ('campaign_status', 'is_hiring', 'is_verified')
