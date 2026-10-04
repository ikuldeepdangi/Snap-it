import os
import json
from django.urls import reverse
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator

from .models import Company, Campaign
from .tasks import generate_campaign_targets_task


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
    credits_used = total_companies * 1  # Mock mapping

    paginator = Paginator(all_campaigns, 7)  # 7 campaigns per page
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
            'campaign_name': campaign.name or f"{tech} Hiring",
            'status': campaign.status,
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
            if request.content_type == 'application/json':
                data = json.loads(request.body.decode('utf-8'))
            else:
                data = request.POST

            city = data.get('city') or data.get('target_city')
            tech = data.get('tech') or data.get('tech_stack')
            salary = data.get('salary', '')
            experience = data.get('experience') or data.get('experience_level', '')
            campaign_name = data.get('campaign_name')
            target_count_raw = data.get('target_count') or data.get('max_companies')
            target_count = int(target_count_raw) if target_count_raw else 12

            if not city or not tech:
                return JsonResponse({'error': 'Missing required fields: city and tech/tech_stack.'}, status=400)

            # Persist initial Campaign record with status=PENDING
            campaign = Campaign.objects.create(
                user=request.user,
                name=campaign_name or f"{tech} Hiring ({city})",
                city=city,
                tech=tech,
                experience=experience,
                salary=salary,
                status='PENDING'
            )

            # Immediately trigger background task without blocking the HTTP request
            try:
                generate_campaign_targets_task.delay(campaign.id, target_count=target_count)
            except Exception:
                # Fallback if Celery broker is not active in current environment
                generate_campaign_targets_task(campaign.id, target_count=target_count)

            profile = getattr(request.user, 'profile', None)
            has_gmail = profile and (profile.gmail_connected or bool(profile.google_access_token or profile.google_refresh_token))

            resp_data = {
                'success': True,
                'campaign_id': campaign.id,
                'status': 'PENDING'
            }
            if not has_gmail:
                resp_data['warning'] = 'Campaign queued! Please connect your Google/Gmail account to send outreach emails.'
                resp_data['permission_required'] = True
                resp_data['connect_url'] = reverse('connect_gmail')

            return JsonResponse(resp_data)
        except ValueError as e:
            return JsonResponse({'error': f'Invalid input format: {str(e)}'}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Invalid request method.'}, status=405)
