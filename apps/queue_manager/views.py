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
            
        screenshot_files = request.FILES.getlist('screenshot')
        if not screenshot_files:
            return JsonResponse({'error': 'No screenshot provided.'}, status=400)
            
        if wallet.balance < len(screenshot_files):
            return JsonResponse({'error': f'Insufficient credits. You need {len(screenshot_files)} credits.'}, status=402)
        
        import config
        from utils.storage import get_file_extension, upload_temp_file, get_public_url

        # Validate all files first
        for f in screenshot_files:
            if f.size > config.MAX_CONTENT_LENGTH:
                return JsonResponse({'error': f'File size exceeds the maximum limit of {config.MAX_CONTENT_LENGTH // (1024*1024)} MB.'}, status=400)
            
            ext = get_file_extension(f.name).lstrip('.')
            if ext not in config.ALLOWED_IMAGE_EXTENSIONS:
                return JsonResponse({'error': f'Unsupported file type. Allowed formats: {", ".join(config.ALLOWED_IMAGE_EXTENSIONS)}'}, status=400)

        job_ids = []
        for f in screenshot_files:
            storage_path = upload_temp_file(f, user_id=request.user.id)
            public_url = get_public_url(storage_path)
            
            job = ProcessingJob(
                user=request.user,
                screenshot_storage_path=storage_path,
                screenshot_public_url=public_url,
                status='PENDING'
            )
            job.save()
            job_ids.append(job.id)
            
        first_job = ProcessingJob.objects.get(id=job_ids[0])
        
        # Calculate queue position
        position = ProcessingJob.objects.filter(status='PENDING', created_at__lt=first_job.created_at).count() + 1
        
        return JsonResponse({
            'job_ids': job_ids,
            'job_id': first_job.id, # Keep for backward compatibility if needed, but we will use job_ids on frontend
            'queue_position': position,
            'status': first_job.status,
            'total_submitted': len(screenshot_files)
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
