from rest_framework import views
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.exceptions import PermissionDenied
from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta, datetime
from decimal import Decimal
from core.users.models import User
from core.booking.models import Booking, Payment
from core.wallet.models import Wallet, WalletTransaction
from core.binary.models import BinaryPair, BinaryNode, BinaryEarning
from core.binary.utils import get_all_descendant_nodes
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
        
        # Count bookings by month
        bookings = Booking.objects.filter(
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
            
            # Count total users up to end of this month
            total_buyers = User.objects.filter(date_joined__lte=month_end).count()
            
            # Count active buyers up to end of this month
            # Note: This assumes is_active_buyer status is current, not historical
            # For accurate historical data, you'd need to track status changes over time
            active_buyers = User.objects.filter(
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
    
    def _get_buyer_segments(self):
        """Get buyer category distribution"""
        now = timezone.now()
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        active_buyers = User.objects.filter(is_active_buyer=True).count()
        inactive = User.objects.filter(is_active_buyer=False, role='user').count()
        pre_booked = User.objects.filter(bookings__status='pending').distinct().count()
        new_this_month = User.objects.filter(
            date_joined__gte=current_month_start
        ).count()
        
        return {
            'active_buyers': active_buyers,
            'inactive': inactive,
            'pre_booked': pre_booked,
            'new_this_month': new_this_month
        }
    
    def _get_sales_funnel(self):
        """Get sales funnel visualization data"""
        total_visitors = User.objects.count()
        interested = User.objects.filter(bookings__status='pending').distinct().count()
        pre_booked = interested  # Same as interested based on our definition
        paid = User.objects.filter(bookings__payments__status='completed').distinct().count()
        delivered = User.objects.filter(bookings__status='completed').distinct().count()
        
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
    
    def _get_conversion_rates(self):
        """Get stage-to-stage conversion rates with trend indicators"""
        now = timezone.now()
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Current period data
        total_visitors = User.objects.count()
        interested = User.objects.filter(bookings__status='pending').distinct().count()
        pre_booked = interested
        paid = User.objects.filter(bookings__payments__status='completed').distinct().count()
        delivered = User.objects.filter(bookings__status='completed').distinct().count()
        
        # Previous period data (previous month)
        if now.month == 1:
            prev_month_start = now.replace(year=now.year-1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            prev_month_start = now.replace(month=now.month-1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        prev_month_end = current_month_start - timedelta(days=1)
        
        prev_visitors = User.objects.filter(date_joined__lt=current_month_start).count()
        prev_interested = User.objects.filter(
            bookings__created_at__lt=current_month_start,
            bookings__status='pending'
        ).distinct().count()
        prev_pre_booked = prev_interested
        prev_paid = User.objects.filter(
            bookings__payments__completed_at__lt=current_month_start,
            bookings__payments__status='completed'
        ).distinct().count()
        prev_delivered = User.objects.filter(
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
    
    def _calculate_percentage_change(self, current, previous):
        """Calculate percentage change between two values"""
        if previous == 0:
            return 0 if current == 0 else 100.0
        return round(((current - previous) / previous) * 100, 1)
    
    def _get_pre_bookings(self):
        """Calculate pre-bookings KPIs and summary data"""
        # Total Pre-Bookings: All bookings with status in ['pending', 'active', 'expired']
        pre_booking_statuses = ['pending', 'active', 'expired']
        total_pre_bookings = Booking.objects.filter(status__in=pre_booking_statuses).count()
        
        # Pending: Bookings with status='pending'
        pending_count = Booking.objects.filter(status='pending').count()
        
        # Confirmed: Bookings with status='active' (confirmed/active buyers)
        confirmed_count = Booking.objects.filter(status='active').count()
        
        # Expired: Bookings with status='expired'
        expired_count = Booking.objects.filter(status='expired').count()
        
        # Total Amount: Sum of booking_amount for all pre-bookings
        total_amount_result = Booking.objects.filter(
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
    
    def _get_emi_orders(self):
        """Calculate EMI orders KPIs, collection trend, and summary data"""
        now = timezone.now()
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Total EMI Orders: Bookings with payment_option='emi_options'
        total_emi_orders = Booking.objects.filter(payment_option='emi_options').count()
        
        # Active EMIs: EMI orders that are not completed/cancelled
        active_emis = Booking.objects.filter(
            payment_option='emi_options',
            status__in=['pending', 'active']
        ).count()
        
        # Monthly Collection: Sum of EMI payments collected in current month
        monthly_collection_result = Payment.objects.filter(
            booking__payment_option='emi_options',
            status='completed',
            completed_at__gte=current_month_start
        ).aggregate(total=Sum('amount'))
        monthly_collection = float(monthly_collection_result['total'] or 0)
        
        # Pending Amount: Total remaining_amount across all active EMI orders
        pending_amount_result = Booking.objects.filter(
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
            payment_option='emi_options',
            status='completed'
        ).count()
        
        cancelled_count = Booking.objects.filter(
            payment_option='emi_options',
            status='cancelled'
        ).count()
        
        total_collected_result = Payment.objects.filter(
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
    
    def _get_cancelled_orders(self):
        """Calculate cancelled orders KPIs, cancellation trend, and summary with refund status"""
        # Total Cancelled: Bookings with status='cancelled'
        total_cancelled = Booking.objects.filter(status='cancelled').count()
        
        # Total Amount: Sum of total_amount for cancelled bookings
        total_amount_result = Booking.objects.filter(
            status='cancelled'
        ).aggregate(total=Sum('total_amount'))
        total_amount = float(total_amount_result['total'] or 0)
        
        # Refund Pending: Cancelled bookings with payments that haven't been refunded
        # Get all cancelled bookings with payments
        cancelled_bookings = Booking.objects.filter(
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
        total_bookings = Booking.objects.count()
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

