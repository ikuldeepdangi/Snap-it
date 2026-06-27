import uuid
import os
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from apps.bot.models import TelegramProfile

@login_required
def telegram_integration_view(request):
    profile, created = TelegramProfile.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        telegram_username = request.POST.get('telegram_username', '').strip()
        if telegram_username:
            if telegram_username.startswith('@'):
                telegram_username = telegram_username[1:]
            
            profile.telegram_username = telegram_username
            if not profile.verification_token and not profile.is_verified:
                profile.verification_token = str(uuid.uuid4())
            profile.save()
            return redirect('telegram_integration')
    
    # Check if they have a token but aren't verified yet
    if profile.telegram_username and not profile.is_verified and not profile.verification_token:
        profile.verification_token = str(uuid.uuid4())
        profile.save()
        
    bot_username = os.getenv('TELEGRAM_BOT_USERNAME', 'SnapItAppBot')
        
    return render(request, 'bot/telegram_bot.html', {
        'profile': profile,
        'bot_username': bot_username
    })

from django.http import JsonResponse

@login_required
def telegram_status_api(request):
    try:
        profile = TelegramProfile.objects.get(user=request.user)
        return JsonResponse({'is_verified': profile.is_verified})
    except TelegramProfile.DoesNotExist:
        return JsonResponse({'is_verified': False})
