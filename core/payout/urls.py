from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PayoutViewSet, PayoutTransactionViewSet

router = DefaultRouter()
router.register(r'', PayoutViewSet, basename='payout')
router.register(r'transactions', PayoutTransactionViewSet, basename='payout-transaction')

urlpatterns = [
    path('', include(router.urls)),
]

