from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Wallet, WalletTransaction
from .serializers import WalletSerializer, WalletTransactionSerializer
from .utils import get_or_create_wallet


class WalletViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Wallet viewing
    """
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return Wallet.objects.all()
        return Wallet.objects.filter(user=user)
    
    @action(detail=False, methods=['get'])
    def my_wallet(self, request):
        """Get current user's wallet"""
        wallet = get_or_create_wallet(request.user)
        serializer = self.get_serializer(wallet)
        return Response(serializer.data)


class WalletTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Wallet Transaction viewing
    """
    queryset = WalletTransaction.objects.all()
    serializer_class = WalletTransactionSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return WalletTransaction.objects.all()
        return WalletTransaction.objects.filter(user=user)

