from rest_framework import serializers
from .models import BinaryNode, BinaryPair, BinaryEarning


class BinaryNodeSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    parent_username = serializers.CharField(source='parent.user.username', read_only=True)
    
    class Meta:
        model = BinaryNode
        fields = '__all__'
        read_only_fields = ('user', 'created_at', 'updated_at')


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

