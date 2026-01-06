from rest_framework import serializers
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .utils import (
    send_email_otp, send_mobile_otp, verify_otp, generate_referral_code,
    store_signup_session, get_signup_session, delete_signup_session
)

User = get_user_model()


class SendOTPSerializer(serializers.Serializer):
    identifier = serializers.CharField(required=True)
    otp_type = serializers.ChoiceField(choices=['email', 'mobile'], required=True)
    
    def validate(self, attrs):
        identifier = attrs['identifier']
        otp_type = attrs['otp_type']
        
        if otp_type == 'email':
            if '@' not in identifier:
                raise serializers.ValidationError("Invalid email format")
        elif otp_type == 'mobile':
            if not identifier.isdigit() or len(identifier) < 10:
                raise serializers.ValidationError("Invalid mobile number")
        
        return attrs
    
    def create(self, validated_data):
        identifier = validated_data['identifier']
        otp_type = validated_data['otp_type']
        
        if otp_type == 'email':
            send_email_otp(identifier)
        else:
            send_mobile_otp(identifier)
        
        return {'message': f'OTP sent to {identifier}'}


class VerifyOTPSerializer(serializers.Serializer):
    identifier = serializers.CharField(required=True)
    otp_code = serializers.CharField(required=True, max_length=10)
    otp_type = serializers.ChoiceField(choices=['email', 'mobile'], required=True)
    referral_code = serializers.CharField(required=False, allow_blank=True)
    
    def validate(self, attrs):
        identifier = attrs['identifier']
        otp_code = attrs['otp_code']
        otp_type = attrs['otp_type']
        
        if not verify_otp(identifier, otp_code, otp_type):
            raise serializers.ValidationError("Invalid or expired OTP")
        
        return attrs
    
    def create(self, validated_data):
        identifier = validated_data['identifier']
        otp_type = validated_data['otp_type']
        referral_code = validated_data.get('referral_code')
        
        # Get or create user
        if otp_type == 'email':
            user, created = User.objects.get_or_create(
                email=identifier,
                defaults={'username': identifier}
            )
        else:
            user, created = User.objects.get_or_create(
                mobile=identifier,
                defaults={'username': identifier}
            )
        
        # Handle referral
        if referral_code and created:
            try:
                referrer = User.objects.get(referral_code=referral_code)
                user.referred_by = referrer
                user.save(update_fields=['referred_by'])
            except User.DoesNotExist:
                pass
        
        # Generate referral code if new user
        if created and not user.referral_code:
            generate_referral_code(user)
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        
        return {
            'user': user,
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        }


class RefreshTokenSerializer(serializers.Serializer):
    refresh = serializers.CharField(required=True)


class SignupSerializer(serializers.Serializer):
    """Serializer for user signup with all details"""
    first_name = serializers.CharField(required=True, max_length=150)
    last_name = serializers.CharField(required=True, max_length=150)
    email = serializers.EmailField(required=True)
    mobile = serializers.CharField(required=True, max_length=15)
    gender = serializers.ChoiceField(choices=['male', 'female', 'other'], required=True)
    date_of_birth = serializers.DateField(required=True)
    address_line1 = serializers.CharField(required=True)
    address_line2 = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=True, max_length=100)
    state = serializers.CharField(required=True, max_length=100)
    pincode = serializers.CharField(required=True, max_length=10)
    country = serializers.CharField(default='India', max_length=100)
    referral_code = serializers.CharField(required=False, allow_blank=True)
    
    def validate_email(self, value):
        """Check if email already exists"""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered")
        return value
    
    def validate_mobile(self, value):
        """Check if mobile already exists"""
        if User.objects.filter(mobile=value).exists():
            raise serializers.ValidationError("Mobile number already registered")
        return value
    
    def validate(self, attrs):
        """Validate mobile number format"""
        mobile = attrs.get('mobile', '')
        if not mobile.isdigit() or len(mobile) < 10:
            raise serializers.ValidationError({"mobile": "Invalid mobile number format"})
        return attrs
    
    def create(self, validated_data):
        """Store signup data and send OTPs"""
        from datetime import date
        
        email = validated_data['email']
        mobile = validated_data['mobile']
        
        # Convert date_of_birth to string for JSON serialization
        signup_data = validated_data.copy()
        if 'date_of_birth' in signup_data and isinstance(signup_data['date_of_birth'], date):
            signup_data['date_of_birth'] = signup_data['date_of_birth'].isoformat()
        
        # Send OTP to both email and mobile
        send_email_otp(email)
        send_mobile_otp(mobile)
        
        # Store signup session in Redis
        signup_token = store_signup_session(email, mobile, signup_data)
        
        return {
            'message': 'OTP sent to email and mobile',
            'signup_token': signup_token
        }


class VerifySignupOTPSerializer(serializers.Serializer):
    """Serializer for verifying signup OTP"""
    signup_token = serializers.CharField(required=True)
    email_otp = serializers.CharField(required=True, max_length=10)
    mobile_otp = serializers.CharField(required=True, max_length=10)
    
    def validate(self, attrs):
        """Validate OTPs and signup token"""
        signup_token = attrs['signup_token']
        email_otp = attrs['email_otp']
        mobile_otp = attrs['mobile_otp']
        
        # Get signup session
        session_data = get_signup_session(signup_token)
        if not session_data:
            raise serializers.ValidationError("Invalid or expired signup token")
        
        email = session_data['email']
        mobile = session_data['mobile']
        
        # Verify both OTPs
        if not verify_otp(email, email_otp, 'email'):
            raise serializers.ValidationError({"email_otp": "Invalid or expired email OTP"})
        
        if not verify_otp(mobile, mobile_otp, 'mobile'):
            raise serializers.ValidationError({"mobile_otp": "Invalid or expired mobile OTP"})
        
        return attrs
    
    def create(self, validated_data):
        """Create user account after OTP verification"""
        signup_token = validated_data['signup_token']
        session_data = get_signup_session(signup_token)
        
        if not session_data:
            raise serializers.ValidationError("Invalid or expired signup token")
        
        signup_data = session_data['data']
        email = session_data['email']
        mobile = session_data['mobile']
        
        # Parse date_of_birth from string if needed
        from datetime import datetime
        date_of_birth = signup_data['date_of_birth']
        if isinstance(date_of_birth, str):
            date_of_birth = datetime.strptime(date_of_birth, '%Y-%m-%d').date()
        
        # Create user
        username = email or mobile
        user = User.objects.create(
            username=username,
            email=email,
            mobile=mobile,
            first_name=signup_data['first_name'],
            last_name=signup_data['last_name'],
            gender=signup_data['gender'],
            date_of_birth=date_of_birth,
            address_line1=signup_data['address_line1'],
            address_line2=signup_data.get('address_line2', ''),
            city=signup_data['city'],
            state=signup_data['state'],
            pincode=signup_data['pincode'],
            country=signup_data.get('country', 'India'),
            role='user'
        )
        
        # Handle referral
        referral_code = signup_data.get('referral_code')
        if referral_code:
            try:
                referrer = User.objects.get(referral_code=referral_code)
                user.referred_by = referrer
                user.save(update_fields=['referred_by'])
            except User.DoesNotExist:
                pass
        
        # Generate referral code
        generate_referral_code(user)
        
        # Delete signup session
        delete_signup_session(signup_token)
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        
        return {
            'user': user,
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        }


class CreateAdminSerializer(serializers.Serializer):
    """Serializer for creating admin user (superuser only)"""
    first_name = serializers.CharField(required=True, max_length=150)
    last_name = serializers.CharField(required=True, max_length=150)
    email = serializers.EmailField(required=True)
    mobile = serializers.CharField(required=True, max_length=15)
    gender = serializers.ChoiceField(choices=['male', 'female', 'other'], required=True)
    date_of_birth = serializers.DateField(required=True)
    address_line1 = serializers.CharField(required=True)
    address_line2 = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=True, max_length=100)
    state = serializers.CharField(required=True, max_length=100)
    pincode = serializers.CharField(required=True, max_length=10)
    country = serializers.CharField(default='India', max_length=100)
    
    def validate_email(self, value):
        """Check if email already exists"""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered")
        return value
    
    def validate_mobile(self, value):
        """Check if mobile already exists"""
        if User.objects.filter(mobile=value).exists():
            raise serializers.ValidationError("Mobile number already registered")
        return value
    
    def validate(self, attrs):
        """Validate mobile number format"""
        mobile = attrs.get('mobile', '')
        if not mobile.isdigit() or len(mobile) < 10:
            raise serializers.ValidationError({"mobile": "Invalid mobile number format"})
        return attrs
    
    def create(self, validated_data):
        """Create admin user"""
        email = validated_data['email']
        mobile = validated_data['mobile']
        username = email or mobile
        
        # Create admin user
        user = User.objects.create(
            username=username,
            email=email,
            mobile=mobile,
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            gender=validated_data['gender'],
            date_of_birth=validated_data['date_of_birth'],
            address_line1=validated_data['address_line1'],
            address_line2=validated_data.get('address_line2', ''),
            city=validated_data['city'],
            state=validated_data['state'],
            pincode=validated_data['pincode'],
            country=validated_data.get('country', 'India'),
            role='admin',
            is_staff=True,
            is_superuser=True
        )
        
        # Generate referral code
        generate_referral_code(user)
        
        # Send OTP to email and mobile for initial login
        send_email_otp(email)
        send_mobile_otp(mobile)
        
        return {
            'user': user,
            'message': 'Admin created successfully. OTP sent to email and mobile for initial login.'
        }


class CreateStaffSerializer(serializers.Serializer):
    """Serializer for creating staff user (admin or superuser)"""
    first_name = serializers.CharField(required=True, max_length=150)
    last_name = serializers.CharField(required=True, max_length=150)
    email = serializers.EmailField(required=True)
    mobile = serializers.CharField(required=True, max_length=15)
    gender = serializers.ChoiceField(choices=['male', 'female', 'other'], required=True)
    date_of_birth = serializers.DateField(required=True)
    address_line1 = serializers.CharField(required=True)
    address_line2 = serializers.CharField(required=False, allow_blank=True)
    city = serializers.CharField(required=True, max_length=100)
    state = serializers.CharField(required=True, max_length=100)
    pincode = serializers.CharField(required=True, max_length=10)
    country = serializers.CharField(default='India', max_length=100)
    
    def validate_email(self, value):
        """Check if email already exists"""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email already registered")
        return value
    
    def validate_mobile(self, value):
        """Check if mobile already exists"""
        if User.objects.filter(mobile=value).exists():
            raise serializers.ValidationError("Mobile number already registered")
        return value
    
    def validate(self, attrs):
        """Validate mobile number format"""
        mobile = attrs.get('mobile', '')
        if not mobile.isdigit() or len(mobile) < 10:
            raise serializers.ValidationError({"mobile": "Invalid mobile number format"})
        return attrs
    
    def create(self, validated_data):
        """Create staff user"""
        email = validated_data['email']
        mobile = validated_data['mobile']
        username = email or mobile
        
        # Create staff user
        user = User.objects.create(
            username=username,
            email=email,
            mobile=mobile,
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            gender=validated_data['gender'],
            date_of_birth=validated_data['date_of_birth'],
            address_line1=validated_data['address_line1'],
            address_line2=validated_data.get('address_line2', ''),
            city=validated_data['city'],
            state=validated_data['state'],
            pincode=validated_data['pincode'],
            country=validated_data.get('country', 'India'),
            role='staff',
            is_staff=True,
            is_superuser=False
        )
        
        # Generate referral code
        generate_referral_code(user)
        
        # Send OTP to email and mobile for initial login
        send_email_otp(email)
        send_mobile_otp(mobile)
        
        return {
            'user': user,
            'message': 'Staff created successfully. OTP sent to email and mobile for initial login.'
        }

