from rest_framework import views
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta
from core.users.models import User
from core.booking.models import Booking, Payment
from core.wallet.models import Wallet, WalletTransaction
from core.binary.models import BinaryPair
from core.payout.models import Payout


class DashboardView(views.APIView):
    """
    Dashboard statistics
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        is_admin = user.is_superuser or user.role == 'admin'
        
        if is_admin:
            # Admin dashboard
            stats = {
                'total_users': User.objects.count(),
                'active_buyers': User.objects.filter(is_active_buyer=True).count(),
                'total_bookings': Booking.objects.count(),
                'total_revenue': Payment.objects.filter(status='completed').aggregate(
                    total=Sum('amount')
                )['total'] or 0,
                'total_wallet_balance': Wallet.objects.aggregate(
                    total=Sum('balance')
                )['total'] or 0,
                'pending_payouts': Payout.objects.filter(status='pending').count(),
            }
        else:
            # User dashboard
            wallet = user.wallet if hasattr(user, 'wallet') else None
            
            stats = {
                'wallet_balance': wallet.balance if wallet else 0,
                'total_earnings': wallet.total_earned if wallet else 0,
                'total_withdrawn': wallet.total_withdrawn if wallet else 0,
                'active_bookings': Booking.objects.filter(user=user, status__in=['pre_booked', 'confirmed']).count(),
                'total_bookings': Booking.objects.filter(user=user).count(),
                'binary_pairs': BinaryPair.objects.filter(user=user).count(),
                'pending_payouts': Payout.objects.filter(user=user, status='pending').count(),
            }
        
        return Response(stats)


class SalesReportView(views.APIView):
    """
    Sales report (admin only)
    """
    permission_classes = [IsAdminUser]
    
    def get(self, request):
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        payments = Payment.objects.filter(status='completed')
        
        if start_date:
            payments = payments.filter(payment_date__gte=start_date)
        if end_date:
            payments = payments.filter(payment_date__lte=end_date)
        
        report = {
            'total_sales': payments.aggregate(total=Sum('amount'))['total'] or 0,
            'total_transactions': payments.count(),
            'bookings': Booking.objects.filter(
                payments__in=payments
            ).distinct().count(),
        }
        
        return Response(report)


class UserReportView(views.APIView):
    """
    User activity report
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        is_admin = user.is_superuser or user.role == 'admin'
        
        if is_admin:
            user_id = request.query_params.get('user_id')
            if not user_id:
                return Response({'error': 'user_id required'}, status=400)
            target_user = User.objects.get(id=user_id)
        else:
            target_user = user
        
        report = {
            'user': {
                'id': target_user.id,
                'username': target_user.username,
                'email': target_user.email,
                'is_active_buyer': target_user.is_active_buyer,
            },
            'bookings': Booking.objects.filter(user=target_user).count(),
            'total_paid': Payment.objects.filter(
                user=target_user, status='completed'
            ).aggregate(total=Sum('amount'))['total'] or 0,
            'wallet_balance': target_user.wallet.balance if hasattr(target_user, 'wallet') else 0,
            'binary_pairs': BinaryPair.objects.filter(user=target_user).count(),
            'payouts': Payout.objects.filter(user=target_user).count(),
        }
        
        return Response(report)


class WalletReportView(views.APIView):
    """
    Wallet transaction report
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        is_admin = user.is_superuser or user.role == 'admin'
        
        if is_admin:
            user_id = request.query_params.get('user_id')
            if user_id:
                transactions = WalletTransaction.objects.filter(user_id=user_id)
            else:
                transactions = WalletTransaction.objects.all()
        else:
            transactions = WalletTransaction.objects.filter(user=user)
        
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        if start_date:
            transactions = transactions.filter(created_at__gte=start_date)
        if end_date:
            transactions = transactions.filter(created_at__lte=end_date)
        
        report = {
            'total_transactions': transactions.count(),
            'total_credit': transactions.filter(amount__gt=0).aggregate(
                total=Sum('amount')
            )['total'] or 0,
            'total_debit': abs(transactions.filter(amount__lt=0).aggregate(
                total=Sum('amount')
            )['total'] or 0),
            'by_type': transactions.values('transaction_type').annotate(
                count=Count('id'),
                total=Sum('amount')
            ),
        }
        
        return Response(report)

