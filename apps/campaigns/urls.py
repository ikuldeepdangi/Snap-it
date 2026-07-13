from django.urls import path
from . import views

app_name = 'campaigns'

urlpatterns = [
    path('', views.campaign_dashboard, name='dashboard'),
    path('generate/', views.generate_campaign_api, name='generate'),
]
