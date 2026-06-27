from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from .models import ProcessingJob
from apps.billing.models import CreditWallet

@login_required
def submit_job_view(request):
    if request.method == 'POST':
        # Check credit
        try:
            wallet = CreditWallet.objects.get(user=request.user)
        except CreditWallet.DoesNotExist:
            wallet = CreditWallet.objects.create(user=request.user, balance=25)
            
        if wallet.balance < 1:
            return JsonResponse({'error': 'Insufficient credits.'}, status=402)
        
        screenshot_file = request.FILES.get('screenshot')
        if not screenshot_file:
            return JsonResponse({'error': 'No screenshot provided.'}, status=400)
        
        job = ProcessingJob.objects.create(
            user=request.user,
            screenshot=screenshot_file,
            status='PENDING'
        )
        
        # Calculate queue position
        position = ProcessingJob.objects.filter(status='PENDING', created_at__lt=job.created_at).count() + 1
        
        return JsonResponse({
            'job_id': job.id,
            'queue_position': position,
            'status': job.status
        })
    return JsonResponse({'error': 'Invalid request method.'}, status=405)

@login_required
def job_status_view(request, job_id):
    try:
        job = ProcessingJob.objects.get(id=job_id, user=request.user)
        if job.status == 'PENDING':
            position = ProcessingJob.objects.filter(status='PENDING', created_at__lt=job.created_at).count() + 1
        else:
            position = 0
            
        return JsonResponse({
            'job_id': job.id,
            'status': job.status,
            'queue_position': position,
            'result_data': job.result_data
        })
    except ProcessingJob.DoesNotExist:
        return JsonResponse({'error': 'Job not found.'}, status=404)
