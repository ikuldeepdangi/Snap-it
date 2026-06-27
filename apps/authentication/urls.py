from django.urls import path
from .views import landing_page_view, login_view, oauth_callback_view, dashboard_view, history_view, logout_view

urlpatterns = [
    path('', landing_page_view, name='landing_page'),
    path('auth/login/', login_view, name='login'),
    path('auth/logout/', logout_view, name='logout'),
    path('auth/callback/', oauth_callback_view, name='oauth_callback'),
    path('dashboard/', dashboard_view, name='dashboard'),
    path('history/', history_view, name='history'),
]
