from rest_framework import serializers
from .models import (
    ComplianceDocument, TDSRecord, DistributorDocument, DistributorDocumentAcceptance,
    AsaTerms, PaymentTerms, UserAsaAcceptance, UserPaymentAcceptance
)
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
        
        attrs['user'] = user
        attrs['document'] = document
        return attrs


# ============================================================================
# ASA Terms Serializers
# ============================================================================

class AsaTermsSerializer(serializers.ModelSerializer):
    """
    Full CRUD serializer for admin/staff to manage ASA Terms
    """
    class Meta:
        model = AsaTerms
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')
    
    def validate(self, attrs):
        """
        Ensure only one active ASA terms version at a time
        """
        is_active = attrs.get('is_active', self.instance.is_active if self.instance else False)
        
        if is_active:
            # Check if there's already an active version
            existing_active = AsaTerms.objects.filter(is_active=True).exclude(pk=self.instance.pk if self.instance else None)
            if existing_active.exists():
                raise serializers.ValidationError(
                    "Only one active ASA Terms version can exist at a time. "
                    "Please deactivate the existing active version first."
                )
        
        return attrs


class AsaTermsListSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for users to view active ASA Terms
    Includes is_accepted status
    """
    is_accepted = serializers.SerializerMethodField()
    user_acceptance = serializers.SerializerMethodField()
    
    class Meta:
        model = AsaTerms
        fields = [
            'id', 'version', 'title', 'full_text', 'effective_from',
            'is_active', 'is_accepted', 'user_acceptance'
        ]
        read_only_fields = fields
    
    def get_is_accepted(self, obj):
        """Check if current user has accepted this ASA Terms version"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return UserAsaAcceptance.objects.filter(
                user=request.user,
                terms_version=obj.version
            ).exists()
        return False
    
    def get_user_acceptance(self, obj):
        """Get user's acceptance record if exists"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            acceptance = UserAsaAcceptance.objects.filter(
                user=request.user,
                terms_version=obj.version
            ).first()
            if acceptance:
                return {
                    'id': acceptance.id,
                    'accepted_at': acceptance.accepted_at,
                    'terms_version': acceptance.terms_version,
                }
        return None


class InitiateAsaAcceptanceSerializer(serializers.Serializer):
    """
    Serializer for initiating ASA Terms acceptance
    Validates that all required checkboxes are checked
    """
    checkboxes_verified = serializers.BooleanField(
        required=True,
        help_text="Must be True - confirms all checkboxes are checked"
    )
    
    def validate_checkboxes_verified(self, value):
        if not value:
            raise serializers.ValidationError(
                "All required checkboxes must be checked to initiate acceptance."
            )
        return value


class VerifyAsaAcceptanceSerializer(serializers.Serializer):
    """
    Serializer for verifying OTP and completing ASA Terms acceptance
    """
    identifier = serializers.CharField(required=True, help_text="User's email or mobile number")
    otp_code = serializers.CharField(required=True, max_length=10)
    otp_type = serializers.ChoiceField(choices=['email', 'mobile'], required=True)
    terms_id = serializers.IntegerField(required=True, help_text="ASA Terms ID")
    
    def validate(self, attrs):
        from core.auth.utils import verify_otp
        
        identifier = attrs['identifier']
        otp_code = attrs['otp_code']
        otp_type = attrs['otp_type']
        terms_id = attrs['terms_id']
        
        # Verify user exists
        try:
            if otp_type == 'email':
                user = User.objects.get(email=identifier)
            else:
                user = User.objects.get(mobile=identifier)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")
        
        # Verify ASA Terms exists and is active
        try:
            asa_terms = AsaTerms.objects.get(id=terms_id, is_active=True)
        except AsaTerms.DoesNotExist:
            raise serializers.ValidationError("ASA Terms not found or is not active.")
        
        # Check if user already accepted this version
        if UserAsaAcceptance.objects.filter(user=user, terms_version=asa_terms.version).exists():
            raise serializers.ValidationError(
                f"You have already accepted ASA Terms version {asa_terms.version}. "
                "Each version can only be accepted once."
            )
        
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
        
        attrs['user'] = user
        attrs['asa_terms'] = asa_terms
        return attrs


class UserAsaAcceptanceSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for viewing ASA acceptance records
    """
    user_username = serializers.CharField(source='user.username', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    terms_title = serializers.SerializerMethodField()
    agreement_pdf_url = serializers.FileField(read_only=True)
    
    class Meta:
        model = UserAsaAcceptance
        fields = '__all__'
        read_only_fields = (
            'id', 'user', 'terms_version', 'accepted_at', 'ip_address', 'user_agent',
            'otp_verified', 'otp_identifier', 'agreement_pdf_url', 'pdf_hash',
            'created_at', 'user_username', 'user_email', 'terms_title'
        )
    
    def get_terms_title(self, obj):
        """Get title of the ASA Terms version that was accepted"""
        try:
            asa_terms = AsaTerms.objects.get(version=obj.terms_version)
            return asa_terms.title
        except AsaTerms.DoesNotExist:
            return f"ASA Terms v{obj.terms_version}"


# ============================================================================
# Payment Terms Serializers
# ============================================================================

class PaymentTermsSerializer(serializers.ModelSerializer):
    """
    Full CRUD serializer for admin/staff to manage Payment Terms
    """
    class Meta:
        model = PaymentTerms
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


class PaymentTermsListSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for users to view active Payment Terms
    """
    is_accepted = serializers.SerializerMethodField()
    
    class Meta:
        model = PaymentTerms
        fields = [
            'id', 'version', 'title', 'full_text', 'effective_from',
            'is_active', 'is_accepted'
        ]
        read_only_fields = fields
    
    def get_is_accepted(self, obj):
        """Check if current user has accepted this Payment Terms version"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return UserPaymentAcceptance.objects.filter(
                user=request.user,
                payment_terms_version=obj.version
            ).exists()
        return False


class InitiatePaymentTermsSerializer(serializers.Serializer):
    """
    Serializer for initiating Payment Terms acceptance
    No additional validation needed - just triggers OTP sending
    """
    pass  # No fields needed - just triggers OTP sending


class VerifyPaymentTermsSerializer(serializers.Serializer):
    """
    Serializer for verifying OTP and completing Payment Terms acceptance
    """
    identifier = serializers.CharField(required=True, help_text="User's email or mobile number")
    otp_code = serializers.CharField(required=True, max_length=10)
    otp_type = serializers.ChoiceField(choices=['email', 'mobile'], required=True)
    terms_id = serializers.IntegerField(required=True, help_text="Payment Terms ID")
    generate_pdf = serializers.BooleanField(default=False, help_text="Whether to generate receipt PDF")
    
    def validate(self, attrs):
        from core.auth.utils import verify_otp
        
        identifier = attrs['identifier']
        otp_code = attrs['otp_code']
        otp_type = attrs['otp_type']
        terms_id = attrs['terms_id']
        
        # Verify user exists
        try:
            if otp_type == 'email':
                user = User.objects.get(email=identifier)
            else:
                user = User.objects.get(mobile=identifier)
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")
        
        # Verify Payment Terms exists and is active
        try:
            payment_terms = PaymentTerms.objects.get(id=terms_id, is_active=True)
        except PaymentTerms.DoesNotExist:
            raise serializers.ValidationError("Payment Terms not found or is not active.")
        
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
        
        attrs['user'] = user
        attrs['payment_terms'] = payment_terms
        return attrs


class AcceptPaymentTermsSerializer(serializers.Serializer):
    """
    Serializer for accepting Payment Terms
    OTP is required for first-time acceptance
    """
    identifier = serializers.CharField(required=False, help_text="User's email or mobile (required if OTP needed)")
    otp_code = serializers.CharField(required=False, max_length=10, help_text="OTP code (required if OTP needed)")
    otp_type = serializers.ChoiceField(choices=['email', 'mobile'], required=False, help_text="OTP type (required if OTP needed)")
    terms_id = serializers.IntegerField(required=True, help_text="Payment Terms ID")
    generate_pdf = serializers.BooleanField(default=False, help_text="Whether to generate receipt PDF")
    
    def validate(self, attrs):
        from core.auth.utils import verify_otp
        
        terms_id = attrs['terms_id']
        user = self.context['request'].user
        
        # Verify Payment Terms exists and is active
        try:
            payment_terms = PaymentTerms.objects.get(id=terms_id, is_active=True)
        except PaymentTerms.DoesNotExist:
            raise serializers.ValidationError("Payment Terms not found or is not active.")
        
        # Check if this is first-time acceptance
        is_first_time = not UserPaymentAcceptance.objects.filter(
            user=user,
            payment_terms_version=payment_terms.version
        ).exists()
        
        # OTP is required for first-time acceptance
        if is_first_time:
            identifier = attrs.get('identifier')
            otp_code = attrs.get('otp_code')
            otp_type = attrs.get('otp_type')
            
            if not identifier or not otp_code or not otp_type:
                raise serializers.ValidationError(
                    "OTP verification is required for first-time Payment Terms acceptance. "
                    "Please provide identifier, otp_code, and otp_type."
                )
            
            # Verify OTP
            if user.email and user.mobile:
                email_valid = verify_otp(user.email, otp_code, 'email')
                mobile_valid = verify_otp(user.mobile, otp_code, 'mobile')
                
                if not email_valid and not mobile_valid:
                    raise serializers.ValidationError("Invalid or expired OTP")
                
                if email_valid:
                    attrs['otp_identifier'] = user.email
                else:
                    attrs['otp_identifier'] = user.mobile
                attrs['otp_verified'] = True
            else:
                if not verify_otp(identifier, otp_code, otp_type):
                    raise serializers.ValidationError("Invalid or expired OTP")
                attrs['otp_identifier'] = identifier
                attrs['otp_verified'] = True
        else:
            # Not first time - OTP optional
            attrs['otp_verified'] = False
            attrs['otp_identifier'] = ''
        
        attrs['payment_terms'] = payment_terms
        return attrs


class UserPaymentAcceptanceSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for viewing Payment acceptance records
    """
    user_username = serializers.CharField(source='user.username', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    terms_title = serializers.SerializerMethodField()
    receipt_pdf_url = serializers.SerializerMethodField()
    
    class Meta:
        model = UserPaymentAcceptance
        fields = '__all__'
        read_only_fields = (
            'id', 'user', 'payment_terms_version', 'accepted_at', 'ip_address', 'user_agent',
            'otp_verified', 'otp_identifier', 'receipt_pdf_url', 'created_at',
            'user_username', 'user_email', 'terms_title'
        )
    
    def get_terms_title(self, obj):
        """Get title of the Payment Terms version that was accepted"""
        try:
            payment_terms = PaymentTerms.objects.get(version=obj.payment_terms_version)
            return payment_terms.title
        except PaymentTerms.DoesNotExist:
            return f"Payment Terms v{obj.payment_terms_version}"
    
    def get_receipt_pdf_url(self, obj):
        """Return absolute URL for the receipt PDF"""
        if obj.receipt_pdf_url:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.receipt_pdf_url.url)
            return obj.receipt_pdf_url.url
        return None

