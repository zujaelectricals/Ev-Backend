from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('create-order/', views.create_order, name='create-order'),
    path('verify/', views.verify_payment, name='verify'),
    path('webhook/', views.RazorpayWebhookView.as_view(), name='webhook'),
    path('create-payout/', views.create_payout, name='create-payout'),
    path('refund/', views.create_refund, name='refund'),
]

