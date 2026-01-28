from rest_framework import views
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.exceptions import PermissionDenied
from django.db.models import Sum, Count, Q, Avg, F
from django.utils import timezone
from datetime import timedelta, datetime
from decimal import Decimal
from core.users.models import User
from core.booking.models import Booking, Payment
from core.wallet.models import Wallet, WalletTransaction
from core.binary.models import BinaryPair, BinaryNode, BinaryEarning
from core.binary.utils import get_all_descendant_nodes
from core.payout.models import Payout
from core.notification.models import Notification


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


class DistributorDashboardView(views.APIView):
    """
    Distributor dashboard with team performance, growth trends, and sales activity
    Only accessible to users with is_distributor=True
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        # Check if user is a distributor
        if not user.is_distributor:
            raise PermissionDenied("This endpoint is only available for distributors.")
        
        # Get distributor's binary node
        try:
            distributor_node = BinaryNode.objects.select_related('user').get(user=user)
        except BinaryNode.DoesNotExist:
            return Response({
                'error': 'Binary node not found. Please ensure you have a binary tree structure.'
            }, status=404)
        
        # Get all team members (all descendants)
        all_team_members = self._get_all_team_members(distributor_node)
        
        # Calculate all dashboard data
        dashboard_data = {
            'top_performers': self._get_top_performers(all_team_members, distributor_node),
            'team_growth_trend': self._get_team_growth_trend(all_team_members),
            'team_distribution': self._get_team_distribution(distributor_node),
            'recent_sales_activity': self._get_recent_sales_activity(user),
            'commission_trend': self._get_commission_trend(user),
        }
        
        return Response(dashboard_data)
    
    def _get_all_team_members(self, distributor_node):
        """Get all team members (descendants) in the distributor's binary tree"""
        all_members = []
        
        # Get all left descendants
        left_descendants = get_all_descendant_nodes(distributor_node, 'left')
        all_members.extend(left_descendants)
        
        # Get all right descendants
        right_descendants = get_all_descendant_nodes(distributor_node, 'right')
        all_members.extend(right_descendants)
        
        return all_members
    
    def _get_top_performers(self, team_members, distributor_node):
        """Get top 5 performers based on referral count"""
        performers = []
        
        for node in team_members:
            team_member_user = node.user
            
            # Count total referrals for this team member
            # Direct referrals via referred_by field
            direct_referrals = User.objects.filter(referred_by=team_member_user).count()
            
            # Users who used referral code in bookings
            booking_referrals = Booking.objects.filter(
                referred_by=team_member_user
            ).values('user').distinct().count()
            
            # Get unique count
            all_referred_user_ids = set(
                list(User.objects.filter(referred_by=team_member_user).values_list('id', flat=True)) +
                list(Booking.objects.filter(referred_by=team_member_user).values_list('user_id', flat=True).distinct())
            )
            
            referral_count = len(all_referred_user_ids)
            
            # Determine team (RSA = left, RSB = right)
            team = 'RSA' if node.side == 'left' else 'RSB'
            
            performers.append({
                'name': team_member_user.get_full_name() or team_member_user.username,
                'referrals': referral_count,
                'team': team
            })
        
        # Sort by referral count (descending) and return top 5
        performers.sort(key=lambda x: x['referrals'], reverse=True)
        return performers[:5]
    
    def _get_team_growth_trend(self, team_members):
        """Get monthly team member growth for last 6 months"""
        # Get current date
        now = timezone.now()
        
        # Initialize data for last 6 months
        months_data = {}
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        # Get last 6 months using calendar months
        for i in range(6):
            # Calculate month offset
            month_offset = 5 - i
            year = now.year
            month = now.month - month_offset
            
            # Handle year rollover
            while month <= 0:
                month += 12
                year -= 1
            while month > 12:
                month -= 12
                year += 1
            
            month_key = f"{year}-{month:02d}"
            months_data[month_key] = {
                'month_name': month_names[month - 1],
                'count': 0
            }
        
        # Count team members by month (using BinaryNode created_at)
        for node in team_members:
            created_month = node.created_at.strftime('%Y-%m')
            if created_month in months_data:
                months_data[created_month]['count'] += 1
        
        # Format response
        months = []
        counts = []
        for month_key in sorted(months_data.keys()):
            months.append(months_data[month_key]['month_name'])
            counts.append(months_data[month_key]['count'])
        
        return {
            'months': months,
            'counts': counts
        }
    
    def _get_team_distribution(self, distributor_node):
        """Get RSA (left) vs RSB (right) distribution"""
        # Update counts to ensure accuracy
        distributor_node.update_counts()
        distributor_node.refresh_from_db()
        
        left_count = distributor_node.left_count
        right_count = distributor_node.right_count
        total = left_count + right_count
        
        if total == 0:
            return {
                'rsa_percentage': 0,
                'rsb_percentage': 0,
                'rsa_count': 0,
                'rsb_count': 0
            }
        
        rsa_percentage = round((left_count / total) * 100)
        rsb_percentage = round((right_count / total) * 100)
        
        return {
            'rsa_percentage': rsa_percentage,
            'rsb_percentage': rsb_percentage,
            'rsa_count': left_count,
            'rsb_count': right_count
        }
    
    def _get_recent_sales_activity(self, distributor):
        """Get recent sales activity (binary pairs) with PV calculations"""
        # Get recent binary pairs for distributor (last 20)
        recent_pairs = BinaryPair.objects.filter(
            user=distributor
        ).select_related(
            'left_user', 'right_user'
        ).order_by('-created_at')[:20]
        
        sales_activity = []
        
        for pair in recent_pairs:
            # Calculate Left PV (from left_user's completed payments)
            left_pv = Decimal('0')
            if pair.left_user:
                left_payments = Payment.objects.filter(
                    user=pair.left_user,
                    status='completed'
                ).aggregate(total=Sum('amount'))['total']
                if left_payments:
                    left_pv = Decimal(str(left_payments))
                else:
                    # Fallback to booking amount
                    left_booking = Booking.objects.filter(
                        user=pair.left_user
                    ).order_by('-created_at').first()
                    if left_booking:
                        left_pv = left_booking.booking_amount or Decimal('0')
            
            # Calculate Right PV (from right_user's completed payments)
            right_pv = Decimal('0')
            if pair.right_user:
                right_payments = Payment.objects.filter(
                    user=pair.right_user,
                    status='completed'
                ).aggregate(total=Sum('amount'))['total']
                if right_payments:
                    right_pv = Decimal(str(right_payments))
                else:
                    # Fallback to booking amount
                    right_booking = Booking.objects.filter(
                        user=pair.right_user
                    ).order_by('-created_at').first()
                    if right_booking:
                        right_pv = right_booking.booking_amount or Decimal('0')
            
            # Matched PV is minimum of Left PV and Right PV, or use pair_amount
            matched_pv = min(left_pv, right_pv) if left_pv > 0 and right_pv > 0 else (pair.pair_amount if pair.pair_amount else Decimal('0'))
            
            # Get commission and net amount from BinaryEarning
            commission = pair.pair_amount or pair.earning_amount or Decimal('0')
            net_amount = Decimal('0')
            
            try:
                earning = BinaryEarning.objects.filter(binary_pair=pair).first()
                if earning:
                    net_amount = earning.net_amount
            except BinaryEarning.DoesNotExist:
                pass
            
            # Format date
            date_obj = pair.matched_at or pair.created_at
            formatted_date = date_obj.strftime('%d %b %Y') if date_obj else ''
            
            sales_activity.append({
                'date': formatted_date,
                'left_pv': str(left_pv),
                'right_pv': str(right_pv),
                'matched_pv': str(matched_pv),
                'commission': str(commission),
                'net_amount': str(net_amount),
                'status': pair.status
            })
        
        return sales_activity
    
    def _get_commission_trend(self, distributor):
        """Get monthly commission earnings for last 6 months"""
        # Get all binary earnings for distributor
        earnings = BinaryEarning.objects.filter(
            user=distributor
        ).order_by('created_at')
        
        # Get current date
        now = timezone.now()
        
        # Initialize data for last 6 months
        months_data = {}
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        
        # Get last 6 months using calendar months
        for i in range(6):
            # Calculate month offset
            month_offset = 5 - i
            year = now.year
            month = now.month - month_offset
            
            # Handle year rollover
            while month <= 0:
                month += 12
                year -= 1
            while month > 12:
                month -= 12
                year += 1
            
            month_key = f"{year}-{month:02d}"
            months_data[month_key] = {
                'month_name': month_names[month - 1],
                'amount': Decimal('0')
            }
        
        # Sum earnings by month
        for earning in earnings:
            earning_month = earning.created_at.strftime('%Y-%m')
            if earning_month in months_data:
                months_data[earning_month]['amount'] += earning.net_amount
        
        # Format response
        months = []
        amounts = []
        for month_key in sorted(months_data.keys()):
            months.append(months_data[month_key]['month_name'])
            amounts.append(float(months_data[month_key]['amount']))
        
        return {
            'months': months,
            'amounts': amounts
        }


class AdminDashboardView(views.APIView):
    """
    Admin Dashboard with comprehensive business intelligence data
    Only accessible to admin and staff roles
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        # Check if user is admin or staff
        if not (user.is_superuser or user.role in ['admin', 'staff']):
            raise PermissionDenied("This endpoint is only available for admin and staff users.")
        
        # Aggregate all dashboard data
        dashboard_data = {
            'kpi_cards': self._get_kpi_cards(),
            'booking_trends': self._get_booking_trends(),
            'payment_distribution': self._get_payment_distribution(),
            'staff_performance': self._get_staff_performance(),
            'buyer_growth_trend': self._get_buyer_growth_trend(),
            'buyer_segments': self._get_buyer_segments(),
            'sales_funnel': self._get_sales_funnel(),
            'conversion_rates': self._get_conversion_rates(),
            'pre_bookings': self._get_pre_bookings(),
            'emi_orders': self._get_emi_orders(),
            'cancelled_orders': self._get_cancelled_orders(),
        }
        
        return Response(dashboard_data)
    
    def _get_kpi_cards(self):
        """Calculate all KPI metrics with percentage changes"""
        now = timezone.now()
        
        # Calculate current and previous month date ranges
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 1:
            previous_month_start = now.replace(year=now.year-1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            previous_month_start = now.replace(month=now.month-1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        previous_month_end = current_month_start - timedelta(days=1)
        previous_month_start = previous_month_start.replace(day=1)
        
        # Active Buyers
        current_active_buyers = User.objects.filter(is_active_buyer=True).count()
        previous_active_buyers = User.objects.filter(
            is_active_buyer=True,
            date_joined__lt=current_month_start
        ).count()
        active_buyers_change = self._calculate_percentage_change(current_active_buyers, previous_active_buyers)
        
        # Total Visitors (Total registered users)
        current_total_visitors = User.objects.count()
        previous_total_visitors = User.objects.filter(
            date_joined__lt=current_month_start
        ).count()
        total_visitors_change = self._calculate_percentage_change(current_total_visitors, previous_total_visitors)
        
        # Pre-Booked (Bookings with status='pending')
        pre_booked = Booking.objects.filter(status='pending').count()
        pre_booked_conversion = (pre_booked / current_total_visitors * 100) if current_total_visitors > 0 else 0
        
        # Paid Orders (Bookings with completed payments)
        paid_orders = Booking.objects.filter(
            payments__status='completed'
        ).distinct().count()
        paid_orders_conversion = (paid_orders / pre_booked * 100) if pre_booked > 0 else 0
        
        # Delivered (Bookings with status='completed')
        delivered = Booking.objects.filter(status='completed').count()
        delivered_conversion = (delivered / paid_orders * 100) if paid_orders > 0 else 0
        
        return {
            'active_buyers': {
                'value': current_active_buyers,
                'change': abs(active_buyers_change),
                'trend': 'up' if active_buyers_change >= 0 else 'down'
            },
            'total_visitors': {
                'value': current_total_visitors,
                'change': abs(total_visitors_change),
                'trend': 'up' if total_visitors_change >= 0 else 'down'
            },
            'pre_booked': {
                'value': pre_booked,
                'conversion': round(pre_booked_conversion, 1)
            },
            'paid_orders': {
                'value': paid_orders,
                'conversion': round(paid_orders_conversion, 1)
            },
            'delivered': {
                'value': delivered,
                'conversion': round(delivered_conversion, 1)
            }
        }
    
    def _get_booking_trends(self):
        """Calculate monthly booking data and growth percentage"""
        def _get_trends_for_role(user_role):
            """Get booking trends for a specific user role"""
            now = timezone.now()
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            
            # Get last 4 months of booking data
            months_data = {}
            for i in range(4):
                month_offset = 3 - i
                year = now.year
                month = now.month - month_offset
                
                # Handle year rollover
                while month <= 0:
                    month += 12
                    year -= 1
                while month > 12:
                    month -= 12
                    year += 1
                
                month_key = f"{year}-{month:02d}"
                months_data[month_key] = {
                    'month_name': month_names[month - 1],
                    'count': 0
                }
            
            # Count bookings by month for this role
            bookings = Booking.objects.filter(
                user__role=user_role,
                created_at__gte=datetime(now.year, now.month, 1) - timedelta(days=120)
            )
            
            for booking in bookings:
                booking_month = booking.created_at.strftime('%Y-%m')
                if booking_month in months_data:
                    months_data[booking_month]['count'] += 1
            
            # Format response
            months = []
            booking_counts = []
            sorted_keys = sorted(months_data.keys())
            
            for month_key in sorted_keys:
                months.append(months_data[month_key]['month_name'])
                booking_counts.append(months_data[month_key]['count'])
            
            # Calculate growth percentage (current month vs previous month)
            growth = 0
            if len(booking_counts) >= 2:
                current = booking_counts[-1]
                previous = booking_counts[-2]
                if previous > 0:
                    growth = round(((current - previous) / previous) * 100, 1)
            
            return {
                'months': months,
                'bookings': booking_counts,
                'growth': growth
            }
        
        return {
            'normal_users': _get_trends_for_role('user'),
            'staff_users': _get_trends_for_role('staff')
        }
    
    def _get_payment_distribution(self):
        """Analyze payment types: Full Payment, EMI, Wallet, Mixed"""
        # Get all bookings with completed payments
        bookings_with_payments = Booking.objects.filter(
            payments__status='completed'
        ).distinct().prefetch_related('payments')
        
        full_payment_count = 0
        emi_count = 0
        wallet_count = 0
        mixed_count = 0
        
        for booking in bookings_with_payments:
            payment_methods = set(booking.payments.filter(status='completed').values_list('payment_method', flat=True))
            
            # Check if it's a full payment booking
            if booking.payment_option == 'full_payment' and len(payment_methods) == 1:
                if 'wallet' in payment_methods:
                    wallet_count += 1
                else:
                    full_payment_count += 1
            # Check if it's EMI
            elif booking.payment_option == 'emi_options':
                if len(payment_methods) == 1 and 'wallet' in payment_methods:
                    wallet_count += 1
                else:
                    emi_count += 1
            # Mixed payment methods
            elif len(payment_methods) > 1:
                mixed_count += 1
            # Wallet only
            elif 'wallet' in payment_methods:
                wallet_count += 1
        
        total = full_payment_count + emi_count + wallet_count + mixed_count
        
        if total == 0:
            return {
                'full_payment': {'count': 0, 'percentage': 0.0},
                'emi': {'count': 0, 'percentage': 0.0},
                'wallet': {'count': 0, 'percentage': 0.0},
                'mixed': {'count': 0, 'percentage': 0.0}
            }
        
        return {
            'full_payment': {
                'count': full_payment_count,
                'percentage': round((full_payment_count / total) * 100, 1)
            },
            'emi': {
                'count': emi_count,
                'percentage': round((emi_count / total) * 100, 1)
            },
            'wallet': {
                'count': wallet_count,
                'percentage': round((wallet_count / total) * 100, 1)
            },
            'mixed': {
                'count': mixed_count,
                'percentage': round((mixed_count / total) * 100, 1)
            }
        }
    
    def _get_staff_performance(self):
        """Calculate staff achievement percentages based on bookings processed"""
        # Get all staff users
        staff_users = User.objects.filter(role='staff')
        
        now = timezone.now()
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        staff_performance = []
        
        # Default target: 100 bookings per month (can be adjusted)
        default_target = 100
        
        for staff in staff_users:
            # Count bookings processed by this staff member this month
            # Since there's no direct staff field on Booking, we'll count bookings
            # where payments were accepted by staff (via accept_payment action)
            # For now, we'll use a simpler approach: count bookings created this month
            # and assume staff are involved in processing them
            # In a real scenario, you'd track which staff member processed each booking
            
            # Alternative: Count total bookings and divide by number of staff
            # Or track staff assignments in a separate model
            
            # For this implementation, we'll calculate based on total bookings
            # and assign proportionally, or use a fixed target system
            bookings_processed = Booking.objects.filter(
                created_at__gte=current_month_start
            ).count()
            
            # Simple approach: divide bookings among staff members
            # In production, you'd have a proper tracking mechanism
            if staff_users.count() > 0:
                avg_bookings_per_staff = bookings_processed / staff_users.count()
            else:
                avg_bookings_per_staff = 0
            
            achievement = round((avg_bookings_per_staff / default_target) * 100) if default_target > 0 else 0
            achievement = min(achievement, 100)  # Cap at 100%
            
            staff_performance.append({
                'name': staff.get_full_name() or staff.username or staff.first_name or 'Staff',
                'achievement': achievement
            })
        
        # Sort by achievement descending
        staff_performance.sort(key=lambda x: x['achievement'], reverse=True)
        
        return staff_performance
    
    def _get_buyer_growth_trend(self):
        """Get buyer growth trend over last 6 months - cumulative totals at end of each month"""
        def _get_trend_for_role(user_role):
            """Get buyer growth trend for a specific user role"""
            now = timezone.now()
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            
            # Initialize data for last 6 months
            months_data = []
            for i in range(6):
                month_offset = 5 - i
                year = now.year
                month = now.month - month_offset
                
                # Handle year rollover
                while month <= 0:
                    month += 12
                    year -= 1
                while month > 12:
                    month -= 12
                    year += 1
                
                # Calculate end of month date
                if month == 12:
                    next_month = 1
                    next_year = year + 1
                else:
                    next_month = month + 1
                    next_year = year
                
                month_end = datetime(next_year, next_month, 1) - timedelta(days=1)
                month_end = timezone.make_aware(month_end.replace(hour=23, minute=59, second=59))
                
                months_data.append({
                    'month_name': month_names[month - 1],
                    'month_end': month_end,
                    'year': year,
                    'month': month
                })
            
            # Calculate cumulative counts at end of each month
            months = []
            active_buyers_list = []
            total_buyers_list = []
            
            for month_info in months_data:
                month_end = month_info['month_end']
                
                # Count total users up to end of this month for this role
                total_buyers = User.objects.filter(role=user_role, date_joined__lte=month_end).count()
                
                # Count active buyers up to end of this month for this role
                # Note: This assumes is_active_buyer status is current, not historical
                # For accurate historical data, you'd need to track status changes over time
                active_buyers = User.objects.filter(
                    role=user_role,
                    is_active_buyer=True,
                    date_joined__lte=month_end
                ).count()
                
                months.append(month_info['month_name'])
                active_buyers_list.append(active_buyers)
                total_buyers_list.append(total_buyers)
            
            return {
                'months': months,
                'active_buyers': active_buyers_list,
                'total_buyers': total_buyers_list
            }
        
        return {
            'normal_users': _get_trend_for_role('user'),
            'staff_users': _get_trend_for_role('staff')
        }
    
    def _get_buyer_segments(self):
        """Get buyer category distribution"""
        now = timezone.now()
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Normal users (role='user')
        normal_active_buyers = User.objects.filter(is_active_buyer=True, role='user').count()
        normal_inactive = User.objects.filter(is_active_buyer=False, role='user').count()
        normal_pre_booked = User.objects.filter(role='user', bookings__status='pending').distinct().count()
        normal_new_this_month = User.objects.filter(
            role='user',
            date_joined__gte=current_month_start
        ).count()
        
        # Staff users (role='staff')
        staff_active_buyers = User.objects.filter(is_active_buyer=True, role='staff').count()
        staff_inactive = User.objects.filter(is_active_buyer=False, role='staff').count()
        staff_pre_booked = User.objects.filter(role='staff', bookings__status='pending').distinct().count()
        staff_new_this_month = User.objects.filter(
            role='staff',
            date_joined__gte=current_month_start
        ).count()
        
        return {
            'normal_users': {
                'active_buyers': normal_active_buyers,
                'inactive': normal_inactive,
                'pre_booked': normal_pre_booked,
                'new_this_month': normal_new_this_month
            },
            'staff_users': {
                'active_buyers': staff_active_buyers,
                'inactive': staff_inactive,
                'pre_booked': staff_pre_booked,
                'new_this_month': staff_new_this_month
            }
        }
    
    def _get_sales_funnel(self):
        """Get sales funnel visualization data"""
        def _build_funnel(user_role):
            """Build funnel for a specific user role"""
            total_visitors = User.objects.filter(role=user_role).count()
            interested = User.objects.filter(role=user_role, bookings__status='pending').distinct().count()
            pre_booked = interested  # Same as interested based on our definition
            paid = User.objects.filter(role=user_role, bookings__payments__status='completed').distinct().count()
            delivered = User.objects.filter(role=user_role, bookings__status='completed').distinct().count()
            
            funnel = []
            
            # Visitors
            funnel.append({
                'stage': 'Visitors',
                'count': total_visitors,
                'percentage': 100.0,
                'drop_off': None
            })
            
            # Interested
            interested_pct = (interested / total_visitors * 100) if total_visitors > 0 else 0
            drop_off_1 = 100.0 - interested_pct
            funnel.append({
                'stage': 'Interested',
                'count': interested,
                'percentage': round(interested_pct, 1),
                'drop_off': round(drop_off_1, 1)
            })
            
            # Pre-Booked
            pre_booked_pct = (pre_booked / total_visitors * 100) if total_visitors > 0 else 0
            drop_off_2 = interested_pct - pre_booked_pct
            funnel.append({
                'stage': 'Pre-Booked',
                'count': pre_booked,
                'percentage': round(pre_booked_pct, 1),
                'drop_off': round(drop_off_2, 1)
            })
            
            # Paid
            paid_pct = (paid / total_visitors * 100) if total_visitors > 0 else 0
            drop_off_3 = pre_booked_pct - paid_pct
            funnel.append({
                'stage': 'Paid',
                'count': paid,
                'percentage': round(paid_pct, 1),
                'drop_off': round(drop_off_3, 1)
            })
            
            # Delivered
            delivered_pct = (delivered / total_visitors * 100) if total_visitors > 0 else 0
            drop_off_4 = paid_pct - delivered_pct
            funnel.append({
                'stage': 'Delivered',
                'count': delivered,
                'percentage': round(delivered_pct, 1),
                'drop_off': round(drop_off_4, 1)
            })
            
            return funnel
        
        return {
            'normal_users': _build_funnel('user'),
            'staff_users': _build_funnel('staff')
        }
    
    def _get_conversion_rates(self):
        """Get stage-to-stage conversion rates with trend indicators"""
        def _get_rates_for_role(user_role):
            """Get conversion rates for a specific user role"""
            now = timezone.now()
            current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # Current period data
            total_visitors = User.objects.filter(role=user_role).count()
            interested = User.objects.filter(role=user_role, bookings__status='pending').distinct().count()
            pre_booked = interested
            paid = User.objects.filter(role=user_role, bookings__payments__status='completed').distinct().count()
            delivered = User.objects.filter(role=user_role, bookings__status='completed').distinct().count()
            
            # Previous period data (previous month)
            if now.month == 1:
                prev_month_start = now.replace(year=now.year-1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                prev_month_start = now.replace(month=now.month-1, day=1, hour=0, minute=0, second=0, microsecond=0)
            
            prev_month_end = current_month_start - timedelta(days=1)
            
            prev_visitors = User.objects.filter(role=user_role, date_joined__lt=current_month_start).count()
            prev_interested = User.objects.filter(
                role=user_role,
                bookings__created_at__lt=current_month_start,
                bookings__status='pending'
            ).distinct().count()
            prev_pre_booked = prev_interested
            prev_paid = User.objects.filter(
                role=user_role,
                bookings__payments__completed_at__lt=current_month_start,
                bookings__payments__status='completed'
            ).distinct().count()
            prev_delivered = User.objects.filter(
                role=user_role,
                bookings__completed_at__lt=current_month_start,
                bookings__status='completed'
            ).distinct().count()
            
            # Calculate conversion rates
            visitors_to_interested = (interested / total_visitors * 100) if total_visitors > 0 else 0
            interested_to_pre_booked = (pre_booked / interested * 100) if interested > 0 else 0
            pre_booked_to_paid = (paid / pre_booked * 100) if pre_booked > 0 else 0
            paid_to_delivered = (delivered / paid * 100) if paid > 0 else 0
            
            # Previous period rates
            prev_visitors_to_interested = (prev_interested / prev_visitors * 100) if prev_visitors > 0 else 0
            prev_interested_to_pre_booked = (prev_pre_booked / prev_interested * 100) if prev_interested > 0 else 0
            prev_pre_booked_to_paid = (prev_paid / prev_pre_booked * 100) if prev_pre_booked > 0 else 0
            prev_paid_to_delivered = (prev_delivered / prev_paid * 100) if prev_paid > 0 else 0
            
            # Calculate changes
            change_1 = visitors_to_interested - prev_visitors_to_interested
            change_2 = interested_to_pre_booked - prev_interested_to_pre_booked
            change_3 = pre_booked_to_paid - prev_pre_booked_to_paid
            change_4 = paid_to_delivered - prev_paid_to_delivered
            
            return [
                {
                    'from': 'Visitors',
                    'to': 'Interested',
                    'rate': round(visitors_to_interested, 1),
                    'change': round(abs(change_1), 1),
                    'trend': 'up' if change_1 >= 0 else 'down',
                    'converted_count': interested
                },
                {
                    'from': 'Interested',
                    'to': 'Pre-Booked',
                    'rate': round(interested_to_pre_booked, 1),
                    'change': round(abs(change_2), 1),
                    'trend': 'up' if change_2 >= 0 else 'down',
                    'converted_count': pre_booked
                },
                {
                    'from': 'Pre-Booked',
                    'to': 'Paid',
                    'rate': round(pre_booked_to_paid, 1),
                    'change': round(abs(change_3), 1),
                    'trend': 'up' if change_3 >= 0 else 'down',
                    'converted_count': paid
                },
                {
                    'from': 'Paid',
                    'to': 'Delivered',
                    'rate': round(paid_to_delivered, 1),
                    'change': round(abs(change_4), 1),
                    'trend': 'up' if change_4 >= 0 else 'down',
                    'converted_count': delivered
                }
            ]
        
        return {
            'normal_users': _get_rates_for_role('user'),
            'staff_users': _get_rates_for_role('staff')
        }
    
    def _calculate_percentage_change(self, current, previous):
        """Calculate percentage change between two values"""
        if previous == 0:
            return 0 if current == 0 else 100.0
        return round(((current - previous) / previous) * 100, 1)
    
    def _get_pre_bookings(self):
        """Calculate pre-bookings KPIs and summary data"""
        def _get_pre_bookings_for_role(user_role):
            """Get pre-bookings data for a specific user role"""
            # Total Pre-Bookings: All bookings with status in ['pending', 'active', 'expired']
            pre_booking_statuses = ['pending', 'active', 'expired']
            total_pre_bookings = Booking.objects.filter(
                user__role=user_role,
                status__in=pre_booking_statuses
            ).count()
            
            # Pending: Bookings with status='pending'
            pending_count = Booking.objects.filter(
                user__role=user_role,
                status='pending'
            ).count()
            
            # Confirmed: Bookings with status='active' (confirmed/active buyers)
            confirmed_count = Booking.objects.filter(
                user__role=user_role,
                status='active'
            ).count()
            
            # Expired: Bookings with status='expired'
            expired_count = Booking.objects.filter(
                user__role=user_role,
                status='expired'
            ).count()
            
            # Total Amount: Sum of booking_amount for all pre-bookings
            total_amount_result = Booking.objects.filter(
                user__role=user_role,
                status__in=pre_booking_statuses
            ).aggregate(total=Sum('booking_amount'))
            total_amount = float(total_amount_result['total'] or 0)
            
            return {
                'kpi_cards': {
                    'total_pre_bookings': total_pre_bookings,
                    'pending': pending_count,
                    'confirmed': confirmed_count,
                    'total_amount': round(total_amount, 2)
                },
                'summary': {
                    'total_count': total_pre_bookings,
                    'pending_count': pending_count,
                    'confirmed_count': confirmed_count,
                    'expired_count': expired_count,
                    'total_amount': round(total_amount, 2)
                }
            }
        
        return {
            'normal_users': _get_pre_bookings_for_role('user'),
            'staff_users': _get_pre_bookings_for_role('staff')
        }
    
    def _get_emi_orders(self):
        """Calculate EMI orders KPIs, collection trend, and summary data"""
        def _get_emi_orders_for_role(user_role):
            """Get EMI orders data for a specific user role"""
            now = timezone.now()
            current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # Total EMI Orders: Bookings with payment_option='emi_options'
            total_emi_orders = Booking.objects.filter(
                user__role=user_role,
                payment_option='emi_options'
            ).count()
            
            # Active EMIs: EMI orders that are not completed/cancelled
            active_emis = Booking.objects.filter(
                user__role=user_role,
                payment_option='emi_options',
                status__in=['pending', 'active']
            ).count()
            
            # Monthly Collection: Sum of EMI payments collected in current month
            monthly_collection_result = Payment.objects.filter(
                booking__user__role=user_role,
                booking__payment_option='emi_options',
                status='completed',
                completed_at__gte=current_month_start
            ).aggregate(total=Sum('amount'))
            monthly_collection = float(monthly_collection_result['total'] or 0)
            
            # Pending Amount: Total remaining_amount across all active EMI orders
            pending_amount_result = Booking.objects.filter(
                user__role=user_role,
                payment_option='emi_options',
                status__in=['pending', 'active']
            ).aggregate(total=Sum('remaining_amount'))
            pending_amount = float(pending_amount_result['total'] or 0)
            
            # EMI Collection Trend: Monthly data for last 4 months
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            months_data = {}
            
            for i in range(4):
                month_offset = 3 - i
                year = now.year
                month = now.month - month_offset
                
                # Handle year rollover
                while month <= 0:
                    month += 12
                    year -= 1
                while month > 12:
                    month -= 12
                    year += 1
                
                month_key = f"{year}-{month:02d}"
                months_data[month_key] = {
                    'month_name': month_names[month - 1],
                    'amount': Decimal('0'),
                    'order_count': 0
                }
            
            # Get EMI payments for last 4 months
            emi_payments = Payment.objects.filter(
                booking__user__role=user_role,
                booking__payment_option='emi_options',
                status='completed',
                completed_at__gte=datetime(now.year, now.month, 1) - timedelta(days=120)
            )
            
            for payment in emi_payments:
                payment_month = payment.completed_at.strftime('%Y-%m')
                if payment_month in months_data:
                    months_data[payment_month]['amount'] += Decimal(str(payment.amount))
            
            # Count unique bookings per month
            for month_key in months_data.keys():
                year, month = month_key.split('-')
                month_start = datetime(int(year), int(month), 1)
                if int(month) == 12:
                    month_end = datetime(int(year) + 1, 1, 1) - timedelta(days=1)
                else:
                    month_end = datetime(int(year), int(month) + 1, 1) - timedelta(days=1)
                
                month_start = timezone.make_aware(month_start)
                month_end = timezone.make_aware(month_end.replace(hour=23, minute=59, second=59))
                
                order_count = Payment.objects.filter(
                    booking__user__role=user_role,
                    booking__payment_option='emi_options',
                    status='completed',
                    completed_at__gte=month_start,
                    completed_at__lte=month_end
                ).values('booking').distinct().count()
                
                months_data[month_key]['order_count'] = order_count
            
            # Format trend data
            sorted_keys = sorted(months_data.keys())
            months = []
            amounts = []
            order_counts = []
            
            for month_key in sorted_keys:
                months.append(months_data[month_key]['month_name'])
                amounts.append(float(months_data[month_key]['amount']))
                order_counts.append(months_data[month_key]['order_count'])
            
            # Summary data
            completed_count = Booking.objects.filter(
                user__role=user_role,
                payment_option='emi_options',
                status='completed'
            ).count()
            
            cancelled_count = Booking.objects.filter(
                user__role=user_role,
                payment_option='emi_options',
                status='cancelled'
            ).count()
            
            total_collected_result = Payment.objects.filter(
                booking__user__role=user_role,
                booking__payment_option='emi_options',
                status='completed'
            ).aggregate(total=Sum('amount'))
            total_collected = float(total_collected_result['total'] or 0)
            
            return {
                'kpi_cards': {
                    'total_emi_orders': total_emi_orders,
                    'active_emis': active_emis,
                    'monthly_collection': round(monthly_collection, 2),
                    'pending_amount': round(pending_amount, 2)
                },
                'collection_trend': {
                    'months': months,
                    'amounts': amounts,
                    'order_counts': order_counts
                },
                'summary': {
                    'total_count': total_emi_orders,
                    'active_count': active_emis,
                    'completed_count': completed_count,
                    'cancelled_count': cancelled_count,
                    'total_collected': round(total_collected, 2),
                    'total_pending': round(pending_amount, 2)
                }
            }
        
        return {
            'normal_users': _get_emi_orders_for_role('user'),
            'staff_users': _get_emi_orders_for_role('staff')
        }
    
    def _get_cancelled_orders(self):
        """Calculate cancelled orders KPIs, cancellation trend, and summary with refund status"""
        def _get_cancelled_orders_for_role(user_role):
            """Get cancelled orders data for a specific user role"""
            # Total Cancelled: Bookings with status='cancelled'
            total_cancelled = Booking.objects.filter(
                user__role=user_role,
                status='cancelled'
            ).count()
            
            # Total Amount: Sum of total_amount for cancelled bookings
            total_amount_result = Booking.objects.filter(
                user__role=user_role,
                status='cancelled'
            ).aggregate(total=Sum('total_amount'))
            total_amount = float(total_amount_result['total'] or 0)
            
            # Refund Pending: Cancelled bookings with payments that haven't been refunded
            # Get all cancelled bookings with payments
            cancelled_bookings = Booking.objects.filter(
                user__role=user_role,
                status='cancelled',
                total_paid__gt=0
            ).prefetch_related('payments')
            
            refund_pending_count = 0
            refund_processed_count = 0
            total_refunded_amount = Decimal('0')
            pending_refund_amount = Decimal('0')
            
            for booking in cancelled_bookings:
                # Check if any payment has status='refunded'
                has_refunded_payment = booking.payments.filter(status='refunded').exists()
                
                if has_refunded_payment:
                    refund_processed_count += 1
                    # Sum refunded amounts
                    refunded_payments = booking.payments.filter(status='refunded')
                    for payment in refunded_payments:
                        total_refunded_amount += Decimal(str(payment.amount))
                else:
                    refund_pending_count += 1
                    # Calculate pending refund amount (total_paid that hasn't been refunded)
                    pending_refund_amount += Decimal(str(booking.total_paid))
            
            # Cancellation Rate: (Total Cancelled / Total Bookings) * 100
            total_bookings = Booking.objects.filter(user__role=user_role).count()
            cancellation_rate = 0.0
            if total_bookings > 0:
                cancellation_rate = round((total_cancelled / total_bookings) * 100, 1)
            
            # Cancellation Trend: Monthly cancellation counts for last 4 months
            now = timezone.now()
            month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
            months_data = {}
            
            for i in range(4):
                month_offset = 3 - i
                year = now.year
                month = now.month - month_offset
                
                # Handle year rollover
                while month <= 0:
                    month += 12
                    year -= 1
                while month > 12:
                    month -= 12
                    year += 1
                
                month_key = f"{year}-{month:02d}"
                months_data[month_key] = {
                    'month_name': month_names[month - 1],
                    'count': 0
                }
            
            # Count cancelled bookings by month
            cancelled_bookings_all = Booking.objects.filter(
                user__role=user_role,
                status='cancelled',
                created_at__gte=datetime(now.year, now.month, 1) - timedelta(days=120)
            )
            
            for booking in cancelled_bookings_all:
                cancelled_month = booking.created_at.strftime('%Y-%m')
                if cancelled_month in months_data:
                    months_data[cancelled_month]['count'] += 1
            
            # Format trend data
            sorted_keys = sorted(months_data.keys())
            months = []
            counts = []
            
            for month_key in sorted_keys:
                months.append(months_data[month_key]['month_name'])
                counts.append(months_data[month_key]['count'])
            
            return {
                'kpi_cards': {
                    'total_cancelled': total_cancelled,
                    'total_amount': round(total_amount, 2),
                    'refund_pending': refund_pending_count,
                    'cancellation_rate': cancellation_rate
                },
                'cancellation_trend': {
                    'months': months,
                    'counts': counts
                },
                'summary': {
                    'total_count': total_cancelled,
                    'total_amount': round(total_amount, 2),
                    'refund_pending_count': refund_pending_count,
                    'refund_processed_count': refund_processed_count,
                    'total_refunded_amount': round(float(total_refunded_amount), 2),
                    'pending_refund_amount': round(float(pending_refund_amount), 2)
                }
            }
        
        return {
            'normal_users': _get_cancelled_orders_for_role('user'),
            'staff_users': _get_cancelled_orders_for_role('staff')
        }


class ComprehensiveReportsView(views.APIView):
    """
    Comprehensive reports endpoint that aggregates all dashboard data
    Only accessible to admin and staff roles
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        # Check if user is admin or staff
        if not (user.is_superuser or user.role in ['admin', 'staff']):
            raise PermissionDenied("This endpoint is only available for admin and staff users.")
        
        # Get requested sections from query parameter
        sections_param = request.query_params.get('sections', '')
        if sections_param:
            requested_sections = [s.strip() for s in sections_param.split(',')]
        else:
            # If no sections specified, return all
            requested_sections = [
                'transaction_history',
                'investment_logs',
                'bv_logs',
                'referral_commission',
                'team_commission',
                'login_history',
                'notification_history'
            ]
        
        # Extract pagination and filter parameters
        pagination_params = {
            'transaction': {
                'page': int(request.query_params.get('transaction_page', 1)),
                'page_size': int(request.query_params.get('transaction_page_size', 20)),
            },
            'investment': {
                'page': int(request.query_params.get('investment_page', 1)),
                'page_size': int(request.query_params.get('investment_page_size', 20)),
            },
            'bv': {
                'page': int(request.query_params.get('bv_page', 1)),
                'page_size': int(request.query_params.get('bv_page_size', 20)),
            },
            'referral': {
                'page': int(request.query_params.get('referral_page', 1)),
                'page_size': int(request.query_params.get('referral_page_size', 20)),
            },
            'team': {
                'page': int(request.query_params.get('team_page', 1)),
                'page_size': int(request.query_params.get('team_page_size', 20)),
            },
            'notification': {
                'page': int(request.query_params.get('notification_page', 1)),
                'page_size': int(request.query_params.get('notification_page_size', 20)),
            },
        }
        
        filter_params = {
            'transaction_status': request.query_params.get('transaction_status', ''),
            'investment_status': request.query_params.get('investment_status', ''),
            'bv_status': request.query_params.get('bv_status', ''),
            'notification_status': request.query_params.get('notification_status', ''),
        }
        
        # Build response with requested sections
        response_data = {}
        
        if 'transaction_history' in requested_sections:
            response_data['transaction_history'] = self._get_transaction_history(
                pagination_params['transaction'], 
                filter_params['transaction_status']
            )
        
        if 'investment_logs' in requested_sections:
            response_data['investment_logs'] = self._get_investment_logs(
                pagination_params['investment'],
                filter_params['investment_status']
            )
        
        if 'bv_logs' in requested_sections:
            response_data['bv_logs'] = self._get_bv_logs(
                pagination_params['bv'],
                filter_params['bv_status']
            )
        
        if 'referral_commission' in requested_sections:
            response_data['referral_commission'] = self._get_referral_commission(
                pagination_params['referral']
            )
        
        if 'team_commission' in requested_sections:
            response_data['team_commission'] = self._get_team_commission(
                pagination_params['team']
            )
        
        if 'login_history' in requested_sections:
            response_data['login_history'] = self._get_login_history()
        
        if 'notification_history' in requested_sections:
            response_data['notification_history'] = self._get_notification_history(
                pagination_params['notification'],
                filter_params['notification_status']
            )
        
        return Response(response_data)
    
    def _paginate_queryset(self, queryset, page, page_size, max_page_size=100):
        """
        Paginate a queryset and return paginated data with metadata
        
        Args:
            queryset: Django queryset to paginate
            page: Page number (1-indexed)
            page_size: Number of items per page
            max_page_size: Maximum allowed page size
            
        Returns:
            dict with 'pagination' metadata and 'results' list
        """
        # Validate and cap page_size
        page_size = min(max(1, page_size), max_page_size)
        page = max(1, page)
        
        # Get total count
        total_count = queryset.count()
        
        # Calculate total pages
        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1
        
        # Ensure page is within bounds
        page = min(page, total_pages)
        
        # Calculate offset
        offset = (page - 1) * page_size
        
        # Get paginated results
        results = list(queryset[offset:offset + page_size])
        
        # Build pagination metadata
        pagination_meta = {
            'total_count': total_count,
            'total_pages': total_pages,
            'current_page': page,
            'page_size': page_size,
            'has_next': page < total_pages,
            'has_previous': page > 1
        }
        
        return {
            'pagination': pagination_meta,
            'results': results
        }
    
    def _apply_transaction_status_filter(self, queryset, status_filter):
        """
        Apply status filter to wallet transactions
        Status can be: Completed (positive amounts) or Deducted (negative amounts)
        """
        if not status_filter:
            return queryset
        
        statuses = [s.strip() for s in status_filter.split(',')]
        
        if 'Completed' in statuses and 'Deducted' not in statuses:
            return queryset.filter(amount__gt=0)
        elif 'Deducted' in statuses and 'Completed' not in statuses:
            return queryset.filter(amount__lt=0)
        else:
            # Both or neither - return all
            return queryset
    
    def _apply_investment_status_filter(self, queryset, status_filter):
        """
        Apply status filter to bookings
        Status can be: pending, active, completed, delivered, cancelled, expired
        """
        if not status_filter:
            return queryset
        
        statuses = [s.strip() for s in status_filter.split(',')]
        return queryset.filter(status__in=statuses)
    
    def _apply_bv_status_filter(self, queryset, status_filter):
        """
        Apply status filter to binary pairs
        Status can be: pending, matched, processed
        """
        if not status_filter:
            return queryset
        
        statuses = [s.strip() for s in status_filter.split(',')]
        return queryset.filter(status__in=statuses)
    
    def _apply_notification_status_filter(self, queryset, status_filter):
        """
        Apply status filter to notifications
        Status can be: read, unread
        """
        if not status_filter:
            return queryset
        
        statuses = [s.strip() for s in status_filter.split(',')]
        
        if 'read' in statuses and 'unread' not in statuses:
            return queryset.filter(is_read=True)
        elif 'unread' in statuses and 'read' not in statuses:
            return queryset.filter(is_read=False)
        else:
            # Both or neither - return all
            return queryset
    
    def _get_transaction_history(self, pagination_params, status_filter=''):
        """Get transaction history data with pagination and filtering"""
        # Get all wallet transactions
        all_transactions = WalletTransaction.objects.all()
        
        # Apply status filter for detailed list
        filtered_transactions = self._apply_transaction_status_filter(all_transactions, status_filter)
        
        # Get payment transactions for success/failure calculation
        all_payments = Payment.objects.all()
        
        # Summary cards (based on all transactions, not filtered)
        total_transactions = all_transactions.count()
        total_amount_result = all_transactions.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        total_amount = abs(float(total_amount_result))
        
        # Success rate and failed count based on Payment model (actual payment success/failure)
        # Wallet transactions don't have a status field - they're all successful by design
        successful_payments = all_payments.filter(status='completed').count()
        failed_payments = all_payments.filter(status='failed').count()
        pending_payments = all_payments.filter(status='pending').count()
        refunded_payments = all_payments.filter(status='refunded').count()
        
        # Calculate success rate: completed / (completed + failed) * 100
        # Exclude pending (not yet processed) and refunded (were successful but refunded)
        processed_payments = successful_payments + failed_payments
        
        if processed_payments > 0:
            success_rate = (successful_payments / processed_payments * 100)
        else:
            # If no processed payments, check if there are any payments at all
            total_payments = all_payments.count()
            if total_payments > 0:
                # All payments are pending - can't calculate success rate yet
                success_rate = 0.0
            else:
                # No payments at all - consider all wallet transactions as successful (100%)
                success_rate = 100.0 if total_transactions > 0 else 0.0
        
        failed = failed_payments
        
        # Transaction type summary
        type_summary = all_transactions.values('transaction_type').annotate(
            count=Count('id'),
            total_amount=Sum('amount'),
            avg_amount=Avg('amount')
        ).order_by('-count')
        
        # Calculate success rate per type
        # For wallet transactions, success rate is based on whether they're credit (positive) or debit (negative)
        # Credits are successful additions, debits are successful deductions
        # Since wallet transactions don't fail (they're only created on success), we calculate based on payment success
        type_summary_list = []
        for item in type_summary:
            type_transactions = all_transactions.filter(transaction_type=item['transaction_type'])
            type_total = item['count']
            
            # For transaction types that relate to payments, check payment status
            # For others, assume 100% success (wallet transactions are only created on success)
            if item['transaction_type'] in ['DEPOSIT', 'REFUND']:
                # These might relate to payments - check if we can find related payments
                # For now, assume successful (wallet transactions are only created on success)
                type_success_rate = 100.0
            else:
                # All wallet transactions are successful by design
                type_success_rate = 100.0 if type_total > 0 else 0.0
            
            type_summary_list.append({
                'type': item['transaction_type'],
                'count': item['count'],
                'total_amount': str(abs(float(item['total_amount'] or 0))),
                'avg_amount': str(abs(float(item['avg_amount'] or 0))),
                'success_rate': round(type_success_rate, 1)
            })
        
        # Weekly transaction trend (last 7 days)
        now = timezone.now()
        week_data = {}
        for i in range(7):
            day = now - timedelta(days=6-i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            day_transactions = all_transactions.filter(created_at__gte=day_start, created_at__lte=day_end)
            day_count = day_transactions.count()
            day_amount = abs(float(day_transactions.aggregate(total=Sum('amount'))['total'] or 0))
            
            day_name = day.strftime('%a')
            week_data[day_name] = {
                'transactions': day_count,
                'amount': day_amount
            }
        
        # Paginate transactions
        transactions_queryset = filtered_transactions.select_related('user').order_by('-created_at')
        paginated_data = self._paginate_queryset(
            transactions_queryset,
            pagination_params['page'],
            pagination_params['page_size']
        )
        
        # Format transaction results
        transactions_list = []
        for txn in paginated_data['results']:
            transactions_list.append({
                'id': txn.id,
                'transaction_id': f"TXN-{txn.created_at.year}-{str(txn.id).zfill(3)}",
                'date': txn.created_at.strftime('%Y-%m-%d'),
                'user': {
                    'id': txn.user.id,
                    'name': txn.user.get_full_name() or txn.user.username,
                    'email': txn.user.email or ''
                },
                'type': txn.transaction_type,
                'amount': str(abs(float(txn.amount))),
                'status': 'Completed' if txn.amount > 0 else 'Deducted',
                'description': txn.description or '',
                'created_at': txn.created_at.isoformat()
            })
        
        return {
            'summary_cards': {
                'total_transactions': total_transactions,
                'total_amount': f"{total_amount:,.2f}",
                'success_rate': round(success_rate, 1),
                'failed': failed
            },
            'transaction_type_summary': type_summary_list,
            'weekly_trend': week_data,
            'all_transactions': {
                'pagination': paginated_data['pagination'],
                'results': transactions_list
            }
        }
    
    def _get_investment_logs(self, pagination_params, status_filter=''):
        """Get investment logs data with pagination and filtering"""
        # Get all bookings
        all_bookings = Booking.objects.all()
        
        # Apply status filter for detailed list
        filtered_bookings = self._apply_investment_status_filter(all_bookings, status_filter)
        
        # Summary cards (based on all bookings, not filtered)
        total_investments = all_bookings.count()
        total_amount_result = all_bookings.aggregate(total=Sum('booking_amount'))['total'] or Decimal('0')
        total_amount = float(total_amount_result)
        avg_investment_result = all_bookings.aggregate(avg=Avg('booking_amount'))['avg'] or Decimal('0')
        avg_investment = float(avg_investment_result) if total_investments > 0 else 0
        active_investments = all_bookings.filter(status__in=['pending', 'active']).count()
        
        # Investment type summary
        investment_type_summary = []
        
        # Pre-Booking
        pre_booking = all_bookings.filter(payment_option='full_payment', status='pending')
        pre_booking_count = pre_booking.count()
        pre_booking_total = float(pre_booking.aggregate(total=Sum('booking_amount'))['total'] or 0)
        pre_booking_avg = (pre_booking_total / pre_booking_count) if pre_booking_count > 0 else 0
        pre_booking_completed = all_bookings.filter(payment_option='full_payment', status='completed').count()
        pre_booking_pending = pre_booking_count
        
        investment_type_summary.append({
            'type': 'Pre-Booking',
            'count': pre_booking_count,
            'total_amount': f"{pre_booking_total:,.2f}",
            'avg_amount': f"{pre_booking_avg:,.2f}",
            'completed': pre_booking_completed,
            'pending': pre_booking_pending
        })
        
        # Full Payment
        full_payment = all_bookings.filter(payment_option='full_payment', status__in=['active', 'completed'])
        full_payment_count = full_payment.count()
        full_payment_total = float(full_payment.aggregate(total=Sum('booking_amount'))['total'] or 0)
        full_payment_avg = (full_payment_total / full_payment_count) if full_payment_count > 0 else 0
        full_payment_completed = all_bookings.filter(payment_option='full_payment', status='completed').count()
        full_payment_pending = all_bookings.filter(payment_option='full_payment', status='active').count()
        
        investment_type_summary.append({
            'type': 'Full Payment',
            'count': full_payment_count,
            'total_amount': f"{full_payment_total:,.2f}",
            'avg_amount': f"{full_payment_avg:,.2f}",
            'completed': full_payment_completed,
            'pending': full_payment_pending
        })
        
        # EMI
        emi = all_bookings.filter(payment_option='emi_options')
        emi_count = emi.count()
        emi_total = float(emi.aggregate(total=Sum('booking_amount'))['total'] or 0)
        emi_avg = (emi_total / emi_count) if emi_count > 0 else 0
        emi_completed = emi.filter(status='completed').count()
        emi_pending = emi.filter(status__in=['pending', 'active']).count()
        
        investment_type_summary.append({
            'type': 'EMI',
            'count': emi_count,
            'total_amount': f"{emi_total:,.2f}",
            'avg_amount': f"{emi_avg:,.2f}",
            'completed': emi_completed,
            'pending': emi_pending
        })
        
        # Top Up (bookings with status='active' that have additional payments)
        # Top ups are bookings where total_paid > booking_amount
        top_up_bookings = []
        for booking in all_bookings.filter(status='active'):
            if float(booking.total_paid) > float(booking.booking_amount):
                top_up_bookings.append(booking)
        
        top_up_count = len(top_up_bookings)
        top_up_total = sum(float(b.total_paid) for b in top_up_bookings)
        top_up_avg = (top_up_total / top_up_count) if top_up_count > 0 else 0
        top_up_completed = 0  # Top ups don't have a completed status
        top_up_pending = top_up_count
        
        investment_type_summary.append({
            'type': 'Top Up',
            'count': top_up_count,
            'total_amount': f"{top_up_total:,.2f}",
            'avg_amount': f"{top_up_avg:,.2f}",
            'completed': top_up_completed,
            'pending': top_up_pending
        })
        
        # Payment method summary
        all_payments = Payment.objects.filter(status='completed')
        payment_method_summary = all_payments.values('payment_method').annotate(
            count=Count('id'),
            total_amount=Sum('amount')
        )
        
        total_payment_amount = float(all_payments.aggregate(total=Sum('amount'))['total'] or 0)
        
        payment_method_list = []
        for item in payment_method_summary:
            method_total = float(item['total_amount'] or 0)
            percentage = (method_total / total_payment_amount * 100) if total_payment_amount > 0 else 0
            
            payment_method_list.append({
                'payment_method': item['payment_method'],
                'count': item['count'],
                'total_amount': f"{method_total:,.2f}",
                'percentage': round(percentage, 1)
            })
        
        # Paginate bookings
        bookings_queryset = filtered_bookings.select_related('user', 'vehicle_model').order_by('-created_at')
        paginated_data = self._paginate_queryset(
            bookings_queryset,
            pagination_params['page'],
            pagination_params['page_size']
        )
        
        # Format booking results
        bookings_list = []
        for booking in paginated_data['results']:
            bookings_list.append({
                'id': booking.id,
                'booking_number': booking.booking_number,
                'user': {
                    'id': booking.user.id,
                    'name': booking.user.get_full_name() or booking.user.username,
                    'email': booking.user.email or ''
                },
                'vehicle_model': booking.vehicle_model.name if booking.vehicle_model else '',
                'booking_amount': f"{float(booking.booking_amount):,.2f}",
                'payment_option': booking.payment_option,
                'status': booking.status,
                'total_paid': f"{float(booking.total_paid):,.2f}",
                'remaining_amount': f"{float(booking.remaining_amount):,.2f}",
                'created_at': booking.created_at.isoformat()
            })
        
        return {
            'summary_cards': {
                'total_investments': total_investments,
                'total_amount': f"{total_amount:,.2f}",
                'avg_investment': f"{avg_investment:,.2f}",
                'active_investments': active_investments
            },
            'investment_type_summary': investment_type_summary,
            'payment_method_summary': payment_method_list,
            'detailed_bookings': {
                'pagination': paginated_data['pagination'],
                'results': bookings_list
            }
        }
    
    def _get_bv_logs(self, pagination_params, status_filter=''):
        """Get BV (Business Volume) logs data with pagination and filtering"""
        # Get all binary pairs
        all_pairs = BinaryPair.objects.all()
        
        # Apply status filter for detailed list
        filtered_pairs = self._apply_bv_status_filter(all_pairs, status_filter)
        
        # Summary cards (based on all pairs, not filtered)
        total_bv_generated = float(all_pairs.aggregate(total=Sum('pair_amount'))['total'] or 0)
        
        # Total BV Distributed (from BinaryEarning)
        all_earnings = BinaryEarning.objects.all()
        total_bv_distributed = float(all_earnings.aggregate(total=Sum('amount'))['total'] or 0)
        
        # Total BV Used (processed pairs)
        used_pairs = all_pairs.filter(status='processed')
        total_bv_used = float(used_pairs.aggregate(total=Sum('pair_amount'))['total'] or 0)
        
        # Active BV (pending + matched pairs)
        active_pairs = all_pairs.filter(status__in=['pending', 'matched'])
        active_bv = float(active_pairs.aggregate(total=Sum('pair_amount'))['total'] or 0)
        
        # BV Type Summary
        bv_type_summary = []
        
        # Generated
        generated_count = all_pairs.count()
        generated_total = total_bv_generated
        generated_avg = (generated_total / generated_count) if generated_count > 0 else 0
        generated_active = active_pairs.count()
        
        bv_type_summary.append({
            'type': 'Generated',
            'count': generated_count,
            'total_amount': f"{generated_total:,.2f}",
            'avg_amount': f"{generated_avg:,.2f}",
            'active': generated_active
        })
        
        # Distributed
        distributed_count = all_earnings.count()
        distributed_total = total_bv_distributed
        distributed_avg = (distributed_total / distributed_count) if distributed_count > 0 else 0
        distributed_active = distributed_count  # All distributed are considered active
        
        bv_type_summary.append({
            'type': 'Distributed',
            'count': distributed_count,
            'total_amount': f"{distributed_total:,.2f}",
            'avg_amount': f"{distributed_avg:,.2f}",
            'active': distributed_active
        })
        
        # Used
        used_count = used_pairs.count()
        used_total = total_bv_used
        used_avg = (used_total / used_count) if used_count > 0 else 0
        used_active = 0  # Used pairs are not active
        
        bv_type_summary.append({
            'type': 'Used',
            'count': used_count,
            'total_amount': f"{used_total:,.2f}",
            'avg_amount': f"{used_avg:,.2f}",
            'active': used_active
        })
        
        # Expired (pairs that are expired - if status exists)
        expired_pairs = all_pairs.filter(status='expired') if hasattr(BinaryPair, 'status') else all_pairs.none()
        expired_count = expired_pairs.count()
        expired_total = float(expired_pairs.aggregate(total=Sum('pair_amount'))['total'] or 0)
        expired_avg = (expired_total / expired_count) if expired_count > 0 else 0
        
        bv_type_summary.append({
            'type': 'Expired',
            'count': expired_count,
            'total_amount': f"{expired_total:,.2f}",
            'avg_amount': f"{expired_avg:,.2f}",
            'active': 0
        })
        
        # BV Source Summary
        # Booking source (BV from bookings/payments)
        booking_bv = float(Payment.objects.filter(status='completed').aggregate(total=Sum('amount'))['total'] or 0)
        
        # Commission source (BV from commissions - BinaryEarning amounts)
        commission_bv = total_bv_distributed
        
        total_bv_source = booking_bv + commission_bv
        
        bv_source_summary = []
        
        booking_percentage = (booking_bv / total_bv_source * 100) if total_bv_source > 0 else 0
        bv_source_summary.append({
            'source': 'Booking',
            'count': Payment.objects.filter(status='completed').count(),
            'total_amount': f"{booking_bv:,.2f}",
            'percentage': round(booking_percentage, 1)
        })
        
        commission_percentage = (commission_bv / total_bv_source * 100) if total_bv_source > 0 else 0
        bv_source_summary.append({
            'source': 'Commission',
            'count': all_earnings.count(),
            'total_amount': f"{commission_bv:,.2f}",
            'percentage': round(commission_percentage, 1)
        })
        
        # Paginate binary pairs
        pairs_queryset = filtered_pairs.select_related('user', 'left_user', 'right_user').order_by('-created_at')
        paginated_data = self._paginate_queryset(
            pairs_queryset,
            pagination_params['page'],
            pagination_params['page_size']
        )
        
        # Format pair results
        pairs_list = []
        for pair in paginated_data['results']:
            pairs_list.append({
                'id': pair.id,
                'user': {
                    'id': pair.user.id,
                    'name': pair.user.get_full_name() or pair.user.username,
                    'email': pair.user.email or ''
                },
                'left_user': {
                    'id': pair.left_user.id if pair.left_user else None,
                    'name': pair.left_user.get_full_name() or pair.left_user.username if pair.left_user else ''
                } if pair.left_user else None,
                'right_user': {
                    'id': pair.right_user.id if pair.right_user else None,
                    'name': pair.right_user.get_full_name() or pair.right_user.username if pair.right_user else ''
                } if pair.right_user else None,
                'pair_amount': f"{float(pair.pair_amount):,.2f}",
                'earning_amount': f"{float(pair.earning_amount):,.2f}",
                'status': pair.status,
                'pair_number_after_activation': pair.pair_number_after_activation,
                'extra_deduction_applied': f"{float(pair.extra_deduction_applied):,.2f}",
                'created_at': pair.created_at.isoformat(),
                'processed_at': pair.processed_at.isoformat() if pair.processed_at else None
            })
        
        return {
            'summary_cards': {
                'total_bv_generated': f"{total_bv_generated:,.2f}",
                'total_bv_distributed': f"{total_bv_distributed:,.2f}",
                'total_bv_used': f"{total_bv_used:,.2f}",
                'active_bv': f"{active_bv:,.2f}"
            },
            'bv_type_summary': bv_type_summary,
            'bv_source_summary': bv_source_summary,
            'detailed_pairs': {
                'pagination': paginated_data['pagination'],
                'results': pairs_list
            }
        }
    
    def _get_referral_commission(self, pagination_params):
        """Get referral commission data with pagination"""
        # Get referral commission transactions (REFERRAL_BONUS)
        referral_transactions = WalletTransaction.objects.filter(
            transaction_type='REFERRAL_BONUS'
        )
        
        # Summary cards
        total_commissions = referral_transactions.count()
        total_amount_result = referral_transactions.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        total_amount = float(total_amount_result)
        
        # Calculate TDS for referral commissions (20% typically)
        # TDS is stored in TDS_DEDUCTION transactions
        referral_tds = WalletTransaction.objects.filter(
            transaction_type='TDS_DEDUCTION',
            description__icontains='referral'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        referral_tds_amount = abs(float(referral_tds))
        
        # Paid amount (transactions that have been processed)
        paid_amount = total_amount  # All referral bonuses are considered paid when credited
        
        # Pending amount (if any pending referral commissions exist)
        pending_amount = 0  # Referral bonuses are credited immediately, so no pending
        
        avg_commission = (total_amount / total_commissions) if total_commissions > 0 else 0
        
        # Top Referrer Performance
        # Get users who have referred others
        referrers = User.objects.filter(referrals__isnull=False).distinct()
        
        top_referrers = []
        for referrer in referrers[:5]:  # Top 5
            # Count referrals
            referrals_count = User.objects.filter(referred_by=referrer).count()
            referrals_count += Booking.objects.filter(referred_by=referrer).values('user').distinct().count()
            
            # Get referral commission amount
            referrer_commissions = WalletTransaction.objects.filter(
                user=referrer,
                transaction_type='REFERRAL_BONUS'
            )
            referrer_total = float(referrer_commissions.aggregate(total=Sum('amount'))['total'] or 0)
            
            # Calculate TDS (10% of total typically, but using 20% as per system)
            referrer_tds = referrer_total * 0.20  # 20% TDS
            referrer_net = referrer_total - referrer_tds
            
            # Paid and pending counts
            referrer_paid = referrer_commissions.count()  # All are paid
            referrer_pending = 0
            
            top_referrers.append({
                'referrer': referrer.get_full_name() or referrer.username,
                'referrals': referrals_count,
                'total_amount': f"{referrer_total:,.2f}",
                'tds': f"{referrer_tds:,.2f}",
                'net_amount': f"{referrer_net:,.2f}",
                'paid': referrer_paid,
                'pending': referrer_pending
            })
        
        # Sort by total_amount descending
        top_referrers.sort(key=lambda x: float(x['total_amount'].replace(',', '')), reverse=True)
        
        # Commission Status Summary
        # All referral commissions are considered completed (they're credited immediately)
        completed_count = total_commissions
        completed_total = total_amount
        completed_tds = referral_tds_amount
        completed_net = total_amount - completed_tds
        
        status_summary = [{
            'status': 'Completed',
            'count': completed_count,
            'total_amount': f"{completed_total:,.2f}",
            'tds': f"{completed_tds:,.2f}",
            'net_amount': f"{completed_net:,.2f}"
        }]
        
        # Add pending if any
        if pending_amount > 0:
            status_summary.append({
                'status': 'Pending',
                'count': 0,
                'total_amount': f"{pending_amount:,.2f}",
                'tds': f"{pending_amount * 0.20:,.2f}",
                'net_amount': f"{pending_amount * 0.80:,.2f}"
            })
        
        # Paginate referral commissions
        commissions_queryset = referral_transactions.select_related('user').order_by('-created_at')
        paginated_data = self._paginate_queryset(
            commissions_queryset,
            pagination_params['page'],
            pagination_params['page_size']
        )
        
        # Format commission results
        commissions_list = []
        for txn in paginated_data['results']:
            commissions_list.append({
                'id': txn.id,
                'transaction_id': f"REF-{txn.created_at.year}-{str(txn.id).zfill(3)}",
                'user': {
                    'id': txn.user.id,
                    'name': txn.user.get_full_name() or txn.user.username,
                    'email': txn.user.email or ''
                },
                'amount': f"{float(txn.amount):,.2f}",
                'referral_for': txn.description or '',
                'created_at': txn.created_at.isoformat()
            })
        
        return {
            'summary_cards': {
                'total_commissions': total_commissions,
                'total_amount': f"{total_amount:,.2f}",
                'paid_amount': f"{paid_amount:,.2f}",
                'pending_amount': f"{pending_amount:,.2f}",
                'avg_commission': f"{avg_commission:,.2f}"
            },
            'top_referrer_performance': top_referrers[:5],
            'commission_status_summary': status_summary,
            'detailed_commissions': {
                'pagination': paginated_data['pagination'],
                'results': commissions_list
            }
        }
    
    def _get_team_commission(self, pagination_params):
        """Get team commission (binary) data with pagination"""
        # Get all binary earnings
        all_earnings = BinaryEarning.objects.all()
        all_pairs = BinaryPair.objects.all()
        
        # Summary cards
        total_commissions = all_earnings.count()
        total_pairs = all_pairs.count()
        total_amount_result = all_earnings.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        total_amount = float(total_amount_result)
        
        # Pool Money (20% of total typically, but calculate from TDS and extra deductions)
        pool_money_tds = abs(float(WalletTransaction.objects.filter(
            transaction_type='TDS_DEDUCTION',
            description__icontains='binary pair'
        ).aggregate(total=Sum('amount'))['total'] or 0))
        
        pool_money_extra = abs(float(WalletTransaction.objects.filter(
            transaction_type='EXTRA_DEDUCTION'
        ).aggregate(total=Sum('amount'))['total'] or 0))
        
        pool_money = pool_money_tds + pool_money_extra
        
        # Net Payout (sum of net_amount from BinaryEarning)
        net_payout_result = all_earnings.aggregate(total=Sum('net_amount'))['total'] or Decimal('0')
        net_payout = float(net_payout_result)
        
        avg_per_pair = (total_amount / total_pairs) if total_pairs > 0 else 0
        
        # Top Distributor Performance
        distributors = User.objects.filter(is_distributor=True)
        
        top_distributors = []
        for distributor in distributors[:5]:  # Top 5
            # Get pairs for this distributor
            distributor_pairs = BinaryPair.objects.filter(user=distributor)
            pairs_count = distributor_pairs.count()
            
            # Get earnings
            distributor_earnings = BinaryEarning.objects.filter(user=distributor)
            distributor_total = float(distributor_earnings.aggregate(total=Sum('amount'))['total'] or 0)
            
            # Calculate TDS (20% of total)
            distributor_tds = distributor_total * 0.20
            
            # Pool money for this distributor (TDS + extra deductions)
            distributor_pool_tds = abs(float(WalletTransaction.objects.filter(
                user=distributor,
                transaction_type='TDS_DEDUCTION',
                description__icontains='binary pair'
            ).aggregate(total=Sum('amount'))['total'] or 0))
            
            distributor_pool_extra = abs(float(WalletTransaction.objects.filter(
                user=distributor,
                transaction_type='EXTRA_DEDUCTION'
            ).aggregate(total=Sum('amount'))['total'] or 0))
            
            distributor_pool = distributor_pool_tds + distributor_pool_extra
            
            # Net amount
            distributor_net = float(distributor_earnings.aggregate(total=Sum('net_amount'))['total'] or 0)
            
            # Paid and pending
            distributor_paid = distributor_pairs.filter(status='processed').count()
            distributor_pending = distributor_pairs.filter(status__in=['pending', 'matched']).count()
            
            top_distributors.append({
                'distributor': distributor.get_full_name() or distributor.username,
                'pairs': pairs_count,
                'total_amount': f"{distributor_total:,.2f}",
                'tds': f"{distributor_tds:,.2f}",
                'pool_money': f"{distributor_pool:,.2f}",
                'net_amount': f"{distributor_net:,.2f}",
                'paid': distributor_paid,
                'pending': distributor_pending
            })
        
        # Sort by total_amount descending
        top_distributors.sort(key=lambda x: float(x['total_amount'].replace(',', '')), reverse=True)
        
        # Commission Breakdown by Status
        status_breakdown = []
        
        # Completed (processed pairs)
        completed_pairs = all_pairs.filter(status='processed')
        completed_count = completed_pairs.count()
        completed_earnings = BinaryEarning.objects.filter(binary_pair__status='processed')
        completed_total = float(completed_earnings.aggregate(total=Sum('amount'))['total'] or 0)
        completed_tds = completed_total * 0.20
        completed_pool = completed_tds  # Simplified
        completed_net = float(completed_earnings.aggregate(total=Sum('net_amount'))['total'] or 0)
        
        status_breakdown.append({
            'status': 'Completed',
            'count': completed_count,
            'total_amount': f"{completed_total:,.2f}",
            'tds': f"{completed_tds:,.2f}",
            'pool_money': f"{completed_pool:,.2f}",
            'net_amount': f"{completed_net:,.2f}"
        })
        
        # Paginate binary earnings
        earnings_queryset = all_earnings.select_related('user', 'binary_pair').order_by('-created_at')
        paginated_data = self._paginate_queryset(
            earnings_queryset,
            pagination_params['page'],
            pagination_params['page_size']
        )
        
        # Format earnings results
        earnings_list = []
        for earning in paginated_data['results']:
            earnings_list.append({
                'id': earning.id,
                'user': {
                    'id': earning.user.id,
                    'name': earning.user.get_full_name() or earning.user.username,
                    'email': earning.user.email or ''
                },
                'binary_pair_id': earning.binary_pair.id,
                'amount': f"{float(earning.amount):,.2f}",
                'pair_number': earning.pair_number,
                'emi_deducted': f"{float(earning.emi_deducted):,.2f}",
                'net_amount': f"{float(earning.net_amount):,.2f}",
                'created_at': earning.created_at.isoformat()
            })
        
        return {
            'summary_cards': {
                'total_commissions': total_commissions,
                'total_pairs': total_pairs,
                'total_amount': f"{total_amount:,.2f}",
                'pool_money': f"{pool_money:,.2f}",
                'net_payout': f"{net_payout:,.2f}",
                'avg_per_pair': f"{avg_per_pair:,.2f}"
            },
            'top_distributor_performance': top_distributors[:5],
            'commission_breakdown_by_status': status_breakdown,
            'detailed_earnings': {
                'pagination': paginated_data['pagination'],
                'results': earnings_list
            }
        }
    
    def _get_login_history(self):
        """Get login history data (placeholder)"""
        return {
            'summary_cards': {
                'total_logins': 0,
                'unique_users': 0,
                'failed_logins': 0,
                'active_sessions': 0,
                'avg_logins_per_user': 0.0
            },
            'device_summary': [],
            'login_status_summary': [],
            'login_location_summary': []
        }
    
    def _get_notification_history(self, pagination_params, status_filter=''):
        """Get notification history data with pagination and filtering"""
        # Get all notifications
        all_notifications = Notification.objects.all()
        
        # Apply status filter for detailed list
        filtered_notifications = self._apply_notification_status_filter(all_notifications, status_filter)
        
        # Summary cards (based on all notifications, not filtered)
        total_sent = all_notifications.count()
        delivered = all_notifications.filter(is_read=True).count()
        opened = delivered  # Assuming read = opened
        clicked = 0  # Placeholder - requires click tracking
        failed = 0  # Placeholder - requires failure tracking
        
        delivery_rate = (delivered / total_sent * 100) if total_sent > 0 else 0
        open_rate = (opened / total_sent * 100) if total_sent > 0 else 0
        click_rate = (clicked / total_sent * 100) if total_sent > 0 else 0
        
        # Delivery Status Summary
        delivery_status = []
        
        delivered_count = delivered
        delivered_pct = delivery_rate
        delivery_status.append({
            'status': 'Delivered',
            'count': delivered_count,
            'percentage': round(delivered_pct, 1)
        })
        
        opened_count = opened
        opened_pct = open_rate
        delivery_status.append({
            'status': 'Opened',
            'count': opened_count,
            'percentage': round(opened_pct, 1)
        })
        
        clicked_count = clicked
        clicked_pct = click_rate
        delivery_status.append({
            'status': 'Clicked',
            'count': clicked_count,
            'percentage': round(clicked_pct, 1)
        })
        
        failed_count = failed
        failed_pct = (failed / total_sent * 100) if total_sent > 0 else 0
        delivery_status.append({
            'status': 'Failed',
            'count': failed_count,
            'percentage': round(failed_pct, 1)
        })
        
        # Notification Type Performance
        type_performance = all_notifications.values('notification_type').annotate(
            sent=Count('id'),
            delivered=Count('id', filter=Q(is_read=True))
        )
        
        type_performance_list = []
        for item in type_performance:
            type_sent = item['sent']
            type_delivered = item['delivered']
            type_opened = type_delivered  # Assuming read = opened
            type_delivery_rate = (type_delivered / type_sent * 100) if type_sent > 0 else 0
            type_open_rate = (type_opened / type_sent * 100) if type_sent > 0 else 0
            
            type_performance_list.append({
                'type': item['notification_type'],
                'sent': type_sent,
                'delivered': type_delivered,
                'opened': type_opened,
                'delivery_rate': round(type_delivery_rate, 1),
                'open_rate': round(type_open_rate, 1)
            })
        
        # Weekly Notification Volume (last 7 days)
        now = timezone.now()
        week_data = {}
        for i in range(7):
            day = now - timedelta(days=6-i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            day_notifications = all_notifications.filter(created_at__gte=day_start, created_at__lte=day_end)
            day_count = day_notifications.count()
            
            day_name = day.strftime('%a')
            week_data[day_name] = day_count
        
        # Paginate notifications
        notifications_queryset = filtered_notifications.select_related('user').order_by('-created_at')
        paginated_data = self._paginate_queryset(
            notifications_queryset,
            pagination_params['page'],
            pagination_params['page_size']
        )
        
        # Format notification results
        notifications_list = []
        for notif in paginated_data['results']:
            notifications_list.append({
                'id': notif.id,
                'notification_type': notif.notification_type,
                'title': notif.title,
                'message': notif.message,
                'is_read': notif.is_read,
                'read_at': notif.read_at.isoformat() if notif.read_at else None,
                'user': {
                    'id': notif.user.id,
                    'name': notif.user.get_full_name() or notif.user.username,
                    'email': notif.user.email or ''
                },
                'created_at': notif.created_at.isoformat()
            })
        
        return {
            'summary_cards': {
                'total_sent': total_sent,
                'delivered': delivered,
                'opened': opened,
                'clicked': clicked,
                'failed': failed,
                'delivery_rate': round(delivery_rate, 1),
                'open_rate': round(open_rate, 1),
                'click_rate': round(click_rate, 1)
            },
            'delivery_status_summary': delivery_status,
            'notification_type_performance': type_performance_list,
            'weekly_notification_volume': week_data,
            'detailed_notifications': {
                'pagination': paginated_data['pagination'],
                'results': notifications_list
            }
        }

