from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import WalletViewSet, WalletTransactionViewSet

router = DefaultRouter()
# Register transactions first to avoid routing conflicts
router.register(r'transactions', WalletTransactionViewSet, basename='wallet-transaction')
router.register(r'', WalletViewSet, basename='wallet')

urlpatterns = [
    path('', include(router.urls)),
]

