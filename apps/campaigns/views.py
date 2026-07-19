from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import Company, Campaign
from .services import CampaignGeneratorService

@login_required
def campaign_dashboard(request):
    campaigns = Campaign.objects.filter(user=request.user).order_by('-created_at')
    
    formatted_batches = []
    
    total_companies = 0
    total_sent = 0
    total_failed = 0
    total_pending = 0
    
    for campaign in campaigns:
        targets = campaign.targets.all()
        
        c_total = targets.count()
        c_pending = targets.filter(campaign_status__in=['PENDING', 'SEARCHING', 'VERIFYING']).count()
        c_sent = targets.filter(campaign_status__in=['SENT', 'COMPLETED']).count()
        c_failed = targets.filter(campaign_status='FAILED').count()
        
        total_companies += c_total
        total_sent += c_sent
        total_failed += c_failed
        total_pending += c_pending
        
        # We need a fallback tech if campaign_inputs is somehow null
        tech = campaign.tech or 'Tech'
        
        formatted_batches.append({
            'id': f'batch_{campaign.id}',
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
        
    success_rate = round((total_sent / total_companies) * 100) if total_companies else 0
    credits_used = total_companies * 1 # Mock mapping
        
    return render(request, 'campaigns/campaign_dashboard.html', {
        'campaign_batches': formatted_batches,
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
            return JsonResponse({'success': True, 'count': len(results)})
        except ValueError as e:
            return JsonResponse({'error': f'Invalid input format: {str(e)}'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({'error': 'Invalid request method.'}, status=405)
