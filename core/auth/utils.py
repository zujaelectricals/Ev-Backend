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


def generate_otp(length=6):
    """Generate a random OTP"""
    return ''.join(random.choices(string.digits, k=length))


def send_email_otp(email, otp_code=None, user=None, user_name=None):
    """
    Send OTP via email using MSG91.
    If otp_code is provided, use it; otherwise generate new one.
    user: Optional User object to extract name for MSG91 template
    user_name: Optional user name string (used if user is not provided)
    """
    # Validate email using MSG91 first
    is_valid, error_msg = validate_email_msg91(email)
    if not is_valid:
        raise ValueError(error_msg or "Invalid email address")
    
    if otp_code is None:
        otp_code = generate_otp(settings.OTP_LENGTH)
    
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
    
    # Extract user name if user object is provided, otherwise use user_name parameter
    final_user_name = user_name
    if not final_user_name and user:
        final_user_name = user.get_full_name() or (user.first_name or user.last_name)
        if not final_user_name:
            final_user_name = user.email.split("@")[0] if user.email else None
    
    # Send OTP via MSG91
    success, error_msg = send_otp_via_msg91(email, otp_code, user_name=final_user_name)
    
    if not success:
        # If MSG91 fails, fallback to regular email (optional)
        # For now, raise error as per requirements
        raise ValueError(error_msg or "Failed to send OTP")
    
    return True


def send_mobile_otp(mobile, otp_code=None):
    """Send OTP via SMS. If otp_code is provided, use it; otherwise generate new one."""
    if otp_code is None:
        otp_code = generate_otp(settings.OTP_LENGTH)
    
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
    
    # Send SMS (integrate with SMS provider)
    # For now, just log it
    print(f"SMS OTP for {mobile}: {otp_code}")
    # TODO: Integrate with actual SMS provider
    # sms_provider.send_sms(mobile, f"Your OTP is: {otp_code}")
    
    return True


def verify_otp(identifier, otp_code, otp_type):
    """Verify OTP from Redis or Database"""
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


def validate_email_msg91(email):
    """
    Validate email using MSG91 API
    Returns (is_valid, error_message)
    """
    if not settings.MSG91_AUTH_KEY:
        # If MSG91 is not configured, skip validation
        return True, None
    
    try:
        url = "https://control.msg91.com/api/v5/email/validate"
        headers = {
            "Content-Type": "application/json",
            "authkey": settings.MSG91_AUTH_KEY
        }
        payload = {
            "email": email
        }
        
        logger.info(f"MSG91 Email Validation Request - Email: {email}")
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Log the response
        logger.info(f"MSG91 Email Validation Response - Email: {email}, Response: {json.dumps(data, indent=2)}")
        
        # Check if validation was successful
        if data.get("status") == "success" and data.get("hasError") == False:
            result = data.get("data", {}).get("result", {})
            if result.get("valid") == True:
                logger.info(f"MSG91 Email Validation Success - Email: {email}")
                return True, None
            else:
                logger.warning(f"MSG91 Email Validation Failed - Email: {email}, Result: {result}")
                return False, "Invalid email address"
        else:
            # Extract error message if available
            errors = data.get("errors", {})
            if errors:
                error_msg = str(errors)
            else:
                error_msg = "Invalid email address"
            logger.warning(f"MSG91 Email Validation Error - Email: {email}, Errors: {errors}")
            return False, error_msg
            
    except requests.exceptions.RequestException as e:
        # On network errors, log but don't block (fail open)
        logger.error(f"MSG91 email validation network error - Email: {email}, Error: {str(e)}")
        return True, None
    except Exception as e:
        logger.error(f"MSG91 email validation unexpected error - Email: {email}, Error: {str(e)}")
        return True, None


def send_otp_via_msg91(email, otp_code, user_name=None, company_name=None):
    """
    Send OTP via MSG91 campaign API
    Returns (success, error_message)
    """
    if not settings.MSG91_AUTH_KEY:
        logger.error("MSG91_AUTH_KEY is not configured in settings")
        return False, "MSG91 authentication key not configured. Please set MSG91_AUTH_KEY in environment variables."
    
    try:
        url = "https://control.msg91.com/api/v5/campaign/api/campaigns/otp/run"
        headers = {
            "Content-Type": "application/json",
            "authkey": settings.MSG91_AUTH_KEY
        }
        
        # Use provided name or default to first part of email
        if not user_name:
            user_name = email.split("@")[0]
        
        # Use company name from settings or default
        if not company_name:
            company_name = settings.MSG91_COMPANY_NAME
        
        payload = {
            "data": {
                "sendTo": [
                    {
                        "to": [
                            {
                                "name": user_name,
                                "email": email
                            }
                        ],
                        "variables": {
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
        
        logger.info(f"MSG91 OTP Send Request - Email: {email}, User: {user_name}")
        logger.debug(f"MSG91 OTP Send Request Payload: {json.dumps(payload, indent=2)}")
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        # Handle 401 Unauthorized specifically
        if response.status_code == 401:
            error_msg = "MSG91 authentication failed. Please verify MSG91_AUTH_KEY is set correctly in production environment."
            logger.error(f"MSG91 OTP Send 401 Unauthorized - Email: {email}, Auth Key Present: {bool(settings.MSG91_AUTH_KEY)}")
            try:
                error_data = response.json()
                logger.error(f"MSG91 Error Response: {json.dumps(error_data, indent=2)}")
            except:
                logger.error(f"MSG91 Error Response (raw): {response.text}")
            return False, error_msg
        
        response.raise_for_status()
        data = response.json()
        
        # Log the response
        logger.info(f"MSG91 OTP Send Response - Email: {email}, Response: {json.dumps(data, indent=2)}")
        
        # Check if OTP was sent successfully
        if data.get("status") == "success" or response.status_code == 200:
            logger.info(f"MSG91 OTP Send Success - Email: {email}")
            return True, None
        else:
            errors = data.get("errors", {})
            if errors:
                error_msg = str(errors)
            else:
                error_msg = "Failed to send OTP"
            logger.warning(f"MSG91 OTP Send Failed - Email: {email}, Errors: {errors}")
            return False, error_msg
            
    except requests.exceptions.RequestException as e:
        error_msg = f"Network error sending OTP: {str(e)}"
        logger.error(f"MSG91 OTP Send Network Error - Email: {email}, Error: {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected error sending OTP: {str(e)}"
        logger.error(f"MSG91 OTP Send Unexpected Error - Email: {email}, Error: {error_msg}")
        return False, error_msg


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

