from django.urls import path
from . import views

from apps.bot.handle_telegram_query import telegram_webhook

urlpatterns = [
    path('', views.telegram_integration_view, name='telegram_integration'),
    path('status/', views.telegram_status_api, name='telegram_status_api'),
    path('webhook/', telegram_webhook, name='telegram_webhook'),
]
