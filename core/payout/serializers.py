from rest_framework import serializers
from .models import Payout, PayoutTransaction


class PayoutSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    wallet_balance = serializers.DecimalField(source='wallet.balance', read_only=True, max_digits=12, decimal_places=2)
    bank_details = serializers.SerializerMethodField()
    
    class Meta:
        model = Payout
        fields = '__all__'
        read_only_fields = ('user', 'wallet', 'tds_amount', 'net_amount', 'status', 
                          'created_at', 'processed_at', 'completed_at', 'transaction_id', 
                          'emi_amount')
    
    def get_bank_details(self, obj):
        """Get bank details from user's KYC document"""
        user = obj.user
        bank_details = []
        
        # Check if user has KYC with bank details
        try:
            kyc = user.kyc
            if kyc and kyc.bank_name and kyc.account_number:
                bank_details.append({
                    'bank_name': kyc.bank_name,
                    'account_number': kyc.account_number,
                    'ifsc_code': kyc.ifsc_code or '',
                    'account_holder_name': kyc.account_holder_name or ''
                })
        except Exception:
            # User doesn't have KYC or KYC doesn't have bank details
            pass
        
        return bank_details
    
    def validate_requested_amount(self, value):
        """Validate requested amount"""
        if value <= 0:
            raise serializers.ValidationError("Amount must be greater than 0")
        return value


class PayoutTransactionSerializer(serializers.ModelSerializer):
    payout_id = serializers.IntegerField(source='payout.id', read_only=True)
    
    class Meta:
        model = PayoutTransaction
        fields = '__all__'
        read_only_fields = ('payout', 'user', 'created_at')

