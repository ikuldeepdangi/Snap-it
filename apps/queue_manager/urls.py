from django.urls import path
from .views import submit_job_view, job_status_view

urlpatterns = [
    path('submit/', submit_job_view, name='submit_job'),
    path('status/<int:job_id>/', job_status_view, name='job_status'),
]
