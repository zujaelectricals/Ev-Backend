from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import WalletViewSet, WalletTransactionViewSet

router = DefaultRouter()
router.register(r'', WalletViewSet, basename='wallet')
router.register(r'transactions', WalletTransactionViewSet, basename='wallet-transaction')

urlpatterns = [
    path('', include(router.urls)),
]

