from rest_framework import serializers
from .models import Payout, PayoutTransaction


class PayoutSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    wallet_balance = serializers.DecimalField(source='wallet.balance', read_only=True, max_digits=12, decimal_places=2)
    
    class Meta:
        model = Payout
        fields = '__all__'
        read_only_fields = ('user', 'wallet', 'tds_amount', 'net_amount', 'status', 
                          'created_at', 'processed_at', 'completed_at', 'transaction_id', 
                          'emi_amount')
    
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

