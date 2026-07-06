import requests
from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from .models import UserProfile
from .services import get_google_auth_url, exchange_code_for_tokens
from apps.core.models import Resume
from apps.core.engine import extract_text_from_pdf
from apps.queue_manager.models import ProcessingJob

def landing_page_view(request):
    """Render the main landing page with branding and login button."""
    if request.user.is_authenticated:
        return redirect('dashboard')
    return render(request, 'authentication/landing.html')

def login_view(request):
    """Redirect to Google's OAuth2 consent screen."""
    redirect_uri = request.build_absolute_uri(reverse('oauth_callback'))
    return redirect(get_google_auth_url(redirect_uri))

@login_required
def connect_gmail_view(request):
    """Redirect to Google's OAuth2 consent screen to request Gmail scope."""
    redirect_uri = request.build_absolute_uri(reverse('oauth_callback'))
    return redirect(get_google_auth_url(redirect_uri, request_gmail=True))

def oauth_callback_view(request):
    """Handle the OAuth2 callback from Google."""
    code = request.GET.get('code')
    if not code:
        return redirect('landing_page')
        
    try:
        redirect_uri = request.build_absolute_uri(reverse('oauth_callback'))
        tokens = exchange_code_for_tokens(code, redirect_uri)
        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')
        expires_in = tokens.get('expires_in', 3600)
        scope_str = tokens.get('scope', '')
        has_gmail = 'https://www.googleapis.com/auth/gmail.send' in scope_str
        
        # Get user info from Google
        user_info_response = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"}
        )
        user_info_response.raise_for_status()
        user_info = user_info_response.json()
        email = user_info.get('email')
        
        if not email:
            # Handle missing email
            return redirect('landing_page')
            
        # Register or get user
        user, created = User.objects.get_or_create(username=email, defaults={'email': email})
        
        # Update or create UserProfile
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if refresh_token:
            profile.google_refresh_token = refresh_token
        profile.google_access_token = access_token
        profile.token_expiry = timezone.now() + timedelta(seconds=expires_in)
        # Update gmail_connected if granted in this request or already True
        profile.gmail_connected = has_gmail or profile.gmail_connected
        profile.save()
        
        # Ensure CreditWallet exists
        from apps.billing.models import CreditWallet
        CreditWallet.objects.get_or_create(user=user, defaults={'balance': 25})
        
        # Authenticate session
        login(request, user)
        return redirect('dashboard')
        
    except Exception as e:
        # In a real app, log the exception and show an error message
        print(f"OAuth Callback Error: {e}")
        return redirect('landing_page')

@login_required
def dashboard_view(request):
    """Dashboard view for logged-in users."""
    from apps.billing.models import CreditWallet
    CreditWallet.objects.get_or_create(user=request.user, defaults={'balance': 25})
    
    if request.method == 'POST' and request.FILES.get('resume_file'):
        file = request.FILES['resume_file']
        
        # Get or create resume, and replace file if it exists
        resume, created = Resume.objects.get_or_create(user=request.user)
        if resume.file:
            resume.file.delete(save=False) # Delete old file
        resume.file = file
        resume.save()
        
        # Extract text
        extract_text_from_pdf(resume)
        return redirect('dashboard')
        
    has_resume = hasattr(request.user, 'resume')
    resume = request.user.resume if has_resume else None
    profile = getattr(request.user, 'profile', None)
    
    return render(request, 'core/dashboard.html', {
        'has_resume': has_resume,
        'resume': resume,
        'gmail_connected': profile.gmail_connected if profile else False
    })

from django.core.paginator import Paginator

@login_required
def history_view(request):
    jobs_list = ProcessingJob.objects.filter(user=request.user)
    
    # Filter by status
    status = request.GET.get('status')
    if status in ['COMPLETED', 'FAILED']:
        jobs_list = jobs_list.filter(status=status)
        
    jobs_list = jobs_list.order_by('-created_at')
    
    # Search locally to safely handle JSON parsing differences across SQLites
    q = request.GET.get('q', '').strip()
    if q:
        q_lower = q.lower()
        filtered_jobs = []
        for job in jobs_list:
            if job.result_data:
                company = str(job.result_data.get('company', '')).lower()
                role = str(job.result_data.get('role', '')).lower()
                hr_email = str(job.result_data.get('hr_email', '')).lower()
                if q_lower in company or q_lower in role or q_lower in hr_email:
                    filtered_jobs.append(job)
            elif q_lower in job.status.lower():
                filtered_jobs.append(job)
        jobs_list = filtered_jobs

    paginator = Paginator(jobs_list, 5)  # Show 5 items per page
    page_number = request.GET.get('page')
    jobs = paginator.get_page(page_number)
    
    return render(request, 'core/history.html', {
        'jobs': jobs,
        'current_status': status or 'ALL',
        'search_query': q
    })

def logout_view(request):
    from django.contrib.auth import logout
    logout(request)
    return redirect('landing_page')

@login_required
def config_view(request):
    """View to edit the custom email prompt."""
    profile = getattr(request.user, 'profile', None)
    if not profile:
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        
    from .models import DEFAULT_EMAIL_PROMPT
    
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'reset':
            profile.custom_email_prompt = None
            profile.save()
        elif action == 'save':
            custom_prompt = request.POST.get('custom_prompt')
            if custom_prompt and custom_prompt.strip():
                profile.custom_email_prompt = custom_prompt.strip()
                profile.save()
        return redirect('config')
        
    current_prompt = profile.custom_email_prompt if profile.custom_email_prompt else DEFAULT_EMAIL_PROMPT
    
    return render(request, 'core/config.html', {
        'current_prompt': current_prompt,
        'is_custom': bool(profile.custom_email_prompt),
        'default_prompt': DEFAULT_EMAIL_PROMPT
    })
