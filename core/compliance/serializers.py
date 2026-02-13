from rest_framework import serializers
from .models import ComplianceDocument, TDSRecord, DistributorDocument, DistributorDocumentAcceptance
from core.users.models import User


class ComplianceDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplianceDocument
        fields = '__all__'
        read_only_fields = ('user', 'uploaded_at', 'verified_at', 'verified_by', 'is_verified')


class TDSRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = TDSRecord
        fields = '__all__'
        read_only_fields = ('user', 'created_at')


class DistributorDocumentSerializer(serializers.ModelSerializer):
    """
    Full CRUD serializer for admin/staff to manage distributor documents
    """
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    acceptance_count = serializers.SerializerMethodField()
    
    class Meta:
        model = DistributorDocument
        fields = '__all__'
        read_only_fields = ('created_by', 'created_at', 'updated_at')
    
    def get_acceptance_count(self, obj):
        """Get number of users who have accepted this document"""
        return obj.acceptances.count()


class DistributorDocumentListSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for users to view active documents
    Excludes admin-only fields
    """
    is_accepted = serializers.SerializerMethodField()
    user_acceptance = serializers.SerializerMethodField()
    
    class Meta:
        model = DistributorDocument
        fields = [
            'id', 'title', 'document_type', 'content', 'file', 'version',
            'is_required', 'effective_from', 'effective_until',
            'is_accepted', 'user_acceptance'
        ]
        read_only_fields = fields
    
    def get_is_accepted(self, obj):
        """Check if current user has accepted this document"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.acceptances.filter(
                user=request.user,
                accepted_version=obj.version
            ).exists()
        return False
    
    def get_user_acceptance(self, obj):
        """Get user's acceptance record if exists"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            acceptance = obj.acceptances.filter(
                user=request.user,
                accepted_version=obj.version
            ).first()
            if acceptance:
                return {
                    'accepted_at': acceptance.accepted_at,
                    'accepted_version': acceptance.accepted_version,
                }
        return None


class DistributorDocumentAcceptanceSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for viewing document acceptances
    """
    user_username = serializers.CharField(source='user.username', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    document_title = serializers.CharField(source='document.title', read_only=True)
    document_type = serializers.CharField(source='document.document_type', read_only=True)
    
    class Meta:
        model = DistributorDocumentAcceptance
        fields = '__all__'
        read_only_fields = (
            'id', 'user', 'document', 'accepted_at', 'ip_address', 'user_agent',
            'otp_verified', 'otp_identifier', 'accepted_version', 'timeline_data',
            'user_info_snapshot', 'user_username', 'user_email', 'document_title', 'document_type'
        )


class AcceptDocumentSerializer(serializers.Serializer):
    """
    Serializer for initiating document acceptance
    """
    identifier = serializers.CharField(required=True, help_text="User's email or mobile number")
    otp_type = serializers.ChoiceField(choices=['email', 'mobile'], required=True)
    
    def validate(self, attrs):
        identifier = attrs['identifier']
        otp_type = attrs['otp_type']
        
        # Validate identifier format
        if otp_type == 'email':
            if '@' not in identifier:
                raise serializers.ValidationError("Invalid email format")
        elif otp_type == 'mobile':
            if not identifier.isdigit() or len(identifier) < 10:
                raise serializers.ValidationError("Invalid mobile number")
        
        # Verify user exists
        try:
            if otp_type == 'email':
                user = User.objects.get(email=identifier)
            else:
                user = User.objects.get(mobile=identifier)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                "User not found. Only existing users can accept documents."
            )
        
        # Store user in validated_data for use in view
        attrs['user'] = user
        return attrs


class VerifyAcceptanceOTPSerializer(serializers.Serializer):
    """
    Serializer for verifying OTP and completing document acceptance
    """
    identifier = serializers.CharField(required=True)
    otp_code = serializers.CharField(required=True, max_length=10)
    otp_type = serializers.ChoiceField(choices=['email', 'mobile'], required=True)
    document_id = serializers.IntegerField(required=True)
    
    def validate(self, attrs):
        from core.auth.utils import verify_otp
        
        identifier = attrs['identifier']
        otp_code = attrs['otp_code']
        otp_type = attrs['otp_type']
        document_id = attrs['document_id']
        
        # Verify user exists
        try:
            if otp_type == 'email':
                user = User.objects.get(email=identifier)
            else:
                user = User.objects.get(mobile=identifier)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                "User not found. Only existing users can verify OTP."
            )
        
        # Verify document exists
        try:
            document = DistributorDocument.objects.get(id=document_id, is_active=True)
        except DistributorDocument.DoesNotExist:
            raise serializers.ValidationError("Document not found or is not active.")
        
        # Verify OTP
        if user.email and user.mobile:
            # User has both email and mobile, check both
            email_valid = verify_otp(user.email, otp_code, 'email')
            mobile_valid = verify_otp(user.mobile, otp_code, 'mobile')
            
            if not email_valid and not mobile_valid:
                raise serializers.ValidationError("Invalid or expired OTP")
            
            # Determine which identifier was used
            if email_valid:
                attrs['otp_identifier'] = user.email
            else:
                attrs['otp_identifier'] = user.mobile
        else:
            # User has only one channel
            if not verify_otp(identifier, otp_code, otp_type):
                raise serializers.ValidationError("Invalid or expired OTP")
            attrs['otp_identifier'] = identifier
        
        # Check if user already accepted this version
        existing_acceptance = DistributorDocumentAcceptance.objects.filter(
            user=user,
            document=document,
            accepted_version=document.version
        ).exists()
        
        if existing_acceptance:
            raise serializers.ValidationError(
                f"You have already accepted this document (version {document.version})."
            )
        
        attrs['user'] = user
        attrs['document'] = document
        return attrs

