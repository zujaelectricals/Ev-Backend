from rest_framework import serializers
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
    
    class Meta:
        model = WalletTransaction
        fields = '__all__'
        read_only_fields = ('user', 'wallet', 'balance_before', 'balance_after', 'created_at')

