import time
from django.conf import settings
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from rest_framework_simplejwt.tokens import RefreshToken
from .utils import (
    send_email_otp, send_mobile_otp, verify_otp, generate_referral_code,
    generate_otp, store_signup_session, get_signup_session, delete_signup_session
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
        
        # Check if user exists and has both email and mobile registered
        user = None
        try:
            if otp_type == 'email':
                user = User.objects.get(email=identifier)
            else:
                user = User.objects.get(mobile=identifier)
        except User.DoesNotExist:
            user = None
        
        # If user exists and has both email and mobile, send OTP to both
        if user and user.email and user.mobile:
            # Generate single OTP code for both channels
            otp_code = generate_otp(settings.OTP_LENGTH)
            
            # Send to both channels with the same OTP
            send_email_otp(user.email, otp_code)
            send_mobile_otp(user.mobile, otp_code)
            
            return {
                'message': f'OTP sent to both email ({user.email}) and mobile ({user.mobile})',
                'sent_to': ['email', 'mobile']
            }
        else:
            # User doesn't exist or doesn't have both channels - send to requested channel only
            if otp_type == 'email':
                send_email_otp(identifier)
                return {'message': f'OTP sent to {identifier}'}
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
        
        # Get or create user with proper error handling
        user = None
        created = False
        
        if otp_type == 'email':
            # First try to get user by email
            try:
                user = User.objects.get(email=identifier)
            except User.DoesNotExist:
                # If not found by email, try by username
                try:
                    user = User.objects.get(username=identifier)
                    # Update email if it's different and not already taken
                    if user.email != identifier:
                        # Check if email is already taken by another user
                        if not User.objects.filter(email=identifier).exclude(pk=user.pk).exists():
                            user.email = identifier
                            user.save(update_fields=['email'])
                except User.DoesNotExist:
                    # Create user with retry logic - try to create directly and handle conflicts
                    username = identifier
                    counter = 1
                    max_retries = 20
                    
                    for attempt in range(max_retries):
                        try:
                            # Try to create user directly - let database handle uniqueness
                            user = User.objects.create(
                                username=username,
                                email=identifier
                            )
                            created = True
                            break
                        except IntegrityError as e:
                            error_msg = str(e).lower()
                            # Check if it's a username conflict
                            if 'username' in error_msg or 'unique constraint' in error_msg:
                                # Try next available username
                                counter += 1
                                username = f"{identifier}_{counter}"
                                if attempt == max_retries - 1:
                                    # Last attempt failed, try one more with timestamp
                                    username = f"{identifier}_{int(time.time())}"
                                    try:
                                        user = User.objects.create(
                                            username=username,
                                            email=identifier
                                        )
                                        created = True
                                        break
                                    except IntegrityError:
                                        raise serializers.ValidationError(
                                            "Unable to create user account. Please contact support."
                                        )
                                continue
                            # If it's an email conflict, user might exist - try to get it
                            elif 'email' in error_msg:
                                try:
                                    user = User.objects.get(email=identifier)
                                    break
                                except User.DoesNotExist:
                                    raise serializers.ValidationError(
                                        "Email is already registered with a different account."
                                    )
                            else:
                                # Some other integrity error
                                raise serializers.ValidationError(
                                    f"Unable to create user account: {str(e)}"
                                )
                    
                    if not created and user is None:
                        raise serializers.ValidationError("Unable to create user. Please try again.")
        else:
            # First try to get user by mobile
            try:
                user = User.objects.get(mobile=identifier)
            except User.DoesNotExist:
                # If not found by mobile, try by username
                try:
                    user = User.objects.get(username=identifier)
                    # Update mobile if it's different and not already taken
                    if user.mobile != identifier:
                        # Check if mobile is already taken by another user
                        if not User.objects.filter(mobile=identifier).exclude(pk=user.pk).exists():
                            user.mobile = identifier
                            user.save(update_fields=['mobile'])
                except User.DoesNotExist:
                    # Create user with retry logic - try to create directly and handle conflicts
                    username = identifier
                    counter = 1
                    max_retries = 20
                    
                    for attempt in range(max_retries):
                        try:
                            # Try to create user directly - let database handle uniqueness
                            user = User.objects.create(
                                username=username,
                                mobile=identifier
                            )
                            created = True
                            break
                        except IntegrityError as e:
                            error_msg = str(e).lower()
                            # Check if it's a username conflict
                            if 'username' in error_msg or 'unique constraint' in error_msg:
                                # Try next available username
                                counter += 1
                                username = f"{identifier}_{counter}"
                                if attempt == max_retries - 1:
                                    # Last attempt failed, try one more with timestamp
                                    username = f"{identifier}_{int(time.time())}"
                                    try:
                                        user = User.objects.create(
                                            username=username,
                                            mobile=identifier
                                        )
                                        created = True
                                        break
                                    except IntegrityError:
                                        raise serializers.ValidationError(
                                            "Unable to create user account. Please contact support."
                                        )
                                continue
                            # If it's a mobile conflict, user might exist - try to get it
                            elif 'mobile' in error_msg:
                                try:
                                    user = User.objects.get(mobile=identifier)
                                    break
                                except User.DoesNotExist:
                                    raise serializers.ValidationError(
                                        "Mobile number is already registered with a different account."
                                    )
                            else:
                                # Some other integrity error
                                raise serializers.ValidationError(
                                    f"Unable to create user account: {str(e)}"
                                )
                    
                    if not created and user is None:
                        raise serializers.ValidationError("Unable to create user. Please try again.")
        
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
        
        # Generate single OTP code for both channels
        otp_code = generate_otp(settings.OTP_LENGTH)
        
        # Send same OTP to both email and mobile
        send_email_otp(email, otp_code)
        send_mobile_otp(mobile, otp_code)
        
        # Store signup session in Redis
        signup_token = store_signup_session(email, mobile, signup_data)
        
        return {
            'message': 'OTP sent to both email and mobile',
            'signup_token': signup_token
        }


class VerifySignupOTPSerializer(serializers.Serializer):
    """Serializer for verifying signup OTP"""
    signup_token = serializers.CharField(required=True)
    otp_code = serializers.CharField(required=True, max_length=10)
    
    def validate(self, attrs):
        """Validate OTP and signup token"""
        signup_token = attrs['signup_token']
        otp_code = attrs['otp_code']
        
        # Get signup session
        session_data = get_signup_session(signup_token)
        if not session_data:
            raise serializers.ValidationError("Invalid or expired signup token")
        
        email = session_data['email']
        mobile = session_data['mobile']
        
        # Verify OTP - check if it matches either email or mobile OTP
        # Since same OTP is sent to both, we check both but only need one to match
        email_valid = verify_otp(email, otp_code, 'email')
        mobile_valid = verify_otp(mobile, otp_code, 'mobile')
        
        if not email_valid and not mobile_valid:
            raise serializers.ValidationError({"otp_code": "Invalid or expired OTP"})
        
        # If one channel's OTP was valid but the other wasn't, mark the other as used too
        # This ensures both OTP records are properly marked as used
        if email_valid and not mobile_valid:
            # Email OTP was valid, mark mobile OTP as used if it exists
            from core.auth.models import OTP
            mobile_otp_obj = OTP.objects.filter(
                identifier=mobile,
                otp_type='mobile',
                otp_code=otp_code,
                is_used=False
            ).first()
            if mobile_otp_obj:
                mobile_otp_obj.mark_as_used()
        elif mobile_valid and not email_valid:
            # Mobile OTP was valid, mark email OTP as used if it exists
            from core.auth.models import OTP
            email_otp_obj = OTP.objects.filter(
                identifier=email,
                otp_type='email',
                otp_code=otp_code,
                is_used=False
            ).first()
            if email_otp_obj:
                email_otp_obj.mark_as_used()
        
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
        
        return {
            'user': user,
            'message': 'Admin created successfully. Admin can login using /api/auth/send-otp/ endpoint.'
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
        
        return {
            'user': user,
            'message': 'Staff created successfully. Staff can login using /api/auth/send-otp/ endpoint.'
        }

