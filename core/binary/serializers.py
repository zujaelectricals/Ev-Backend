from rest_framework import serializers
from django.db.models import Sum
from .models import BinaryNode, BinaryPair, BinaryEarning


class BinaryNodeSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    parent_username = serializers.CharField(source='parent.user.username', read_only=True)
    
    class Meta:
        model = BinaryNode
        fields = '__all__'
        read_only_fields = ('user', 'created_at', 'updated_at')


class BinaryTreeNodeSerializer(serializers.ModelSerializer):
    """
    Recursive serializer for binary tree structure with child nodes
    Includes comprehensive member details for each node
    """
    node_id = serializers.IntegerField(source='id', read_only=True)
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)
    user_full_name = serializers.SerializerMethodField()
    user_mobile = serializers.CharField(source='user.mobile', read_only=True)
    user_first_name = serializers.CharField(source='user.first_name', read_only=True)
    user_last_name = serializers.CharField(source='user.last_name', read_only=True)
    user_city = serializers.CharField(source='user.city', read_only=True)
    user_state = serializers.CharField(source='user.state', read_only=True)
    is_distributor = serializers.BooleanField(source='user.is_distributor', read_only=True)
    is_active_buyer = serializers.BooleanField(source='user.is_active_buyer', read_only=True)
    referral_code = serializers.CharField(source='user.referral_code', read_only=True)
    date_joined = serializers.DateTimeField(source='user.date_joined', read_only=True)
    wallet_balance = serializers.SerializerMethodField()
    total_bookings = serializers.SerializerMethodField()
    total_binary_pairs = serializers.SerializerMethodField()
    total_earnings = serializers.SerializerMethodField()
    total_referrals = serializers.SerializerMethodField()
    total_amount = serializers.SerializerMethodField()
    tds_current = serializers.SerializerMethodField()
    net_amount_total = serializers.SerializerMethodField()
    binary_commission_activated = serializers.BooleanField(read_only=True)
    activation_timestamp = serializers.DateTimeField(read_only=True)
    left_child = serializers.SerializerMethodField()
    right_child = serializers.SerializerMethodField()
    left_side_members = serializers.SerializerMethodField()
    right_side_members = serializers.SerializerMethodField()
    
    class Meta:
        model = BinaryNode
        fields = [
            'node_id', 'user_id', 'user_email', 'user_username', 'user_full_name',
            'user_mobile', 'user_first_name', 'user_last_name', 'user_city', 'user_state',
            'is_distributor', 'is_active_buyer', 'referral_code', 'date_joined',
            'wallet_balance', 'total_bookings', 'total_binary_pairs', 'total_earnings',
            'total_referrals', 'total_amount', 'tds_current', 'net_amount_total',
            'parent', 'side', 'level', 'left_count', 'right_count',
            'binary_commission_activated', 'activation_timestamp', 'left_child', 'right_child', 'left_side_members', 'right_side_members',
            'created_at', 'updated_at'
        ]
        read_only_fields = ('user', 'created_at', 'updated_at')
    
    def __init__(self, *args, **kwargs):
        self.max_depth = kwargs.pop('max_depth', 5)
        self.current_depth = kwargs.pop('current_depth', 0)
        super().__init__(*args, **kwargs)
    
    def get_user_full_name(self, obj):
        """Get user's full name"""
        if obj.user:
            return obj.user.get_full_name() or obj.user.username
        return None
    
    def get_wallet_balance(self, obj):
        """Get user's wallet balance excluding referral bonuses and TDS/extra deductions (these are deducted from booking, not wallet)"""
        if obj.user and hasattr(obj.user, 'wallet'):
            from core.wallet.models import WalletTransaction
            from decimal import Decimal
            
            # Calculate balance excluding:
            # - REFERRAL_BONUS (removed feature)
            # - TDS_DEDUCTION (deducted from booking balance, not wallet)
            # - EXTRA_DEDUCTION (deducted from booking balance, not wallet)
            balance = WalletTransaction.objects.filter(
                user=obj.user
            ).exclude(
                transaction_type__in=['REFERRAL_BONUS', 'TDS_DEDUCTION', 'EXTRA_DEDUCTION']
            ).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            
            return str(balance)
        return "0.00"
    
    def get_total_bookings(self, obj):
        """Get total number of bookings for user"""
        if obj.user:
            from core.booking.models import Booking
            return Booking.objects.filter(user=obj.user).count()
        return 0
    
    def get_total_binary_pairs(self, obj):
        """Get total number of binary pairs for user"""
        if obj.user:
            from .models import BinaryPair
            return BinaryPair.objects.filter(user=obj.user).count()
        return 0
    
    def get_total_earnings(self, obj):
        """Get total earnings (binary-related: direct user commissions and binary pairs)"""
        # Use net_amount_total as total_earnings to match our calculation
        return self.get_net_amount_total(obj)
    
    def get_total_referrals(self, obj):
        """Get total number of referrals (users who used this user's referral code)"""
        if obj.user:
            # Count users who have referred_by = this user
            # Also count users who have bookings with this user as referrer
            from core.users.models import User
            from core.booking.models import Booking
            
            # Direct referrals via referred_by field
            direct_referrals = User.objects.filter(referred_by=obj.user).count()
            
            # Users who used referral code in bookings (may not have referred_by set)
            booking_referrals = Booking.objects.filter(
                referred_by=obj.user
            ).values('user').distinct().count()
            
            # Get unique count (some users might be in both)
            all_referred_user_ids = set(
                list(User.objects.filter(referred_by=obj.user).values_list('id', flat=True)) +
                list(Booking.objects.filter(referred_by=obj.user).values_list('user_id', flat=True).distinct())
            )
            
            return len(all_referred_user_ids)
        return 0
    
    def get_total_amount(self, obj):
        """Get total amount (gross) from all binary earnings and direct user commissions"""
        if obj.user:
            from core.wallet.models import WalletTransaction
            from decimal import Decimal
            
            # Sum binary pair earnings (gross amount)
            binary_total = BinaryEarning.objects.filter(user=obj.user).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            
            # Sum direct user commissions (net amounts)
            direct_commissions_net = WalletTransaction.objects.filter(
                user=obj.user,
                transaction_type='DIRECT_USER_COMMISSION'
            ).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            
            # Sum TDS deducted for direct user commissions only
            # Filter by description to exclude binary pair commission TDS
            # TDS_DEDUCTION amounts are negative, so we get absolute value
            tds_for_direct_commissions = WalletTransaction.objects.filter(
                user=obj.user,
                transaction_type='TDS_DEDUCTION',
                description__icontains='on user commission'  # Distinguishes from binary pair TDS
            ).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            
            # Calculate gross: net + TDS (TDS is negative, so we subtract it)
            direct_commissions_gross = direct_commissions_net - tds_for_direct_commissions
            
            total = binary_total + direct_commissions_gross
            return str(total)
        return "0.00"
    
    def get_tds_current(self, obj):
        """Get total TDS deducted from wallet transactions (for both binary pairs and direct user commissions)"""
        if obj.user:
            from core.wallet.models import WalletTransaction
            # TDS_DEDUCTION transactions have negative amounts, so we sum absolute values
            tds_total = WalletTransaction.objects.filter(
                user=obj.user,
                transaction_type='TDS_DEDUCTION'
            ).aggregate(
                total=Sum('amount')
            )['total']
            # Since TDS amounts are stored as negative, we need to get absolute value
            if tds_total:
                return str(abs(tds_total))
            return "0.00"
        return "0.00"
    
    def get_net_amount_total(self, obj):
        """Get total net amount from all binary earnings and direct user commissions"""
        if obj.user:
            from core.wallet.models import WalletTransaction
            from decimal import Decimal
            
            # Sum binary pair net amounts
            binary_net = BinaryEarning.objects.filter(user=obj.user).aggregate(
                total=Sum('net_amount')
            )['total'] or Decimal('0')
            
            # Sum direct user commissions (these are already net amounts after TDS)
            direct_commissions_net = WalletTransaction.objects.filter(
                user=obj.user,
                transaction_type='DIRECT_USER_COMMISSION'
            ).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            
            total = binary_net + direct_commissions_net
            return str(total)
        return "0.00"
    
    def get_left_child(self, obj):
        """Get left child node recursively"""
        if self.current_depth >= self.max_depth:
            return None
        
        try:
            # Optimize query with select_related
            # Use .first() instead of .get() to handle cases where multiple nodes exist (data integrity issue)
            left_child = BinaryNode.objects.select_related(
                'user', 'user__wallet', 'parent', 'parent__user'
            ).filter(parent=obj, side='left').first()
            
            if not left_child:
                return None
            
            serializer = BinaryTreeNodeSerializer(
                left_child,
                max_depth=self.max_depth,
                current_depth=self.current_depth + 1
            )
            return serializer.data
        except Exception as e:
            # Log error but don't fail the entire response
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting left child for node {obj.id}: {str(e)}")
            return None
    
    def get_right_child(self, obj):
        """Get right child node recursively"""
        if self.current_depth >= self.max_depth:
            return None
        
        try:
            # Optimize query with select_related
            # Use .first() instead of .get() to handle cases where multiple nodes exist (data integrity issue)
            right_child = BinaryNode.objects.select_related(
                'user', 'user__wallet', 'parent', 'parent__user'
            ).filter(parent=obj, side='right').first()
            
            if not right_child:
                return None
            
            serializer = BinaryTreeNodeSerializer(
                right_child,
                max_depth=self.max_depth,
                current_depth=self.current_depth + 1
            )
            return serializer.data
        except Exception as e:
            # Log error but don't fail the entire response
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting right child for node {obj.id}: {str(e)}")
            return None
    
    def _get_all_descendants(self, node, side, max_depth, current_depth=0, exclude_direct_children=False):
        """
        Get all descendant nodes on a specific side
        exclude_direct_children: If True, excludes direct children (already in left_child/right_child)
        """
        if current_depth >= max_depth:
            return []
        
        descendants = []
        # Get direct children on the specified side
        children = BinaryNode.objects.select_related(
            'user', 'user__wallet', 'parent', 'parent__user'
        ).filter(parent=node, side=side)
        
        for child in children:
            # Only add direct children if not excluding them
            if not exclude_direct_children or current_depth > 0:
                # Create a simplified serializer for list view (without nested children to avoid duplication)
                child_data = {
                    'node_id': child.id,
                    'user_id': child.user.id,
                    'user_email': child.user.email,
                    'user_username': child.user.username,
                    'user_full_name': child.user.get_full_name() or child.user.username,
                    'user_mobile': child.user.mobile,
                    'user_first_name': child.user.first_name,
                    'user_last_name': child.user.last_name,
                    'user_city': child.user.city,
                    'user_state': child.user.state,
                    'is_distributor': child.user.is_distributor,
                    'is_active_buyer': child.user.is_active_buyer,
                    'referral_code': child.user.referral_code,
                    'date_joined': child.user.date_joined,
                    'wallet_balance': self._get_wallet_balance(child.user),
                    'total_bookings': self._get_total_bookings(child.user),
                    'total_binary_pairs': self._get_total_binary_pairs(child.user),
                    'total_earnings': self._get_net_amount_total(child.user),
                    'total_referrals': self._get_total_referrals(child.user),
                    'total_amount': self._get_total_amount(child.user),
                    'tds_current': self._get_tds_current(child.user),
                    'net_amount_total': self._get_net_amount_total(child.user),
                    'parent': child.parent.id if child.parent else None,
                    'side': child.side,
                    'level': child.level,
                    'left_count': child.left_count,
                    'right_count': child.right_count,
                    'created_at': child.created_at,
                    'updated_at': child.updated_at
                }
                descendants.append(child_data)
            
            # Recursively get descendants of this child (always include grandchildren and below)
            descendants.extend(self._get_all_descendants(child, 'left', max_depth, current_depth + 1, exclude_direct_children=False))
            descendants.extend(self._get_all_descendants(child, 'right', max_depth, current_depth + 1, exclude_direct_children=False))
        
        return descendants
    
    def _get_total_bookings(self, user):
        """Helper method to get total bookings count"""
        if user:
            from core.booking.models import Booking
            return Booking.objects.filter(user=user).count()
        return 0
    
    def _get_total_binary_pairs(self, user):
        """Helper method to get total binary pairs count"""
        if user:
            from .models import BinaryPair
            return BinaryPair.objects.filter(user=user).count()
        return 0
    
    def _get_total_referrals(self, user):
        """Helper method to get total referrals count"""
        if user:
            from core.users.models import User
            from core.booking.models import Booking
            
            # Get unique count of all users who used this referral code
            all_referred_user_ids = set(
                list(User.objects.filter(referred_by=user).values_list('id', flat=True)) +
                list(Booking.objects.filter(referred_by=user).values_list('user_id', flat=True).distinct())
            )
            
            return len(all_referred_user_ids)
        return 0
    
    def _get_total_amount(self, user):
        """Helper method to get total amount (gross) from all binary earnings and direct user commissions"""
        if user:
            from core.wallet.models import WalletTransaction
            from decimal import Decimal
            
            # Sum binary pair earnings (gross amount)
            binary_total = BinaryEarning.objects.filter(user=user).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            
            # Sum direct user commissions (net amounts)
            direct_commissions_net = WalletTransaction.objects.filter(
                user=user,
                transaction_type='DIRECT_USER_COMMISSION'
            ).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            
            # Sum TDS deducted for direct user commissions only
            tds_for_direct_commissions = WalletTransaction.objects.filter(
                user=user,
                transaction_type='TDS_DEDUCTION',
                description__icontains='on user commission'
            ).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            
            # Calculate gross: net + TDS (TDS is negative, so we subtract it)
            direct_commissions_gross = direct_commissions_net - tds_for_direct_commissions
            
            total = binary_total + direct_commissions_gross
            return str(total)
        return "0.00"
    
    def _get_tds_current(self, user):
        """Helper method to get total TDS deducted"""
        if user:
            from core.wallet.models import WalletTransaction
            tds_total = WalletTransaction.objects.filter(
                user=user,
                transaction_type='TDS_DEDUCTION'
            ).aggregate(
                total=Sum('amount')
            )['total']
            if tds_total:
                return str(abs(tds_total))
            return "0.00"
        return "0.00"
    
    def _get_wallet_balance(self, user):
        """Helper method to get wallet balance excluding referral bonuses and TDS/extra deductions"""
        if user and hasattr(user, 'wallet'):
            from core.wallet.models import WalletTransaction
            from decimal import Decimal
            
            # Calculate balance excluding:
            # - REFERRAL_BONUS (removed feature)
            # - TDS_DEDUCTION (deducted from booking balance, not wallet)
            # - EXTRA_DEDUCTION (deducted from booking balance, not wallet)
            balance = WalletTransaction.objects.filter(
                user=user
            ).exclude(
                transaction_type__in=['REFERRAL_BONUS', 'TDS_DEDUCTION', 'EXTRA_DEDUCTION']
            ).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            
            return str(balance)
        return "0.00"
    
    def _get_net_amount_total(self, user):
        """
        Helper method to get total net amount from all binary earnings and direct user commissions
        IMPORTANT: Only counts pairs that have been successfully processed (credited to wallet)
        This ensures total_earnings matches wallet_balance by only counting amounts that were
        actually credited to the wallet via WalletTransaction records.
        """
        if user:
            from core.wallet.models import WalletTransaction
            from decimal import Decimal
            
            # Sum binary pair commissions from wallet transactions (only successfully processed pairs)
            # This ensures we only count pairs that were actually credited to wallet
            binary_net = WalletTransaction.objects.filter(
                user=user,
                transaction_type='BINARY_PAIR_COMMISSION'
            ).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            
            # Sum direct user commissions (these are already net amounts after TDS)
            direct_commissions_net = WalletTransaction.objects.filter(
                user=user,
                transaction_type='DIRECT_USER_COMMISSION'
            ).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            
            total = binary_net + direct_commissions_net
            return str(total)
        return "0.00"
    
    def get_left_side_members(self, obj):
        """
        Get all members on the left side with their details
        Excludes direct left child (already in left_child) to avoid duplication
        """
        return self._get_all_descendants(obj, 'left', self.max_depth, 0, exclude_direct_children=True)
    
    def get_right_side_members(self, obj):
        """
        Get all members on the right side with their details
        Excludes direct right child (already in right_child) to avoid duplication
        """
        return self._get_all_descendants(obj, 'right', self.max_depth, 0, exclude_direct_children=True)


class BinaryPairSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    left_user_email = serializers.CharField(source='left_user.email', read_only=True)
    right_user_email = serializers.CharField(source='right_user.email', read_only=True)
    
    class Meta:
        model = BinaryPair
        fields = '__all__'
        read_only_fields = ('user', 'status', 'created_at', 'matched_at', 'processed_at', 
                          'pair_month', 'pair_year')


class BinaryEarningSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    pair_id = serializers.IntegerField(source='binary_pair.id', read_only=True)
    
    class Meta:
        model = BinaryEarning
        fields = '__all__'
        read_only_fields = ('user', 'created_at')

