from django.urls import path
from .views import DashboardView, SalesReportView, UserReportView, WalletReportView, DistributorDashboardView, AdminDashboardView, ComprehensiveReportsView

urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('sales/', SalesReportView.as_view(), name='sales-report'),
    path('user/', UserReportView.as_view(), name='user-report'),
    path('wallet/', WalletReportView.as_view(), name='wallet-report'),
    path('distributor-dashboard/', DistributorDashboardView.as_view(), name='distributor-dashboard'),
    path('admin-dashboard/', AdminDashboardView.as_view(), name='admin-dashboard'),
    path('comprehensive/', ComprehensiveReportsView.as_view(), name='comprehensive-reports'),
]

