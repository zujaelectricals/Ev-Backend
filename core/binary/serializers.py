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
    parent_name = serializers.SerializerMethodField()
    left_child = serializers.SerializerMethodField()
    right_child = serializers.SerializerMethodField()
    left_side_members = serializers.SerializerMethodField()
    right_side_members = serializers.SerializerMethodField()
    user_profile_picture_url = serializers.SerializerMethodField()
    counts_for_activation = serializers.SerializerMethodField()
    eligible_for_pairing = serializers.SerializerMethodField()
    
    class Meta:
        model = BinaryNode
        fields = [
            'node_id', 'user_id', 'user_email', 'user_username', 'user_full_name',
            'user_mobile', 'user_first_name', 'user_last_name', 'user_city', 'user_state',
            'is_distributor', 'is_active_buyer', 'referral_code', 'date_joined',
            'wallet_balance', 'total_bookings', 'total_binary_pairs', 'total_earnings',
            'total_referrals', 'total_amount', 'tds_current', 'net_amount_total',
            'parent', 'parent_name', 'side', 'level', 'left_count', 'right_count',
            'binary_commission_activated', 'activation_timestamp', 'left_child', 'right_child', 'left_side_members', 'right_side_members',
            'user_profile_picture_url', 'counts_for_activation', 'eligible_for_pairing', 'created_at', 'updated_at'
        ]
        read_only_fields = ('user', 'created_at', 'updated_at')
    
    def __init__(self, *args, **kwargs):
        self.max_depth = kwargs.pop('max_depth', 5)
        self.current_depth = kwargs.pop('current_depth', 0)
        self.min_depth = kwargs.pop('min_depth', 0)
        self.side_filter = kwargs.pop('side_filter', 'both')  # 'left', 'right', or 'both'
        self.page = kwargs.pop('page', None)
        self.page_size = kwargs.pop('page_size', None)
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        # Ensure request is in context for nested serializers
        if self.request and 'request' not in self.context:
            self.context['request'] = self.request
    
    def to_representation(self, instance):
        """
        Override to exclude null fields from the response
        Removes null values for: left_child, right_child, left_side_members, right_side_members, user_profile_picture_url
        """
        data = super().to_representation(instance)
        
        # Remove null fields to keep response clean
        null_fields_to_remove = ['left_child', 'right_child', 'left_side_members', 'right_side_members', 'user_profile_picture_url']
        for field in null_fields_to_remove:
            if field in data and data[field] is None:
                del data[field]
        
        return data
    
    def get_user_full_name(self, obj):
        """Get user's full name"""
        if obj.user:
            return obj.user.get_full_name() or obj.user.username
        return None
    
    def get_user_profile_picture_url(self, obj):
        """Get absolute URL for user profile picture"""
        if obj.user and obj.user.profile_picture:
            request = self.request or self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.user.profile_picture.url)
            return obj.user.profile_picture.url
        return None
    
    def get_counts_for_activation(self, obj):
        """
        Indicates if this user counts toward binary activation calculation
        Only users with activation payment count toward activation
        """
        if not obj.user:
            return False
        from core.binary.utils import has_activation_payment
        return has_activation_payment(obj.user)
    
    def get_eligible_for_pairing(self, obj):
        """
        Indicates if this user is eligible for binary pair matching
        User must have activation payment AND ancestor must have binary commission activated
        """
        if not obj.user:
            return False
        
        # Check if user has activation payment
        from core.binary.utils import has_activation_payment
        if not has_activation_payment(obj.user):
            return False
        
        # Check if any ancestor has binary commission activated
        # Traverse up the tree to find root or activated ancestor
        current = obj.parent
        while current:
            if current.binary_commission_activated:
                return True
            current = current.parent
        
        return False
    
    def get_parent_name(self, obj):
        """Get parent's full name"""
        if obj.parent and obj.parent.user:
            return obj.parent.user.get_full_name() or obj.parent.user.username
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
            # Use the helper method which includes BINARY_INITIAL_BONUS
            return self._get_net_amount_total(obj.user)
        return "0.00"
    
    def get_left_child(self, obj):
        """Get left child node recursively"""
        # Skip if filtering for right side only
        if self.side_filter == 'right':
            return None
        
        if self.current_depth >= self.max_depth or self.current_depth < self.min_depth:
            return None
        
        try:
            # Optimize query with select_related
            # Use .first() instead of .get() to handle cases where multiple nodes exist (data integrity issue)
            left_child = BinaryNode.objects.select_related(
                'user', 'user__wallet', 'parent', 'parent__user'
            ).filter(parent=obj, side='left').first()
            
            if not left_child:
                return None
            
            # When pagination is enabled, limit recursion to only show direct child (no nested children)
            # Nested children will be accessible through paginated left_side_members and right_side_members
            effective_max_depth = self.max_depth
            if self.page is not None and self.page_size is not None:
                # Only show direct child, stop recursion here
                effective_max_depth = self.current_depth + 1
            
            serializer = BinaryTreeNodeSerializer(
                left_child,
                max_depth=effective_max_depth,
                min_depth=self.min_depth,
                current_depth=self.current_depth + 1,
                side_filter=self.side_filter,
                page=self.page,
                page_size=self.page_size,
                request=self.request
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
        # Skip if filtering for left side only
        if self.side_filter == 'left':
            return None
        
        if self.current_depth >= self.max_depth or self.current_depth < self.min_depth:
            return None
        
        try:
            # Optimize query with select_related
            # Use .first() instead of .get() to handle cases where multiple nodes exist (data integrity issue)
            right_child = BinaryNode.objects.select_related(
                'user', 'user__wallet', 'parent', 'parent__user'
            ).filter(parent=obj, side='right').first()
            
            if not right_child:
                return None
            
            # When pagination is enabled, limit recursion to only show direct child (no nested children)
            # Nested children will be accessible through paginated left_side_members and right_side_members
            effective_max_depth = self.max_depth
            if self.page is not None and self.page_size is not None:
                # Only show direct child, stop recursion here
                effective_max_depth = self.current_depth + 1
            
            serializer = BinaryTreeNodeSerializer(
                right_child,
                max_depth=effective_max_depth,
                min_depth=self.min_depth,
                current_depth=self.current_depth + 1,
                side_filter=self.side_filter,
                page=self.page,
                page_size=self.page_size,
                request=self.request
            )
            return serializer.data
        except Exception as e:
            # Log error but don't fail the entire response
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting right child for node {obj.id}: {str(e)}")
            return None
    
    def _get_all_descendants(self, node, side, max_depth, current_depth=0, exclude_direct_children=False, min_depth=0):
        """
        Get all descendant nodes on a specific side
        exclude_direct_children: If True, excludes direct children (already in left_child/right_child)
        min_depth: Minimum depth to include in results
        """
        if current_depth >= max_depth:
            return []
        
        # First, collect all nodes and their users (without expensive queries)
        nodes_to_process = []
        children = BinaryNode.objects.select_related(
            'user', 'user__wallet', 'parent', 'parent__user'
        ).filter(parent=node, side=side)
        
        for child in children:
            # Only add direct children if not excluding them and depth is within range
            if (not exclude_direct_children or current_depth > 0) and current_depth >= min_depth:
                nodes_to_process.append(child)
            
            # Recursively get descendants of this child (always include grandchildren and below)
            nodes_to_process.extend(self._get_all_descendants_nodes(child, 'left', max_depth, current_depth + 1, exclude_direct_children=False, min_depth=min_depth))
            nodes_to_process.extend(self._get_all_descendants_nodes(child, 'right', max_depth, current_depth + 1, exclude_direct_children=False, min_depth=min_depth))
        
        # If no nodes to process, return empty
        if not nodes_to_process:
            return []
        
        # Batch query all data for all users at once
        user_ids = [node.user.id for node in nodes_to_process if node.user]
        batch_data = self._batch_query_user_data(user_ids, [node.id for node in nodes_to_process])
        
        # Build response using batch data
        descendants = []
        for child in nodes_to_process:
            if not child.user:
                continue
                
            user_id = child.user.id
            node_id = child.id
            
            child_data = {
                'node_id': node_id,
                'user_id': user_id,
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
                'wallet_balance': batch_data['wallet_balances'].get(user_id, "0.00"),
                'total_bookings': batch_data['bookings_count'].get(user_id, 0),
                'total_binary_pairs': batch_data['binary_pairs_count'].get(user_id, 0),
                'total_earnings': batch_data['net_amount_total'].get(user_id, "0.00"),
                'total_referrals': batch_data['referrals_count'].get(user_id, 0),
                'total_amount': batch_data['total_amount'].get(user_id, "0.00"),
                'tds_current': batch_data['tds_current'].get(user_id, "0.00"),
                'net_amount_total': batch_data['net_amount_total'].get(user_id, "0.00"),
                'parent': child.parent.id if child.parent else None,
                'parent_name': child.parent.user.get_full_name() or child.parent.user.username if child.parent and child.parent.user else None,
                'side': child.side,
                'level': child.level,
                'left_count': child.left_count,
                'right_count': child.right_count,
                'counts_for_activation': batch_data['counts_for_activation'].get(node_id, False),
                'eligible_for_pairing': batch_data['eligible_for_pairing'].get(node_id, False),
                'created_at': child.created_at,
                'updated_at': child.updated_at
            }
            descendants.append(child_data)
        
        return descendants
    
    def _get_all_descendants_nodes(self, node, side, max_depth, current_depth=0, exclude_direct_children=False, min_depth=0):
        """
        Helper method to collect all descendant nodes (without expensive queries)
        Returns list of BinaryNode objects
        """
        if current_depth >= max_depth:
            return []
        
        nodes = []
        children = BinaryNode.objects.select_related(
            'user', 'user__wallet', 'parent', 'parent__user'
        ).filter(parent=node, side=side)
        
        for child in children:
            if (not exclude_direct_children or current_depth > 0) and current_depth >= min_depth:
                nodes.append(child)
            
            nodes.extend(self._get_all_descendants_nodes(child, 'left', max_depth, current_depth + 1, exclude_direct_children=False, min_depth=min_depth))
            nodes.extend(self._get_all_descendants_nodes(child, 'right', max_depth, current_depth + 1, exclude_direct_children=False, min_depth=min_depth))
        
        return nodes
    
    def _batch_query_user_data(self, user_ids, node_ids):
        """
        Batch query all user-related data in a few queries instead of N queries
        Returns a dictionary with all the data keyed by user_id or node_id
        """
        from django.db.models import Sum, Count, Q
        from decimal import Decimal
        
        if not user_ids:
            return {
                'wallet_balances': {},
                'bookings_count': {},
                'binary_pairs_count': {},
                'net_amount_total': {},
                'referrals_count': {},
                'total_amount': {},
                'tds_current': {},
                'counts_for_activation': {},
                'eligible_for_pairing': {}
            }
        
        # Batch query wallet balances (excluding certain transaction types)
        from core.wallet.models import WalletTransaction
        wallet_data = WalletTransaction.objects.filter(
            user_id__in=user_ids
        ).exclude(
            transaction_type__in=['REFERRAL_BONUS', 'TDS_DEDUCTION', 'EXTRA_DEDUCTION']
        ).values('user_id').annotate(total=Sum('amount'))
        wallet_balances = {item['user_id']: str(item['total'] or Decimal('0')) for item in wallet_data}
        
        # Batch query bookings count
        from core.booking.models import Booking
        bookings_data = Booking.objects.filter(user_id__in=user_ids).values('user_id').annotate(count=Count('id'))
        bookings_count = {item['user_id']: item['count'] for item in bookings_data}
        
        # Batch query binary pairs count
        from .models import BinaryPair
        binary_pairs_data = BinaryPair.objects.filter(user_id__in=user_ids).values('user_id').annotate(count=Count('id'))
        binary_pairs_count = {item['user_id']: item['count'] for item in binary_pairs_data}
        
        # Batch query binary pair commissions (net)
        binary_commissions = WalletTransaction.objects.filter(
            user_id__in=user_ids,
            transaction_type='BINARY_PAIR_COMMISSION'
        ).values('user_id').annotate(total=Sum('amount'))
        binary_commissions_dict = {item['user_id']: item['total'] or Decimal('0') for item in binary_commissions}
        
        # Batch query direct user commissions (net)
        direct_commissions = WalletTransaction.objects.filter(
            user_id__in=user_ids,
            transaction_type='DIRECT_USER_COMMISSION'
        ).values('user_id').annotate(total=Sum('amount'))
        direct_commissions_dict = {item['user_id']: item['total'] or Decimal('0') for item in direct_commissions}
        
        # Batch query binary initial bonus
        initial_bonus = WalletTransaction.objects.filter(
            user_id__in=user_ids,
            transaction_type='BINARY_INITIAL_BONUS'
        ).values('user_id').annotate(total=Sum('amount'))
        initial_bonus_dict = {item['user_id']: item['total'] or Decimal('0') for item in initial_bonus}
        
        # Calculate net_amount_total for each user
        net_amount_total = {}
        for user_id in user_ids:
            total = (binary_commissions_dict.get(user_id, Decimal('0')) + 
                    direct_commissions_dict.get(user_id, Decimal('0')) + 
                    initial_bonus_dict.get(user_id, Decimal('0')))
            net_amount_total[user_id] = str(total)
        
        # Batch query referrals count
        from core.users.models import User
        # Get all users referred by our users
        direct_referrals_users = User.objects.filter(referred_by_id__in=user_ids).values_list('referred_by_id', 'id')
        direct_referrals_dict = {}
        for referrer_id, referred_id in direct_referrals_users:
            if referrer_id not in direct_referrals_dict:
                direct_referrals_dict[referrer_id] = set()
            direct_referrals_dict[referrer_id].add(referred_id)
        
        # Get all bookings with our users as referrers
        booking_referrals_users = Booking.objects.filter(referred_by_id__in=user_ids).values_list('referred_by_id', 'user_id').distinct()
        for referrer_id, user_id in booking_referrals_users:
            if referrer_id not in direct_referrals_dict:
                direct_referrals_dict[referrer_id] = set()
            direct_referrals_dict[referrer_id].add(user_id)
        
        referrals_count = {user_id: len(direct_referrals_dict.get(user_id, set())) for user_id in user_ids}
        
        # Batch query total amount (gross)
        from .models import BinaryEarning
        binary_earnings = BinaryEarning.objects.filter(user_id__in=user_ids).values('user_id').annotate(total=Sum('amount'))
        binary_earnings_dict = {item['user_id']: item['total'] or Decimal('0') for item in binary_earnings}
        
        tds_for_direct = WalletTransaction.objects.filter(
            user_id__in=user_ids,
            transaction_type='TDS_DEDUCTION',
            description__icontains='on user commission'
        ).values('user_id').annotate(total=Sum('amount'))
        tds_for_direct_dict = {item['user_id']: item['total'] or Decimal('0') for item in tds_for_direct}
        
        total_amount = {}
        for user_id in user_ids:
            direct_gross = direct_commissions_dict.get(user_id, Decimal('0')) - tds_for_direct_dict.get(user_id, Decimal('0'))
            total_amount[user_id] = str(binary_earnings_dict.get(user_id, Decimal('0')) + direct_gross)
        
        # Batch query TDS current
        tds_data = WalletTransaction.objects.filter(
            user_id__in=user_ids,
            transaction_type='TDS_DEDUCTION'
        ).values('user_id').annotate(total=Sum('amount'))
        tds_current = {item['user_id']: str(abs(item['total'] or Decimal('0'))) for item in tds_data}
        
        # Batch query counts_for_activation (check if user has activation payment)
        from core.booking.models import Payment
        activation_payments = Payment.objects.filter(
            user_id__in=user_ids,
            status='completed'
        ).values('user_id').annotate(count=Count('id'))
        has_activation = {item['user_id']: item['count'] > 0 for item in activation_payments}
        
        # For counts_for_activation and eligible_for_pairing, we need node data
        # Get nodes with their users to check activation
        nodes = BinaryNode.objects.filter(id__in=node_ids).select_related('user', 'parent')
        counts_for_activation = {}
        eligible_for_pairing = {}
        
        for node in nodes:
            user_id = node.user.id if node.user else None
            if user_id:
                counts_for_activation[node.id] = has_activation.get(user_id, False)
                
                # Check eligible_for_pairing (user has activation AND ancestor has binary_commission_activated)
                if has_activation.get(user_id, False):
                    # Check if any ancestor has binary_commission_activated
                    current = node.parent
                    has_activated_ancestor = False
                    while current:
                        if current.binary_commission_activated:
                            has_activated_ancestor = True
                            break
                        current = current.parent
                    eligible_for_pairing[node.id] = has_activated_ancestor
                else:
                    eligible_for_pairing[node.id] = False
            else:
                counts_for_activation[node.id] = False
                eligible_for_pairing[node.id] = False
        
        return {
            'wallet_balances': wallet_balances,
            'bookings_count': bookings_count,
            'binary_pairs_count': binary_pairs_count,
            'net_amount_total': net_amount_total,
            'referrals_count': referrals_count,
            'total_amount': total_amount,
            'tds_current': tds_current,
            'counts_for_activation': counts_for_activation,
            'eligible_for_pairing': eligible_for_pairing
        }
    
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
            
            # Sum binary initial bonus (net amount after TDS, but TDS not deducted from booking balance)
            initial_bonus_net = WalletTransaction.objects.filter(
                user=user,
                transaction_type='BINARY_INITIAL_BONUS'
            ).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0')
            
            total = binary_net + direct_commissions_net + initial_bonus_net
            return str(total)
        return "0.00"
    
    def _get_counts_for_activation(self, node):
        """Helper method to check if user counts toward binary activation"""
        if not node or not node.user:
            return False
        from core.binary.utils import has_activation_payment
        return has_activation_payment(node.user)
    
    def _get_eligible_for_pairing(self, node):
        """Helper method to check if user is eligible for binary pair matching"""
        if not node or not node.user:
            return False
        
        # Check if user has activation payment
        from core.binary.utils import has_activation_payment
        if not has_activation_payment(node.user):
            return False
        
        # Check if any ancestor has binary commission activated
        current = node.parent
        while current:
            if current.binary_commission_activated:
                return True
            current = current.parent
        
        return False
    
    def _paginate_side_members(self, members, side_name, node=None):
        """
        Paginate side members array and return paginated response structure
        Applies pagination at all levels to reduce JSON payload size
        
        Args:
            members: List of member dictionaries
            side_name: 'left' or 'right'
            node: BinaryNode object (optional, used to get accurate total count from stored counts)
        """
        if not members:
            return None
        
        # If no pagination requested, return all members (backward compatibility)
        if self.page is None or self.page_size is None:
            return members
        
        try:
            page = int(self.page)
            page_size = int(self.page_size)
            
            # Validate page_size (max 100)
            if page_size > 100:
                page_size = 100
            if page_size < 1:
                page_size = 20
            
            # Calculate total count
            # If node is provided, use stored counts for accurate total (accounts for all descendants regardless of depth limit)
            # Otherwise, use the length of fetched members
            if node:
                # Get total count from stored counts
                if side_name == 'left':
                    total_count = node.left_count
                    # Subtract 1 if direct left child exists (since we exclude direct children)
                    from .models import BinaryNode
                    if BinaryNode.objects.filter(parent=node, side='left').exists():
                        total_count = max(0, total_count - 1)
                else:  # right
                    total_count = node.right_count
                    # Subtract 1 if direct right child exists (since we exclude direct children)
                    from .models import BinaryNode
                    if BinaryNode.objects.filter(parent=node, side='right').exists():
                        total_count = max(0, total_count - 1)
            else:
                # Fallback to length of fetched members (may be inaccurate if depth limited)
                total_count = len(members)
            
            total_pages = (total_count + page_size - 1) // page_size  # Ceiling division
            
            # Validate page number
            if page < 1:
                page = 1
            if page > total_pages and total_pages > 0:
                page = total_pages
            
            # Calculate slice indices
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            
            # Get paginated results
            paginated_members = members[start_index:end_index]
            
            # Build pagination URLs if request is available
            next_url = None
            previous_url = None
            
            if self.request:
                from django.http import QueryDict
                from urllib.parse import urlencode
                
                # Get current query parameters
                query_params = self.request.query_params.copy()
                
                # Build next URL
                if page < total_pages:
                    query_params['page'] = page + 1
                    next_url = f"{self.request.build_absolute_uri(self.request.path)}?{query_params.urlencode()}"
                
                # Build previous URL
                if page > 1:
                    query_params['page'] = page - 1
                    previous_url = f"{self.request.build_absolute_uri(self.request.path)}?{query_params.urlencode()}"
            
            return {
                'count': total_count,
                'page': page,
                'page_size': page_size,
                'total_pages': total_pages,
                'next': next_url,
                'previous': previous_url,
                'results': paginated_members
            }
        except (ValueError, TypeError):
            # If pagination parameters are invalid, return all members
            return members
    
    def get_left_side_members(self, obj):
        """
        Get all members on the left side with their details
        Excludes direct left child (already in left_child) to avoid duplication
        Returns paginated results if pagination is requested
        """
        # Skip if filtering for right side only
        if self.side_filter == 'right':
            return None
        
        members = self._get_all_descendants(obj, 'left', self.max_depth, 0, exclude_direct_children=True, min_depth=self.min_depth)
        return self._paginate_side_members(members, 'left', node=obj)
    
    def get_right_side_members(self, obj):
        """
        Get all members on the right side with their details
        Excludes direct right child (already in right_child) to avoid duplication
        Returns paginated results if pagination is requested
        """
        # Skip if filtering for left side only
        if self.side_filter == 'left':
            return None
        
        members = self._get_all_descendants(obj, 'right', self.max_depth, 0, exclude_direct_children=True, min_depth=self.min_depth)
        return self._paginate_side_members(members, 'right', node=obj)


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

