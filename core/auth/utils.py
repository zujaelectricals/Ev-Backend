import random
import string
import json
import logging
import requests
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from .models import OTP

logger = logging.getLogger(__name__)

# Dummy user configuration
DUMMY_USER_EMAIL = 'testuser@gmail.com'
DUMMY_USER_OTP = '123456'


def generate_otp(length=6):
    """Generate a random OTP"""
    return ''.join(random.choices(string.digits, k=length))


def format_indian_mobile(mobile):
    """
    Format mobile number to Indian format: 91XXXXXXXXXX (12 digits, no + prefix).
    Accepts 10-digit numbers or numbers already prefixed with 91 or +91.
    Returns the formatted mobile string, or None if invalid.
    """
    if not mobile:
        return None
    digits = ''.join(filter(str.isdigit, str(mobile)))
    if len(digits) == 10:
        return f"91{digits}"
    elif len(digits) == 12 and digits.startswith('91'):
        return digits
    else:
        logger.warning(f"Unexpected mobile number format: {mobile}. Expected 10-digit Indian number.")
        return None


def send_otp_via_msg91_unified(otp_code, email=None, mobile=None, user_name=None, company_name=None):
    """
    Send OTP via MSG91 unified SMS + Email campaign API.
    Endpoint: POST https://control.msg91.com/api/v5/campaign/api/campaigns/sms-and-email/run
    At least one of email or mobile must be provided.
    Mobile must be a 10-digit Indian number; it will be formatted as 91XXXXXXXXXX.
    Returns (success, error_message)
    """
    if not settings.MSG91_AUTH_KEY:
        logger.error("MSG91_AUTH_KEY is not configured in settings")
        return False, "MSG91 authentication key not configured. Please set MSG91_AUTH_KEY in environment variables."

    if not email and not mobile:
        return False, "At least one of email or mobile must be provided."

    try:
        url = "https://control.msg91.com/api/v5/campaign/api/campaigns/sms-and-email/run"
        headers = {
            "Content-Type": "application/json",
            "authkey": settings.MSG91_AUTH_KEY
        }

        # Resolve company name
        if not company_name:
            company_name = getattr(settings, 'MSG91_COMPANY_NAME', 'Company')

        # Resolve user name
        if not user_name:
            if email:
                user_name = email.split("@")[0]
            else:
                user_name = "User"

        # Format mobile for Indian numbers (91XXXXXXXXXX, no +)
        formatted_mobile = format_indian_mobile(mobile)

        # Build the recipient object
        recipient = {
            "name": user_name,
            "variables": {
                "numeric": {
                    "type": "text",
                    "value": str(otp_code)
                }
            }
        }
        if email:
            recipient["email"] = email
        if formatted_mobile:
            recipient["mobiles"] = formatted_mobile

        payload = {
            "data": {
                "sendTo": [
                    {
                        "to": [recipient],
                        "variables": {
                            "numeric": {
                                "type": "text",
                                "value": str(otp_code)
                            },
                            "company_name": {
                                "type": "text",
                                "value": company_name
                            },
                            "otp": {
                                "type": "text",
                                "value": str(otp_code)
                            }
                        }
                    }
                ]
            }
        }

        logger.info(f"MSG91 OTP Send Request - Email: {email}, Mobile: {formatted_mobile}, User: {user_name}")
        logger.debug(f"MSG91 OTP Send Request Payload: {json.dumps(payload, indent=2)}")

        response = requests.post(url, json=payload, headers=headers, timeout=10)

        # Handle 401 Unauthorized specifically
        if response.status_code == 401:
            error_msg = "MSG91 authentication failed. Please verify MSG91_AUTH_KEY is set correctly."
            logger.error(f"MSG91 OTP Send 401 Unauthorized - Auth Key Present: {bool(settings.MSG91_AUTH_KEY)}")
            try:
                error_data = response.json()
                logger.error(f"MSG91 Error Response: {json.dumps(error_data, indent=2)}")
            except Exception:
                logger.error(f"MSG91 Error Response (raw): {response.text}")
            return False, error_msg

        response.raise_for_status()

        try:
            data = response.json()
        except Exception:
            data = {"text": response.text}

        logger.info(f"MSG91 OTP Send Response - Email: {email}, Mobile: {formatted_mobile}, Response: {json.dumps(data, indent=2)}")

        if response.status_code == 200:
            logger.info(f"MSG91 OTP Send Success - Email: {email}, Mobile: {formatted_mobile}")
            return True, None
        else:
            errors = data.get("errors", {}) if isinstance(data, dict) else {}
            error_msg = str(errors) if errors else "Failed to send OTP"
            logger.warning(f"MSG91 OTP Send Failed - Email: {email}, Mobile: {formatted_mobile}, Errors: {errors}")
            return False, error_msg

    except requests.exceptions.RequestException as e:
        error_msg = f"Network error sending OTP: {str(e)}"
        logger.error(f"MSG91 OTP Send Network Error - Email: {email}, Mobile: {mobile}, Error: {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected error sending OTP: {str(e)}"
        logger.error(f"MSG91 OTP Send Unexpected Error - Email: {email}, Mobile: {mobile}, Error: {error_msg}")
        return False, error_msg


def send_email_otp(email, otp_code=None, user=None, user_name=None):
    """
    Send OTP via email using MSG91.
    If otp_code is provided, use it; otherwise generate new one.
    user: Optional User object to extract name for MSG91 template
    user_name: Optional user name string (used if user is not provided)
    """
    if otp_code is None:
        otp_code = generate_otp(settings.OTP_LENGTH)

    # Print OTP to terminal
    print(f"\n{'='*60}")
    print(f"OTP SENT VIA EMAIL")
    print(f"{'='*60}")
    print(f"Email: {email}")
    print(f"OTP Code: {otp_code}")
    print(f"{'='*60}\n")

    # Store OTP in Redis with expiry
    cache_key = f"otp:email:{email}"
    cache.set(cache_key, otp_code, timeout=settings.OTP_EXPIRY_MINUTES * 60)

    # Also store in database
    expires_at = timezone.now() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
    OTP.objects.create(
        identifier=email,
        otp_type='email',
        otp_code=otp_code,
        expires_at=expires_at
    )

    # Extract user name and mobile if user object is provided
    final_user_name = user_name
    user_mobile = None
    if user:
        if not final_user_name:
            final_user_name = user.get_full_name() or (user.first_name or user.last_name)
            if not final_user_name:
                final_user_name = user.email.split("@")[0] if user.email else None
        user_mobile = getattr(user, 'mobile', None) or None

    print(f"Email OTP for {email}: {otp_code}")

    # Send OTP via MSG91 unified endpoint (include mobile if available on user)
    success, error_msg = send_otp_via_msg91_unified(
        otp_code,
        email=email,
        mobile=user_mobile,
        user_name=final_user_name
    )

    if not success:
        raise ValueError(error_msg or "Failed to send OTP")

    return True


def send_mobile_otp(mobile, otp_code=None, user=None, user_name=None):
    """
    Send OTP via SMS using MSG91.
    If otp_code is provided, use it; otherwise generate new one.
    user: Optional User object to extract name for MSG91 template
    user_name: Optional user name string (used if user is not provided)
    """
    if otp_code is None:
        otp_code = generate_otp(settings.OTP_LENGTH)

    # Print OTP to terminal
    print(f"\n{'='*60}")
    print(f"OTP SENT VIA SMS")
    print(f"{'='*60}")
    print(f"Mobile: {mobile}")
    print(f"OTP Code: {otp_code}")
    print(f"{'='*60}\n")

    # Store OTP in Redis with expiry
    cache_key = f"otp:mobile:{mobile}"
    cache.set(cache_key, otp_code, timeout=settings.OTP_EXPIRY_MINUTES * 60)

    # Also store in database
    expires_at = timezone.now() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)
    OTP.objects.create(
        identifier=mobile,
        otp_type='mobile',
        otp_code=otp_code,
        expires_at=expires_at
    )

    # Extract user name and email if user object is provided
    final_user_name = user_name
    user_email = None
    if user:
        if not final_user_name:
            final_user_name = user.get_full_name() or (user.first_name or user.last_name)
            if not final_user_name:
                final_user_name = user.mobile if user.mobile else None
        user_email = getattr(user, 'email', None) or None

    # Send SMS via MSG91 unified endpoint (include email if available on user)
    success, error_msg = send_otp_via_msg91_unified(
        otp_code,
        email=user_email,
        mobile=mobile,
        user_name=final_user_name
    )

    if not success:
        logger.warning(f"Failed to send SMS OTP via MSG91 for {mobile}: {error_msg}")

    return True


def send_otp_dual_channel(user, otp_code=None):
    """
    Send OTP to both email and SMS in a single MSG91 API call.
    Returns dict with success status for both channels:
    {
        'email': {'success': bool, 'error': str or None},
        'sms': {'success': bool, 'error': str or None},
        'otp_code': str
    }
    """
    if otp_code is None:
        otp_code = generate_otp(settings.OTP_LENGTH)

    # Print OTP to terminal
    print(f"\n{'='*60}")
    print(f"OTP SENT VIA DUAL CHANNEL (SMS + EMAIL)")
    print(f"{'='*60}")
    print(f"OTP Code: {otp_code}")
    if user.email:
        print(f"Email: {user.email}")
    if user.mobile:
        print(f"Mobile: {user.mobile}")
    print(f"{'='*60}\n")

    result = {
        'email': {'success': False, 'error': None},
        'sms': {'success': False, 'error': None},
        'otp_code': otp_code
    }

    expires_at = timezone.now() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)

    # Store OTP in Redis and DB for email channel
    if user.email:
        cache.set(f"otp:email:{user.email}", otp_code, timeout=settings.OTP_EXPIRY_MINUTES * 60)
        OTP.objects.create(
            identifier=user.email,
            otp_type='email',
            otp_code=otp_code,
            expires_at=expires_at
        )

    # Store OTP in Redis and DB for mobile channel
    if user.mobile:
        cache.set(f"otp:mobile:{user.mobile}", otp_code, timeout=settings.OTP_EXPIRY_MINUTES * 60)
        OTP.objects.create(
            identifier=user.mobile,
            otp_type='mobile',
            otp_code=otp_code,
            expires_at=expires_at
        )

    # Resolve user name
    user_name = user.get_full_name() or (user.first_name or user.last_name)
    if not user_name:
        user_name = user.email.split("@")[0] if user.email else (user.mobile or "User")

    # Single unified MSG91 API call for both email and SMS
    try:
        success, error_msg = send_otp_via_msg91_unified(
            otp_code,
            email=user.email if user.email else None,
            mobile=user.mobile if user.mobile else None,
            user_name=user_name
        )
        if success:
            if user.email:
                result['email']['success'] = True
            if user.mobile:
                result['sms']['success'] = True
        else:
            if user.email:
                result['email']['error'] = error_msg
            if user.mobile:
                result['sms']['error'] = error_msg
            logger.error(f"MSG91 dual channel OTP send failed: {error_msg}")
    except Exception as e:
        error_msg = str(e)
        if user.email:
            result['email']['error'] = error_msg
        if user.mobile:
            result['sms']['error'] = error_msg
        logger.error(f"Dual channel OTP send exception: {error_msg}")

    # At least one channel should succeed
    if not result['email']['success'] and not result['sms']['success']:
        raise ValueError("Failed to send OTP via both email and SMS channels")

    return result


def ensure_dummy_user():
    """Ensure dummy user exists with all required fields"""
    from core.users.models import User
    
    dummy_user, created = User.objects.get_or_create(
        email=DUMMY_USER_EMAIL,
        defaults={
            'username': DUMMY_USER_EMAIL,
            'first_name': 'Test',
            'last_name': 'User',
            'role': 'user',
            'is_distributor': False,
            'is_active_buyer': False,
            'is_staff': False,
            'is_superuser': False,
            'country': 'India',
        }
    )
    
    # Update username if it doesn't match email (for existing users)
    if dummy_user.username != DUMMY_USER_EMAIL:
        dummy_user.username = DUMMY_USER_EMAIL
        dummy_user.save(update_fields=['username'])
    
    # Generate referral code if user doesn't have one
    if not dummy_user.referral_code:
        generate_referral_code(dummy_user)
    
    return dummy_user


def verify_otp(identifier, otp_code, otp_type):
    """Verify OTP from Redis or Database"""
    # Check for dummy user first
    if identifier == DUMMY_USER_EMAIL and otp_code == DUMMY_USER_OTP and otp_type == 'email':
        # Ensure dummy user exists
        ensure_dummy_user()
        return True
    
    # First check Redis
    cache_key = f"otp:{otp_type}:{identifier}"
    cached_otp = cache.get(cache_key)
    
    if cached_otp and cached_otp == otp_code:
        # Valid OTP found in cache, delete it
        cache.delete(cache_key)
        
        # Mark as used in database
        otp_obj = OTP.objects.filter(
            identifier=identifier,
            otp_type=otp_type,
            otp_code=otp_code,
            is_used=False
        ).first()
        
        if otp_obj:
            otp_obj.mark_as_used()
        
        return True
    
    # Check database as fallback
    otp_obj = OTP.objects.filter(
        identifier=identifier,
        otp_type=otp_type,
        otp_code=otp_code,
        is_used=False
    ).first()
    
    if otp_obj and otp_obj.is_valid():
        otp_obj.mark_as_used()
        cache.delete(cache_key)
        return True
    
    return False




def generate_referral_code(user):
    """Generate unique referral code for user"""
    from core.users.models import User
    
    # Try to generate a unique code
    max_attempts = 10
    for _ in range(max_attempts):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        if not User.objects.filter(referral_code=code).exists():
            user.referral_code = code
            user.save(update_fields=['referral_code'])
            return code
    
    # Fallback: use user ID
    code = f"REF{user.id:06d}"
    user.referral_code = code
    user.save(update_fields=['referral_code'])
    return code


def ensure_company_referral_user(company_referral_code):
    """
    Ensure a superadmin user exists with the company referral code.
    Returns the user with the company referral code.
    """
    from core.users.models import User
    
    # First, try to find an existing user with this referral code
    try:
        company_user = User.objects.get(referral_code=company_referral_code)
        # If found, ensure it's a superadmin
        if not company_user.is_superuser:
            company_user.is_superuser = True
            company_user.is_staff = True
            company_user.role = 'admin'
            company_user.save(update_fields=['is_superuser', 'is_staff', 'role'])
        return company_user
    except User.DoesNotExist:
        # Create a new superadmin user with the company referral code
        # Use a default username/email for the company user
        username = f"company_{company_referral_code.lower()}"
        email = f"company@{company_referral_code.lower()}.local"
        
        # Check if username or email already exists, adjust if needed
        base_username = username
        base_email = email
        counter = 1
        while User.objects.filter(username=username).exists() or User.objects.filter(email=email).exists():
            username = f"{base_username}{counter}"
            email = f"company{counter}@{company_referral_code.lower()}.local"
            counter += 1
        
        company_user = User.objects.create(
            username=username,
            email=email,
            first_name='Company',
            last_name='Admin',
            role='admin',
            is_staff=True,
            is_superuser=True,
            referral_code=company_referral_code
        )
        return company_user


def store_signup_session(email, mobile, signup_data, expiry_minutes=15):
    """Store signup session data in Redis"""
    signup_token = ''.join(random.choices(string.ascii_uppercase + string.digits, k=32))
    cache_key = f"signup:{signup_token}"
    
    session_data = {
        'email': email,
        'mobile': mobile,
        'data': signup_data
    }
    
    cache.set(cache_key, json.dumps(session_data), timeout=expiry_minutes * 60)
    return signup_token


def get_signup_session(signup_token):
    """Retrieve signup session data from Redis"""
    cache_key = f"signup:{signup_token}"
    session_data = cache.get(cache_key)
    
    if session_data:
        return json.loads(session_data)
    return None


def delete_signup_session(signup_token):
    """Delete signup session from Redis"""
    cache_key = f"signup:{signup_token}"
    cache.delete(cache_key)

