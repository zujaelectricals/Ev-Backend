from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import User, KYC, Nominee
from django.utils import timezone


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email', 'mobile', 'first_name', 'last_name',
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
        read_only_fields = ('user', 'created_at', 'updated_at',
                            'kyc_status', 'kyc_submitted_at', 'kyc_verified_at', 'kyc_verified_by', 'kyc_rejection_reason')

    def validate_id_proof_document(self, value):
        # Basic file validation: allow common image types and limit size to 5MB
        valid_mime_prefix = 'image/'
        max_size = 5 * 1024 * 1024
        content_type = getattr(value, 'content_type', '')
        if content_type and not content_type.startswith(valid_mime_prefix):
            raise serializers.ValidationError('Invalid file type. Only images are allowed for id proof.')
        if value.size > max_size:
            raise serializers.ValidationError('File size must be <= 5MB')
        return value

    def create(self, validated_data):
        # If user submitted an id_proof_document or id_proof_number, mark nominee KYC as pending
        id_doc = validated_data.get('id_proof_document')
        id_number = validated_data.get('id_proof_number')
        # Ensure kyc_status is always present to avoid NOT NULL DB errors
        validated_data.setdefault('kyc_status', Nominee.KYC_PENDING)
        if id_doc or id_number:
            validated_data['kyc_submitted_at'] = timezone.now()
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # If user updates/ uploads id proof, set status back to pending unless already verified
        id_doc = validated_data.get('id_proof_document', None)
        id_number = validated_data.get('id_proof_number', None)
        instance = super().update(instance, validated_data)
        if (id_doc or id_number) and instance.kyc_status != Nominee.KYC_VERIFIED:
            instance.kyc_status = Nominee.KYC_PENDING
            instance.kyc_submitted_at = timezone.now()
            instance.save(update_fields=['kyc_status', 'kyc_submitted_at'])
        return instance

