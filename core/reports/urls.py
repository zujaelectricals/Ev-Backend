from django.urls import path
from .views import DashboardView, SalesReportView, UserReportView, WalletReportView

urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('sales/', SalesReportView.as_view(), name='sales-report'),
    path('user/', UserReportView.as_view(), name='user-report'),
    path('wallet/', WalletReportView.as_view(), name='wallet-report'),
]

