from rest_framework import serializers
import re
from decimal import Decimal
from .models import Wallet, WalletTransaction


class WalletSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_mobile = serializers.CharField(source='user.mobile', read_only=True)
    
    class Meta:
        model = Wallet
        fields = '__all__'
        read_only_fields = ('user', 'balance', 'total_earned', 'total_withdrawn', 
                          'created_at', 'updated_at')


class WalletTransactionSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()
    tds_amount = serializers.SerializerMethodField()
    
    class Meta:
        model = WalletTransaction
        # Exclude 'user' field and include 'user_name' instead, plus add 'tds_amount'
        fields = ['id', 'user_name', 'user_email', 'wallet', 'transaction_type', 'amount', 
                 'balance_before', 'balance_after', 'description', 'reference_id', 'reference_type', 
                 'created_at', 'tds_amount']
        read_only_fields = ('wallet', 'balance_before', 'balance_after', 'created_at')
    
    def get_user_name(self, obj):
        """Get user's full name or username"""
        if obj.user.get_full_name():
            return obj.user.get_full_name().strip()
        return obj.user.username or obj.user.email or 'N/A'
    
    def get_tds_amount(self, obj):
        """Calculate or extract TDS amount from transaction"""
        # For TDS_DEDUCTION transactions, the amount itself is the TDS (negative value)
        if obj.transaction_type == 'TDS_DEDUCTION':
            return str(abs(obj.amount))

        def _parse_tds_from_description(description):
            """Try to extract TDS from description text; returns Decimal or None."""
            if not description:
                return None
            tds_patterns = [
                r'TDS\s*₹([\d,]+\.?\d*)',
                r'₹([\d,]+\.?\d*)\s*TDS',
            ]
            for pattern in tds_patterns:
                match = re.search(pattern, description)
                if match:
                    tds_str = match.group(1).replace(',', '')
                    try:
                        return Decimal(tds_str)
                    except (ValueError, TypeError):
                        pass
            subtraction_pattern = r'₹([\d,]+\.?\d*)\s*-\s*₹([\d,]+\.?\d*)\s*TDS'
            match = re.search(subtraction_pattern, description)
            if match:
                tds_str = match.group(2).replace(',', '')
                try:
                    return Decimal(tds_str)
                except (ValueError, TypeError):
                    pass
            return None

        # For commission transactions: try description first, then related TDS_DEDUCTION or derived value
        if obj.transaction_type in ['DIRECT_USER_COMMISSION', 'BINARY_PAIR_COMMISSION', 'BINARY_INITIAL_BONUS']:
            from django.db.models import Sum

            tds_from_desc = _parse_tds_from_description(obj.description or '')
            if tds_from_desc is not None and tds_from_desc >= 0:
                return str(tds_from_desc)

            # BINARY_PAIR_COMMISSION: look up related TDS_DEDUCTION or derive from BinaryPair
            if obj.transaction_type == 'BINARY_PAIR_COMMISSION' and obj.reference_id and obj.reference_type == 'binary_pair':
                related_tds = WalletTransaction.objects.filter(
                    user=obj.user,
                    transaction_type='TDS_DEDUCTION',
                    reference_id=obj.reference_id,
                    reference_type='binary_pair'
                ).aggregate(total=Sum('amount'))
                total = related_tds.get('total')
                if total is not None and total != 0:
                    return str(abs(total))
                # Derive TDS from BinaryPair: pair_amount - earning_amount - extra_deduction_applied
                try:
                    from core.binary.models import BinaryPair
                    pair = BinaryPair.objects.filter(id=obj.reference_id).first()
                    if pair and pair.pair_amount is not None and pair.earning_amount is not None:
                        extra = getattr(pair, 'extra_deduction_applied', None) or Decimal('0')
                        tds = Decimal(str(pair.pair_amount)) - Decimal(str(pair.earning_amount)) - Decimal(str(extra))
                        if tds > 0:
                            return str(tds)
                except Exception:
                    pass
                return "0.00"

            # DIRECT_USER_COMMISSION: look up related TDS_DEDUCTION (reference_type='user', reference_id=referred user id)
            if obj.transaction_type == 'DIRECT_USER_COMMISSION' and obj.reference_id is not None and obj.reference_type == 'user':
                related_tds = WalletTransaction.objects.filter(
                    user=obj.user,
                    transaction_type='TDS_DEDUCTION',
                    reference_id=obj.reference_id,
                    reference_type='user'
                ).aggregate(total=Sum('amount'))
                total = related_tds.get('total')
                if total is not None and total != 0:
                    return str(abs(total))
                return "0.00"

            # BINARY_INITIAL_BONUS: only description parsing (no reference-based TDS_DEDUCTION in codebase)
            if obj.transaction_type == 'BINARY_INITIAL_BONUS':
                return "0.00"

        return "0.00"


class CreateWalletRefundSerializer(serializers.Serializer):
    """Serializer for creating wallet refund (Admin/Staff only)"""
    user_id = serializers.IntegerField(
        required=True,
        help_text="User ID to refund to"
    )
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=True,
        help_text="Refund amount in rupees"
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional description for the refund"
    )
    reference_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Optional reference ID (e.g., booking ID)"
    )
    reference_type = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        help_text="Optional reference type (e.g., 'booking', 'order')"
    )

