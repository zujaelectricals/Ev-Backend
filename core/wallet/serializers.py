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
        
        # For commission transactions, try to extract TDS from description
        # Format examples:
        # "User commission for user@email.com (₹1000.00 - ₹200.0000 TDS = ₹800.0000)"
        # "Binary commission initial bonus (₹2000.00 - TDS ₹400.0000 = ₹1600.0000)"
        if obj.transaction_type in ['DIRECT_USER_COMMISSION', 'BINARY_PAIR_COMMISSION', 'BINARY_INITIAL_BONUS']:
            if obj.description:
                # Try to extract TDS from description using regex
                # Pattern 1: "₹200.0000 TDS" or "TDS ₹400.0000"
                tds_patterns = [
                    r'TDS\s*₹([\d,]+\.?\d*)',  # "TDS ₹400.0000"
                    r'₹([\d,]+\.?\d*)\s*TDS',  # "₹200.0000 TDS"
                ]
                
                for pattern in tds_patterns:
                    match = re.search(pattern, obj.description)
                    if match:
                        tds_str = match.group(1).replace(',', '')
                        try:
                            return str(Decimal(tds_str))
                        except (ValueError, TypeError):
                            pass
                
                # Pattern 2: Extract from "₹1000.00 - ₹200.0000 TDS = ₹800.0000"
                # This pattern looks for the subtraction format
                subtraction_pattern = r'₹([\d,]+\.?\d*)\s*-\s*₹([\d,]+\.?\d*)\s*TDS'
                match = re.search(subtraction_pattern, obj.description)
                if match:
                    tds_str = match.group(2).replace(',', '')
                    try:
                        return str(Decimal(tds_str))
                    except (ValueError, TypeError):
                        pass
        
        # For other transaction types, no TDS
        return "0.00"

