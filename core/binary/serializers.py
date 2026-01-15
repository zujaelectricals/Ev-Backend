from rest_framework import serializers
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
    left_child = serializers.SerializerMethodField()
    right_child = serializers.SerializerMethodField()
    left_side_members = serializers.SerializerMethodField()
    right_side_members = serializers.SerializerMethodField()
    
    class Meta:
        model = BinaryNode
        fields = [
            'id', 'user_id', 'user_email', 'user_username', 'user_full_name',
            'user_mobile', 'user_first_name', 'user_last_name', 'user_city', 'user_state',
            'is_distributor', 'is_active_buyer', 'referral_code', 'date_joined',
            'wallet_balance', 'total_bookings', 'total_binary_pairs', 'total_earnings',
            'parent', 'side', 'level', 'left_count', 'right_count',
            'left_child', 'right_child', 'left_side_members', 'right_side_members',
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
        """Get user's wallet balance"""
        if obj.user and hasattr(obj.user, 'wallet'):
            return str(obj.user.wallet.balance)
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
        """Get total earnings from wallet"""
        if obj.user and hasattr(obj.user, 'wallet'):
            return str(obj.user.wallet.total_earned)
        return "0.00"
    
    def get_left_child(self, obj):
        """Get left child node recursively"""
        if self.current_depth >= self.max_depth:
            return None
        
        try:
            # Optimize query with select_related
            left_child = BinaryNode.objects.select_related(
                'user', 'user__wallet', 'parent', 'parent__user'
            ).get(parent=obj, side='left')
            serializer = BinaryTreeNodeSerializer(
                left_child,
                max_depth=self.max_depth,
                current_depth=self.current_depth + 1
            )
            return serializer.data
        except BinaryNode.DoesNotExist:
            return None
    
    def get_right_child(self, obj):
        """Get right child node recursively"""
        if self.current_depth >= self.max_depth:
            return None
        
        try:
            # Optimize query with select_related
            right_child = BinaryNode.objects.select_related(
                'user', 'user__wallet', 'parent', 'parent__user'
            ).get(parent=obj, side='right')
            serializer = BinaryTreeNodeSerializer(
                right_child,
                max_depth=self.max_depth,
                current_depth=self.current_depth + 1
            )
            return serializer.data
        except BinaryNode.DoesNotExist:
            return None
    
    def _get_all_descendants(self, node, side, max_depth, current_depth=0):
        """Get all descendant nodes on a specific side"""
        if current_depth >= max_depth:
            return []
        
        descendants = []
        # Get direct children on the specified side
        children = BinaryNode.objects.select_related(
            'user', 'user__wallet', 'parent', 'parent__user'
        ).filter(parent=node, side=side)
        
        for child in children:
            # Create a simplified serializer for list view (without nested children to avoid duplication)
            child_data = {
                'id': child.id,
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
                'wallet_balance': str(child.user.wallet.balance) if hasattr(child.user, 'wallet') else "0.00",
                'total_bookings': self._get_total_bookings(child.user),
                'total_binary_pairs': self._get_total_binary_pairs(child.user),
                'total_earnings': str(child.user.wallet.total_earned) if hasattr(child.user, 'wallet') else "0.00",
                'parent': child.parent.id if child.parent else None,
                'side': child.side,
                'level': child.level,
                'left_count': child.left_count,
                'right_count': child.right_count,
                'created_at': child.created_at,
                'updated_at': child.updated_at
            }
            descendants.append(child_data)
            
            # Recursively get descendants of this child
            descendants.extend(self._get_all_descendants(child, 'left', max_depth, current_depth + 1))
            descendants.extend(self._get_all_descendants(child, 'right', max_depth, current_depth + 1))
        
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
    
    def get_left_side_members(self, obj):
        """Get all members on the left side with their details"""
        return self._get_all_descendants(obj, 'left', self.max_depth, 0)
    
    def get_right_side_members(self, obj):
        """Get all members on the right side with their details"""
        return self._get_all_descendants(obj, 'right', self.max_depth, 0)


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

