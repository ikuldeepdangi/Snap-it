from django.urls import path
from . import views

urlpatterns = [
    path('', views.billing_page, name='billing_page'),
    path('create-razorpay-order/', views.create_razorpay_order, name='create_razorpay_order'),
    path('verify-razorpay-payment/', views.verify_razorpay_payment, name='verify_razorpay_payment'),
    path('record-failed-payment/', views.record_failed_payment, name='record_failed_payment'),
    path('manual-payment-request/', views.manual_payment_request, name='manual_payment_request'),
]
