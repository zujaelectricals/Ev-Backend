import random
import string
import json
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from .models import OTP


def generate_otp(length=6):
    """Generate a random OTP"""
    return ''.join(random.choices(string.digits, k=length))


def send_email_otp(email, otp_code=None):
    """Send OTP via email. If otp_code is provided, use it; otherwise generate new one."""
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
    
    # Print OTP to terminal (for development)
    print("\n" + "="*60)
    print(f"EMAIL OTP for {email}: {otp_code}")
    print(f"This code will expire in {settings.OTP_EXPIRY_MINUTES} minutes.")
    print("="*60 + "\n")
    
    # Try to send email (optional - will fail gracefully if SMTP not configured)
    subject = 'Your EV Distribution Platform OTP'
    message = f'Your OTP code is: {otp_code}\n\nThis code will expire in {settings.OTP_EXPIRY_MINUTES} minutes.'
    
    try:
        send_mail(
            subject,
            message,
            settings.EMAIL_HOST_USER,
            [email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        # Email sending failed, but OTP is already printed to terminal
        # This is expected in development when SMTP is not configured
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

