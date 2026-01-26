from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from django.db import transaction
from django.utils import timezone
from datetime import timedelta, datetime
from .models import Payout, PayoutTransaction
from .serializers import PayoutSerializer, PayoutTransactionSerializer
from .utils import process_payout, auto_fill_emi_from_payout
from core.wallet.utils import get_or_create_wallet
from core.settings.models import PlatformSettings


class PayoutPagination(PageNumberPagination):
    """Custom pagination for payout list with page_size support"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'


class PayoutViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Payout management
    """
    queryset = Payout.objects.all()
    serializer_class = PayoutSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = PayoutPagination
    
    def get_queryset(self):
        user = self.request.user
        queryset = Payout.objects.select_related('user', 'wallet')
        
        if user.is_superuser or user.role == 'admin':
            queryset = queryset.all()
        else:
            queryset = queryset.filter(user=user)
        
        # Filter by status
        status_param = self.request.query_params.get('status', None)
        if status_param:
            status_param = status_param.strip()
            queryset = queryset.filter(status=status_param)
        
        # Date filtering
        date_from = self.request.query_params.get('date_from', None)
        date_to = self.request.query_params.get('date_to', None)
        period = self.request.query_params.get('period', None)
        
        # Preset period takes precedence over date range
        if period:
            period = period.strip().lower()
            now = timezone.now()
            
            if period == 'last_7_days':
                date_from = (now - timedelta(days=7)).date()
                date_to = now.date()
            elif period == 'last_30_days':
                date_from = (now - timedelta(days=30)).date()
                date_to = now.date()
            elif period == 'last_90_days':
                date_from = (now - timedelta(days=90)).date()
                date_to = now.date()
            elif period == 'last_year':
                date_from = (now - timedelta(days=365)).date()
                date_to = now.date()
            elif period == 'all_time':
                # No date filter
                date_from = None
                date_to = None
        
        # Apply date filters
        if date_from:
            try:
                if isinstance(date_from, str):
                    date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
                queryset = queryset.filter(created_at__gte=timezone.make_aware(
                    datetime.combine(date_from, datetime.min.time())
                ))
            except ValueError:
                pass  # Invalid date format, ignore
        
        if date_to:
            try:
                if isinstance(date_to, str):
                    date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
                queryset = queryset.filter(created_at__lte=timezone.make_aware(
                    datetime.combine(date_to, datetime.max.time())
                ))
            except ValueError:
                pass  # Invalid date format, ignore
        
        return queryset.order_by('-created_at')
    
    def _get_wallet_summary(self, user):
        """Get wallet summary for user"""
        wallet = get_or_create_wallet(user)
        return {
            'current_balance': str(wallet.balance),
            'total_earned': str(wallet.total_earned),
            'total_withdrawn': str(wallet.total_withdrawn)
        }
    
    def _get_withdrawal_history(self, user, filters=None):
        """Get withdrawal history (completed payouts only)"""
        queryset = Payout.objects.filter(
            user=user,
            status='completed'
        ).select_related('user', 'wallet').order_by('-completed_at')
        
        # Track if date filter was actually applied
        date_filter_applied = False
        
        # Apply date filters if provided
        if filters:
            date_from = filters.get('date_from')
            date_to = filters.get('date_to')
            period = filters.get('period')
            
            # Preset period takes precedence
            if period:
                period = period.strip().lower()
                now = timezone.now()
                
                if period == 'last_7_days':
                    date_from = (now - timedelta(days=7)).date()
                    date_to = now.date()
                    date_filter_applied = True
                elif period == 'last_30_days':
                    date_from = (now - timedelta(days=30)).date()
                    date_to = now.date()
                    date_filter_applied = True
                elif period == 'last_90_days':
                    date_from = (now - timedelta(days=90)).date()
                    date_to = now.date()
                    date_filter_applied = True
                elif period == 'last_year':
                    date_from = (now - timedelta(days=365)).date()
                    date_to = now.date()
                    date_filter_applied = True
                elif period == 'all_time':
                    date_from = None
                    date_to = None
                    # all_time means no date filter
                    date_filter_applied = False
            
            if date_from:
                try:
                    if isinstance(date_from, str):
                        date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
                    queryset = queryset.filter(completed_at__gte=timezone.make_aware(
                        datetime.combine(date_from, datetime.min.time())
                    ))
                    date_filter_applied = True
                except ValueError:
                    pass
            
            if date_to:
                try:
                    if isinstance(date_to, str):
                        date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
                    queryset = queryset.filter(completed_at__lte=timezone.make_aware(
                        datetime.combine(date_to, datetime.max.time())
                    ))
                    date_filter_applied = True
                except ValueError:
                    pass
        
        # Limit to last 50 if no date filter was applied
        if not date_filter_applied:
            queryset = queryset[:50]
        
        return queryset
    
    def list(self, request, *args, **kwargs):
        """List payouts with comprehensive response including wallet summary and withdrawal history"""
        # Get filtered queryset
        queryset = self.filter_queryset(self.get_queryset())
        
        # Get paginated results
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated_response = self.get_paginated_response(serializer.data)
            
            # Extract pagination data
            try:
                page_num = int(request.query_params.get('page', 1))
            except (ValueError, TypeError):
                page_num = 1
            
            pagination_data = {
                'count': paginated_response.data['count'],
                'page': page_num,
                'page_size': len(page),
                'total_pages': paginated_response.data.get('total_pages', 1),
                'next': paginated_response.data.get('next'),
                'previous': paginated_response.data.get('previous'),
                'results': paginated_response.data['results']
            }
        else:
            # No pagination
            serializer = self.get_serializer(queryset, many=True)
            pagination_data = {
                'count': len(serializer.data),
                'page': 1,
                'page_size': len(serializer.data),
                'total_pages': 1,
                'next': None,
                'previous': None,
                'results': serializer.data
            }
        
        # Get wallet summary
        wallet_summary = self._get_wallet_summary(request.user)
        
        # Get withdrawal history filters
        withdrawal_filters = {
            'date_from': request.query_params.get('date_from'),
            'date_to': request.query_params.get('date_to'),
            'period': request.query_params.get('period')
        }
        
        # Get withdrawal history
        withdrawal_queryset = self._get_withdrawal_history(request.user, withdrawal_filters)
        withdrawal_serializer = self.get_serializer(withdrawal_queryset, many=True)
        
        # Build comprehensive response
        response_data = {
            'wallet_summary': wallet_summary,
            'withdrawal_history': withdrawal_serializer.data,
            'payouts': pagination_data
        }
        
        return Response(response_data)
    
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
        
        # Check payout_approval_needed setting
        platform_settings = PlatformSettings.get_settings()
        if not platform_settings.payout_approval_needed:
            # Auto-process payout if approval is not needed
            try:
                process_payout(payout)
            except Exception as e:
                # If auto-processing fails, set status back to pending for manual review
                payout.status = 'pending'
                payout.save()
                raise serializers.ValidationError(f"Failed to auto-process payout: {str(e)}")
    
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

