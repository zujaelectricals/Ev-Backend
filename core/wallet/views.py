from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.pagination import PageNumberPagination
from django.contrib.auth import get_user_model
from datetime import datetime, timedelta
from .models import Wallet, WalletTransaction
from .serializers import WalletSerializer, WalletTransactionSerializer
from .utils import get_or_create_wallet

User = get_user_model()


class WalletTransactionPagination(PageNumberPagination):
    """Custom pagination for wallet transaction list with page_size support"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'


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
    pagination_class = WalletTransactionPagination
    
    def get_queryset(self):
        user = self.request.user
        is_admin = user.is_superuser or user.role == 'admin'
        
        # Base queryset
        if is_admin:
            # Admin can filter by user_id query parameter
            user_id = self.request.query_params.get('user_id')
            if user_id:
                try:
                    user_id_int = int(user_id)
                    # Verify user exists
                    if not User.objects.filter(id=user_id_int).exists():
                        raise NotFound(f"User with ID {user_id} does not exist.")
                    queryset = WalletTransaction.objects.filter(user_id=user_id_int)
                except ValueError:
                    raise ValidationError(f"Invalid user_id format: '{user_id}'. Must be a number.")
            else:
                queryset = WalletTransaction.objects.all()
        else:
            # Regular users only see their own transactions
            queryset = WalletTransaction.objects.filter(user=user)
        
        # Filter by transaction_type
        transaction_type = self.request.query_params.get('transaction_type')
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)
        
        # Filter by start_date
        start_date = self.request.query_params.get('start_date')
        if start_date:
            try:
                start_datetime = datetime.strptime(start_date, '%Y-%m-%d')
                queryset = queryset.filter(created_at__gte=start_datetime)
            except ValueError:
                raise ValidationError(f"Invalid start_date format: '{start_date}'. Use YYYY-MM-DD format.")
        
        # Filter by end_date
        end_date = self.request.query_params.get('end_date')
        if end_date:
            try:
                end_datetime = datetime.strptime(end_date, '%Y-%m-%d')
                # Include the entire end date (up to 23:59:59)
                end_datetime = end_datetime + timedelta(days=1) - timedelta(seconds=1)
                queryset = queryset.filter(created_at__lte=end_datetime)
            except ValueError:
                raise ValidationError(f"Invalid end_date format: '{end_date}'. Use YYYY-MM-DD format.")
        
        return queryset.order_by('-created_at')

