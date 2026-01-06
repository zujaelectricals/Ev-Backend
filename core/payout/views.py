from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils import timezone
from .models import Payout, PayoutTransaction
from .serializers import PayoutSerializer, PayoutTransactionSerializer
from .utils import process_payout, auto_fill_emi_from_payout
from core.wallet.utils import get_or_create_wallet


class PayoutViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Payout management
    """
    queryset = Payout.objects.all()
    serializer_class = PayoutSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return Payout.objects.all()
        return Payout.objects.filter(user=user)
    
    def perform_create(self, serializer):
        user = self.request.user
        wallet = get_or_create_wallet(user)
        
        # Validate wallet balance
        requested_amount = serializer.validated_data['requested_amount']
        if wallet.balance < requested_amount:
            raise serializers.ValidationError("Insufficient wallet balance")
        
        payout = serializer.save(user=user, wallet=wallet)
        
        # Calculate TDS
        payout.calculate_tds()
        
        # Check if EMI auto-fill is requested
        emi_auto_filled = self.request.data.get('emi_auto_filled', False)
        if emi_auto_filled:
            emi_used, remaining = auto_fill_emi_from_payout(user, requested_amount)
            payout.emi_amount = emi_used
            payout.net_amount = remaining
            payout.emi_auto_filled = True
        
        payout.save()
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def process(self, request, pk=None):
        """Process payout (admin only)"""
        if not (request.user.is_superuser or request.user.role == 'admin'):
            return Response(
                {'error': 'Permission denied'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        payout = self.get_object()
        
        if payout.status != 'pending':
            return Response(
                {'error': 'Payout already processed'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            process_payout(payout)
            serializer = self.get_serializer(payout)
            return Response(serializer.data)
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def complete(self, request, pk=None):
        """Mark payout as completed (admin only)"""
        if not (request.user.is_superuser or request.user.role == 'admin'):
            return Response(
                {'error': 'Permission denied'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        payout = self.get_object()
        payout.status = 'completed'
        payout.completed_at = timezone.now()
        payout.transaction_id = request.data.get('transaction_id', '')
        payout.save()
        
        serializer = self.get_serializer(payout)
        return Response(serializer.data)


class PayoutTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Payout Transaction viewing
    """
    queryset = PayoutTransaction.objects.all()
    serializer_class = PayoutTransactionSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return PayoutTransaction.objects.all()
        return PayoutTransaction.objects.filter(user=user)

