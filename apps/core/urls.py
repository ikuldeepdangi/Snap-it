from django.urls import path
from . import views

urlpatterns = [
    path('privacy/', views.privacy_view, name='privacy'),
    path('terms/', views.terms_view, name='terms'),
]
