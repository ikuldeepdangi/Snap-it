from django.shortcuts import render

def privacy_view(request):
    return render(request, 'core/privacy.html')

def terms_view(request):
    return render(request, 'core/terms.html')

def custom_404(request, exception=None):
    return render(request, '404.html', status=404)
