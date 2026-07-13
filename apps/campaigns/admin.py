from django.contrib import admin
from .models import TargetCompanyCampaign

@admin.register(TargetCompanyCampaign)
class TargetCompanyCampaignAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'root_domain', 'primary_recipient_hr', 'campaign_status', 'created_at')
    search_fields = ('company_name', 'root_domain', 'primary_recipient_hr', 'target_tech_stack')
    list_filter = ('campaign_status', 'target_tech_stack')
