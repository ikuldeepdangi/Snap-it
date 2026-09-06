from django.urls import path
from . import views
from . import campaign_retry

app_name = 'campaigns'

urlpatterns = [
    path('', views.campaign_dashboard, name='dashboard'),
    path('generate/', views.generate_campaign_api, name='generate'),
    path('retry/<int:campaign_id>/', campaign_retry.retry_failed_campaign_jobs, name='retry'),
]
