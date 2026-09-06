from django.urls import reverse
import os
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import Company, Campaign
from .services import CampaignGeneratorService
from .raw_ai_mode import RawAICampaignGeneratorService


from django.core.paginator import Paginator

@login_required
def campaign_dashboard(request):
    all_campaigns = Campaign.objects.filter(user=request.user).order_by('-created_at')
    
    total_companies = 0
    total_sent = 0
    total_failed = 0
    total_pending = 0
    
    for campaign in all_campaigns:
        targets = campaign.targets.all()
        total_companies += targets.count()
        total_pending += targets.filter(campaign_status__in=['PENDING', 'SEARCHING', 'VERIFYING']).count()
        total_sent += targets.filter(campaign_status__in=['SENT', 'COMPLETED']).count()
        total_failed += targets.filter(campaign_status='FAILED').count()
        
    success_rate = round((total_sent / total_companies) * 100) if total_companies else 0
    credits_used = total_companies * 1 # Mock mapping

    paginator = Paginator(all_campaigns, 7) # 7 campaigns per page
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    formatted_batches = []
    for campaign in page_obj.object_list:
        targets = campaign.targets.all()
        c_total = targets.count()
        c_pending = targets.filter(campaign_status__in=['PENDING', 'SEARCHING', 'VERIFYING']).count()
        c_sent = targets.filter(campaign_status__in=['SENT', 'COMPLETED']).count()
        c_failed = targets.filter(campaign_status='FAILED').count()
        
        tech = campaign.tech or 'Tech'
        formatted_batches.append({
            'id': f'batch_{campaign.id}',
            'campaign_id': campaign.id,
            'short_id': f'EXT-{str(campaign.id).zfill(6)}',
            'tech': tech,
            'date': campaign.created_at,
            'total': c_total,
            'pending': c_pending,
            'sent': c_sent,
            'failed': c_failed,
            'targets': targets,
            'campaign_name': campaign.name or f"{tech} Hiring"
        })
        
    profile = getattr(request.user, 'profile', None)
    gmail_connected = profile and (profile.gmail_connected or bool(profile.google_access_token or profile.google_refresh_token))

    return render(request, 'campaigns/campaign_dashboard.html', {
        'campaign_batches': formatted_batches,
        'page_obj': page_obj,
        'gmail_connected': gmail_connected,
        'connect_gmail_url': reverse('connect_gmail'),
        'analytics': {
            'total_companies': total_companies,
            'total_sent': total_sent,
            'total_pending': total_pending,
            'success_rate': success_rate,
            'credits_used': credits_used
        }
    })

@login_required
def generate_campaign_api(request):
    if request.method == 'POST':
        try:
            city = request.POST.get('city')
            tech = request.POST.get('tech')
            salary = request.POST.get('salary')
            experience = request.POST.get('experience')
            campaign_name = request.POST.get('campaign_name')
            max_companies_str = request.POST.get('max_companies')
            max_companies = int(max_companies_str) if max_companies_str else 10
            additional_notes = request.POST.get('additional_notes', '')

            if not all([city, tech, salary, experience]):
                return JsonResponse({'error': 'Missing required fields.'}, status=400)
                
            ai_mode = os.getenv("AI_MODE", "paid").strip().lower()
            if ai_mode == "free":
                service = RawAICampaignGeneratorService()
                results = service.generate_targets(
                    target_city=city,
                    target_tech=tech,
                    salary_threshold=salary,
                    experience_tier=experience,
                    max_companies=max_companies,
                    user=request.user,
                    campaign_name=campaign_name,
                    additional_notes=additional_notes
                )
            else:
                service = CampaignGeneratorService()
                results = service.generate_targets(
                    target_city=city,
                    target_tech=tech,
                    salary_threshold=salary,
                    experience_tier=experience,
                    max_companies=max_companies,
                    use_grounding=True,
                    user=request.user,
                    campaign_name=campaign_name,
                    additional_notes=additional_notes
                )


            profile = getattr(request.user, 'profile', None)
            has_gmail = profile and (profile.gmail_connected or bool(profile.google_access_token or profile.google_refresh_token))

            resp_data = {'success': True, 'count': len(results)}
            if not has_gmail:
                resp_data['warning'] = 'Campaign targets generated! Please connect your Google/Gmail account to send outreach emails.'
                resp_data['permission_required'] = True
                resp_data['connect_url'] = reverse('connect_gmail')

            return JsonResponse(resp_data)
        except ValueError as e:
            return JsonResponse({'error': f'Invalid input format: {str(e)}'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Invalid request method.'}, status=405)
