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
    return redirect(get_google_auth_url())

def oauth_callback_view(request):
    """Handle the OAuth2 callback from Google."""
    code = request.GET.get('code')
    if not code:
        return redirect('landing_page')
        
    try:
        tokens = exchange_code_for_tokens(code)
        access_token = tokens.get('access_token')
        refresh_token = tokens.get('refresh_token')
        expires_in = tokens.get('expires_in', 3600)
        
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
    
    return render(request, 'core/dashboard.html', {
        'has_resume': has_resume,
        'resume': resume
    })

@login_required
def history_view(request):
    jobs = ProcessingJob.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'core/history.html', {'jobs': jobs})
