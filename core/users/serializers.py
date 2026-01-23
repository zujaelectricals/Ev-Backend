from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import User, KYC, Nominee, DistributorApplication
from django.utils import timezone


class ReferredByUserSerializer(serializers.Serializer):
    """Nested serializer for referred_by user details"""
    id = serializers.IntegerField()
    fullname = serializers.SerializerMethodField()
    email = serializers.EmailField()
    
    def get_fullname(self, obj):
        """Get full name from first_name and last_name"""
        return obj.get_full_name() if obj else None
    
    def to_representation(self, instance):
        """Handle None values"""
        if instance is None:
            return None
        return super().to_representation(instance)


class ReviewedByUserSerializer(serializers.Serializer):
    """Nested serializer for reviewed_by user details"""
    id = serializers.IntegerField()
    fullname = serializers.SerializerMethodField()
    email = serializers.EmailField()
    
    def get_fullname(self, obj):
        """Get full name from first_name and last_name"""
        return obj.get_full_name() if obj else None
    
    def to_representation(self, instance):
        """Handle None values"""
        if instance is None:
            return None
        return super().to_representation(instance)


class UserSerializer(serializers.ModelSerializer):
    kyc_status = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ('id', 'email', 'mobile', 'first_name', 'last_name',
                  'gender', 'date_of_birth', 'address_line1', 'address_line2',
                  'city', 'state', 'pincode', 'country',
                  'role', 'is_distributor', 'is_active_buyer', 'referral_code', 
                  'date_joined', 'last_login', 'kyc_status')
        read_only_fields = ('id', 'role', 'is_distributor', 'is_active_buyer', 
                           'referral_code', 'date_joined', 'last_login', 'kyc_status')
    
    def get_kyc_status(self, obj):
        """Get KYC status if KYC exists for the user"""
        # For OneToOneField reverse relationships, use hasattr which safely checks existence
        # This avoids triggering unnecessary database queries
        if hasattr(obj, 'kyc') and obj.kyc is not None:
            return obj.kyc.status
        return None


class UserProfileSerializer(serializers.ModelSerializer):
    kyc_status = serializers.SerializerMethodField()
    nominee_exists = serializers.SerializerMethodField()
    referred_by = ReferredByUserSerializer(read_only=True, allow_null=True)
    binary_commission_active = serializers.SerializerMethodField()
    binary_pairs_matched = serializers.SerializerMethodField()
    left_leg_count = serializers.SerializerMethodField()
    right_leg_count = serializers.SerializerMethodField()
    carry_forward_left = serializers.SerializerMethodField()
    carry_forward_right = serializers.SerializerMethodField()
    is_distributor_terms_and_conditions_accepted = serializers.SerializerMethodField()
    distributor_application_status = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'mobile', 'first_name', 'last_name',
                  'gender', 'date_of_birth', 'address_line1', 'address_line2',
                  'city', 'state', 'pincode', 'country',
                  'role', 'is_distributor', 'is_active_buyer', 'referral_code',
                  'referred_by', 'kyc_status', 'nominee_exists', 'date_joined',
                  'binary_commission_active', 'binary_pairs_matched', 'left_leg_count',
                  'right_leg_count', 'carry_forward_left', 'carry_forward_right',
                  'is_distributor_terms_and_conditions_accepted', 'distributor_application_status')
        read_only_fields = ('id', 'role', 'is_distributor', 'is_active_buyer',
                           'referral_code', 'referred_by', 'date_joined')
    
    def get_kyc_status(self, obj):
        """Get KYC status if KYC exists for the user"""
        # For OneToOneField reverse relationships, use hasattr which safely checks existence
        # This avoids triggering unnecessary database queries
        if hasattr(obj, 'kyc') and obj.kyc is not None:
            return obj.kyc.status
        return None
    
    def get_nominee_exists(self, obj):
        """Check if nominee exists for the user"""
        # For OneToOneField reverse relationships, use hasattr which safely checks existence
        return hasattr(obj, 'nominee') and obj.nominee is not None
    
    def get_binary_commission_active(self, obj):
        """Get binary_commission_activated status from BinaryNode"""
        if hasattr(obj, 'binary_node') and obj.binary_node:
            return obj.binary_node.binary_commission_activated
        return False
    
    def get_binary_pairs_matched(self, obj):
        """Count total binary pairs matched after activation"""
        from core.binary.models import BinaryPair
        return BinaryPair.objects.filter(
            user=obj,
            pair_number_after_activation__isnull=False
        ).count()
    
    def get_left_leg_count(self, obj):
        """Get left_count from BinaryNode"""
        if hasattr(obj, 'binary_node') and obj.binary_node:
            return obj.binary_node.left_count
        return 0
    
    def get_right_leg_count(self, obj):
        """Get right_count from BinaryNode"""
        if hasattr(obj, 'binary_node') and obj.binary_node:
            return obj.binary_node.right_count
        return 0
    
    def get_carry_forward_left(self, obj):
        """Get carry-forward count for left leg"""
        from core.binary.models import BinaryCarryForward
        active_carry = BinaryCarryForward.objects.filter(
            user=obj,
            side='left',
            is_active=True
        ).first()
        return active_carry.remaining_count if active_carry else 0
    
    def get_carry_forward_right(self, obj):
        """Get carry-forward count for right leg"""
        from core.binary.models import BinaryCarryForward
        active_carry = BinaryCarryForward.objects.filter(
            user=obj,
            side='right',
            is_active=True
        ).first()
        return active_carry.remaining_count if active_carry else 0
    
    def get_is_distributor_terms_and_conditions_accepted(self, obj):
        """Get terms and conditions acceptance status from DistributorApplication"""
        if hasattr(obj, 'distributor_application') and obj.distributor_application is not None:
            return obj.distributor_application.is_distributor_terms_and_conditions_accepted
        return None
    
    def get_distributor_application_status(self, obj):
        """Get distributor application status if application exists for the user"""
        # For OneToOneField reverse relationships, use hasattr which safely checks existence
        # This avoids triggering unnecessary database queries
        if hasattr(obj, 'distributor_application') and obj.distributor_application is not None:
            return obj.distributor_application.status
        return None


class KYCSerializer(serializers.ModelSerializer):
    reviewed_by = ReviewedByUserSerializer(read_only=True, allow_null=True)
    
    class Meta:
        model = KYC
        fields = '__all__'
        read_only_fields = ('user', 'submitted_at', 'reviewed_at', 'reviewed_by')
    
    def update(self, instance, validated_data):
        """Update KYC and reset status to pending when resubmitting after rejection"""
        # If KYC was previously rejected and user is resubmitting, reset status to pending
        # Also clear rejection reason and reset review fields
        was_rejected = instance.status == 'rejected'
        
        # Update the instance with new data
        instance = super().update(instance, validated_data)
        
        # If it was rejected, reset status and clear review information
        if was_rejected:
            instance.status = 'pending'
            instance.rejection_reason = ''
            instance.reviewed_by = None
            instance.reviewed_at = None
            instance.save(update_fields=['status', 'rejection_reason', 'reviewed_by', 'reviewed_at'])
        
        return instance


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


class DistributorApplicationSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)
    user_full_name = serializers.SerializerMethodField()
    reviewed_by = ReviewedByUserSerializer(read_only=True, allow_null=True)
    is_distributor_terms_and_conditions_accepted = serializers.BooleanField(required=False)
    
    class Meta:
        model = DistributorApplication
        fields = '__all__'
        read_only_fields = ('user', 'status', 'submitted_at', 'reviewed_at', 'reviewed_by')
    
    def get_user_full_name(self, obj):
        return obj.user.get_full_name()
    
    def validate_is_distributor_terms_and_conditions_accepted(self, value):
        """Validate that terms and conditions must be accepted"""
        if not value:
            raise serializers.ValidationError('You cannot Proceed without Accepting Terms and Conditions')
        return value
    
    def validate(self, data):
        """Validate eligibility before allowing application"""
        user = self.context['request'].user
        
        # Check if user has approved KYC (Active Buyer requirement removed)
        if not hasattr(user, 'kyc') or user.kyc.status != 'approved':
            raise serializers.ValidationError({
                'non_field_errors': ['User must have approved KYC to apply for distributor program.']
            })
        
        # Check if application already exists
        if hasattr(user, 'distributor_application'):
            raise serializers.ValidationError({
                'non_field_errors': ['Application already exists. You can only submit one distributor application.']
            })
        
        # Validate terms and conditions acceptance - must be explicitly True
        terms_accepted = data.get('is_distributor_terms_and_conditions_accepted', False)
        if not terms_accepted:
            raise serializers.ValidationError({
                'is_distributor_terms_and_conditions_accepted': ['You cannot Proceed without Accepting Terms and Conditions']
            })
        
        return data
    
    def create(self, validated_data):
        """Create distributor application for the current user (automatically approved)"""
        user = self.context['request'].user
        validated_data['user'] = user
        # Status will be set to 'approved' in the view
        return super().create(validated_data)

