from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Campaign, Company

@login_required
def retry_failed_campaign_jobs(request, campaign_id):
    """
    Finds all failed Company target jobs for a given campaign belonging to request.user
    and resets their status to PENDING so the queue worker retries them.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method.'}, status=405)
        
    campaign = get_object_or_404(Campaign, id=campaign_id, user=request.user)
    
    failed_targets = Company.objects.filter(campaign=campaign, campaign_status='FAILED')
    count = failed_targets.count()
    
    if count == 0:
        return JsonResponse({'success': False, 'message': 'No failed targets found for this campaign.', 'count': 0})
        
    updated_count = failed_targets.update(
        campaign_status='PENDING',
        verification_reason='Queued for manual retry.'
    )
    
    return JsonResponse({
        'success': True,
        'message': f'Successfully queued {updated_count} failed target email(s) for retry.',
        'count': updated_count
    })
