from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import User, KYC, Nominee


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'mobile', 'first_name', 'last_name',
                  'gender', 'date_of_birth', 'address_line1', 'address_line2',
                  'city', 'state', 'pincode', 'country',
                  'role', 'is_distributor', 'is_active_buyer', 'referral_code', 
                  'date_joined', 'last_login')
        read_only_fields = ('id', 'role', 'is_distributor', 'is_active_buyer', 
                           'referral_code', 'date_joined', 'last_login')


class UserProfileSerializer(serializers.ModelSerializer):
    kyc_status = serializers.SerializerMethodField()
    nominee_exists = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'mobile', 'first_name', 'last_name',
                  'gender', 'date_of_birth', 'address_line1', 'address_line2',
                  'city', 'state', 'pincode', 'country',
                  'role', 'is_distributor', 'is_active_buyer', 'referral_code',
                  'referred_by', 'kyc_status', 'nominee_exists', 'date_joined')
        read_only_fields = ('id', 'role', 'is_distributor', 'is_active_buyer',
                           'referral_code', 'referred_by', 'date_joined')
    
    def get_kyc_status(self, obj):
        if hasattr(obj, 'kyc'):
            return obj.kyc.status
        return None
    
    def get_nominee_exists(self, obj):
        return hasattr(obj, 'nominee')


class KYCSerializer(serializers.ModelSerializer):
    class Meta:
        model = KYC
        fields = '__all__'
        read_only_fields = ('user', 'submitted_at', 'reviewed_at', 'reviewed_by')


class NomineeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Nominee
        fields = '__all__'
        read_only_fields = ('user', 'created_at', 'updated_at')

