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


def send_email_otp(email, otp_code=None, user=None, user_name=None):
    """
    Send OTP via email using MSG91.
    If otp_code is provided, use it; otherwise generate new one.
    user: Optional User object to extract name for MSG91 template
    user_name: Optional user name string (used if user is not provided)
    """
    # Validate email using MSG91 first
    # Note: 402 (insufficient balance) errors are allowed - validation returns True
    # to allow OTP sending to proceed even when validation service has billing issues
    is_valid, error_msg = validate_email_msg91(email)
    if not is_valid:
        raise ValueError(error_msg or "Invalid email address")
    
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
    
    # Extract user name if user object is provided, otherwise use user_name parameter
    final_user_name = user_name
    if not final_user_name and user:
        final_user_name = user.get_full_name() or (user.first_name or user.last_name)
        if not final_user_name:
            final_user_name = user.email.split("@")[0] if user.email else None
    
    # Print OTP to terminal for debugging
    print(f"Email OTP for {email}: {otp_code}")
    
    # Send OTP via MSG91
    success, error_msg = send_otp_via_msg91(email, otp_code, user_name=final_user_name)
    
    if not success:
        # If MSG91 fails, fallback to regular email (optional)
        # For now, raise error as per requirements
        raise ValueError(error_msg or "Failed to send OTP")
    
    return True


def send_sms_via_msg91(mobile, otp_code, user_name=None, company_name=None):
    """
    Send OTP via MSG91 SMS API
    Returns (success, error_message)
    """
    if not settings.MSG91_AUTH_KEY:
        logger.error("MSG91_AUTH_KEY is not configured in settings")
        return False, "MSG91 authentication key not configured. Please set MSG91_AUTH_KEY in environment variables."
    
    try:
        # MSG91 SMS API endpoint
        url = "https://control.msg91.com/api/v5/flow/"
        headers = {
            "Content-Type": "application/json",
            "authkey": settings.MSG91_AUTH_KEY
        }
        
        # Use company name from settings or default
        if not company_name:
            company_name = getattr(settings, 'MSG91_COMPANY_NAME', 'Company')
        
        # MSG91 SMS flow payload
        # Note: This assumes you have configured an SMS flow template in MSG91
        # You may need to adjust the payload structure based on your MSG91 SMS template configuration
        payload = {
            "flow_id": getattr(settings, 'MSG91_SMS_FLOW_ID', None),  # SMS Flow ID from MSG91 dashboard
            "sender": getattr(settings, 'MSG91_SMS_SENDER_ID', 'MSG91'),  # Sender ID
            "mobiles": mobile,
            "otp": str(otp_code),
            "company_name": company_name
        }
        
        # If flow_id is not configured, use the older SMS API endpoint
        if not payload.get("flow_id"):
            # Fallback to older MSG91 SMS API
            url = "https://control.msg91.com/api/sendotp.php"
            params = {
                "authkey": settings.MSG91_AUTH_KEY,
                "mobile": mobile,
                "message": f"Your OTP is {otp_code}. {company_name}",
                "sender": payload.get("sender", "MSG91"),
                "otp": otp_code
            }
            logger.info(f"MSG91 SMS OTP Send Request - Mobile: {mobile}")
            logger.debug(f"MSG91 SMS OTP Send Request Params: {params}")
            
            response = requests.get(url, params=params, timeout=10)
        else:
            logger.info(f"MSG91 SMS OTP Send Request - Mobile: {mobile}, User: {user_name}")
            logger.debug(f"MSG91 SMS OTP Send Request Payload: {json.dumps(payload, indent=2)}")
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
        
        # Handle 401 Unauthorized specifically
        if response.status_code == 401:
            error_msg = "MSG91 authentication failed. Please verify MSG91_AUTH_KEY is set correctly."
            logger.error(f"MSG91 SMS OTP Send 401 Unauthorized - Mobile: {mobile}, Auth Key Present: {bool(settings.MSG91_AUTH_KEY)}")
            try:
                error_data = response.json()
                logger.error(f"MSG91 SMS Error Response: {json.dumps(error_data, indent=2)}")
            except:
                logger.error(f"MSG91 SMS Error Response (raw): {response.text}")
            return False, error_msg
        
        response.raise_for_status()
        
        # For GET requests (older API), response might be text
        try:
            data = response.json()
        except:
            data = {"text": response.text}
        
        # Log the response
        logger.info(f"MSG91 SMS OTP Send Response - Mobile: {mobile}, Response: {json.dumps(data, indent=2)}")
        
        # Check if OTP was sent successfully
        # MSG91 SMS API returns different formats, check for success indicators
        if response.status_code == 200:
            # Check response content for success
            if isinstance(data, dict):
                if data.get("type") == "success" or data.get("status") == "success" or "success" in str(data).lower():
                    logger.info(f"MSG91 SMS OTP Send Success - Mobile: {mobile}")
                    return True, None
            elif isinstance(data, str) and "success" in data.lower():
                logger.info(f"MSG91 SMS OTP Send Success - Mobile: {mobile}")
                return True, None
            # If we get here, assume success for 200 status
            logger.info(f"MSG91 SMS OTP Send Success (200 status) - Mobile: {mobile}")
            return True, None
        else:
            errors = data.get("errors", {}) if isinstance(data, dict) else {}
            if errors:
                error_msg = str(errors)
            else:
                error_msg = "Failed to send SMS OTP"
            logger.warning(f"MSG91 SMS OTP Send Failed - Mobile: {mobile}, Errors: {errors}")
            return False, error_msg
            
    except requests.exceptions.RequestException as e:
        error_msg = f"Network error sending SMS OTP: {str(e)}"
        logger.error(f"MSG91 SMS OTP Send Network Error - Mobile: {mobile}, Error: {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Unexpected error sending SMS OTP: {str(e)}"
        logger.error(f"MSG91 SMS OTP Send Unexpected Error - Mobile: {mobile}, Error: {error_msg}")
        return False, error_msg


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
    
    # Extract user name if user object is provided, otherwise use user_name parameter
    final_user_name = user_name
    if not final_user_name and user:
        final_user_name = user.get_full_name() or (user.first_name or user.last_name)
        if not final_user_name:
            final_user_name = user.mobile if user.mobile else None
    
    # Send SMS via MSG91
    success, error_msg = send_sms_via_msg91(mobile, otp_code, user_name=final_user_name)
    
    if not success:
        # If MSG91 fails, log error but don't raise (to allow fallback behavior)
        logger.warning(f"Failed to send SMS OTP via MSG91 for {mobile}: {error_msg}")
        # Still return True as OTP is stored and can be verified
        # In production, you might want to raise an error here
    
    return True


def send_otp_dual_channel(user, otp_code=None):
    """
    Send OTP to both email and SMS simultaneously
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
    print(f"OTP SENT VIA DUAL CHANNEL")
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
    
    # Send email OTP if user has email
    if user.email:
        try:
            send_email_otp(user.email, otp_code, user=user)
            result['email']['success'] = True
        except Exception as e:
            error_msg = str(e)
            result['email']['error'] = error_msg
            logger.error(f"Failed to send email OTP to {user.email}: {error_msg}")
    
    # Send SMS OTP if user has mobile
    if user.mobile:
        try:
            send_mobile_otp(user.mobile, otp_code, user=user)
            result['sms']['success'] = True
        except Exception as e:
            error_msg = str(e)
            result['sms']['error'] = error_msg
            logger.error(f"Failed to send SMS OTP to {user.mobile}: {error_msg}")
    
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
        
        # Parse response data even if status code indicates error
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            # If response is not JSON, create a basic error structure
            data = {
                "status": "fail",
                "hasError": True,
                "errors": [f"HTTP {response.status_code}: {response.text[:200]}"]
            }
        
        # Log the response
        logger.info(f"MSG91 Email Validation Response - Email: {email}, Status: {response.status_code}, Response: {json.dumps(data, indent=2)}")
        
        # Handle HTTP errors (like 402 - insufficient balance)
        if not response.ok:
            # Extract error message from response
            errors = data.get("errors", [])
            if isinstance(errors, list) and len(errors) > 0:
                error_msg = errors[0] if isinstance(errors[0], str) else str(errors[0])
            elif isinstance(errors, dict):
                error_msg = str(errors)
            else:
                error_msg = f"HTTP {response.status_code}: Validation request failed"
            
            # Special handling for 402 - insufficient balance
            # For 402, we still return True to allow email sending to proceed
            # (validation balance issue shouldn't block email sending)
            if response.status_code == 402:
                logger.warning(
                    f"MSG91 email validation returned 402 (insufficient balance) - Email: {email}, "
                    f"Status: {response.status_code}, Error: {error_msg}. "
                    f"Proceeding with email send anyway."
                )
                # Return True with a warning message - allows email to be sent
                return True, f"insufficient_balance: {error_msg}"
            else:
                logger.warning(
                    f"MSG91 email validation HTTP error - Email: {email}, "
                    f"Status: {response.status_code}, Error: {error_msg}"
                )
            
            return False, error_msg
        
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
            errors = data.get("errors", [])
            if isinstance(errors, list) and len(errors) > 0:
                error_msg = errors[0] if isinstance(errors[0], str) else str(errors[0])
            elif isinstance(errors, dict):
                error_msg = str(errors)
            else:
                error_msg = "Validation failed"
            logger.warning(f"MSG91 Email Validation Error - Email: {email}, Errors: {errors}")
            return False, error_msg
            
    except requests.exceptions.Timeout:
        # On timeout, log but don't block (fail open for network issues)
        logger.error(f"MSG91 email validation timeout - Email: {email}")
        return True, None
    except requests.exceptions.ConnectionError:
        # On connection error, log but don't block (fail open for network issues)
        logger.error(f"MSG91 email validation connection error - Email: {email}")
        return True, None
    except Exception as e:
        # On other unexpected errors, log but don't block (fail open)
        logger.error(f"MSG91 email validation unexpected error - Email: {email}, Error: {str(e)}", exc_info=True)
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

