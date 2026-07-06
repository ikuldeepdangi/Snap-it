from django.urls import path
from .views import landing_page_view, login_view, oauth_callback_view, dashboard_view, history_view, logout_view, config_view, connect_gmail_view

urlpatterns = [
    path('', landing_page_view, name='landing_page'),
    path('auth/login/', login_view, name='login'),
    path('auth/logout/', logout_view, name='logout'),
    path('auth/callback/', oauth_callback_view, name='oauth_callback'),
    path('auth/connect-gmail/', connect_gmail_view, name='connect_gmail'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('history/', history_view, name='history'),
    path('config/', config_view, name='config'),
]
