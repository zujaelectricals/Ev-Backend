"""
Razorpay signature verification utilities
"""
import hmac
import hashlib
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def verify_payment_signature(order_id, payment_id, signature):
    """
    Verify Razorpay payment signature.
    
    Razorpay generates a signature using HMAC SHA256 with the following format:
    message = order_id + "|" + payment_id
    signature = HMAC-SHA256(key_secret, message)
    
    Args:
        order_id (str): Razorpay order ID
        payment_id (str): Razorpay payment ID
        signature (str): Signature to verify
    
    Returns:
        bool: True if signature is valid, False otherwise
    """
    try:
        key_secret = settings.RAZORPAY_KEY_SECRET
        
        if not key_secret:
            logger.error("RAZORPAY_KEY_SECRET not configured")
            return False
        
        # Create the message in the format: order_id|payment_id
        message = f"{order_id}|{payment_id}"
        
        # Generate expected signature
        expected_signature = hmac.new(
            key_secret.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Use constant-time comparison to prevent timing attacks
        is_valid = hmac.compare_digest(expected_signature, signature)
        
        if not is_valid:
            logger.warning(
                f"Invalid payment signature for order_id={order_id}, payment_id={payment_id}"
            )
        
        return is_valid
    
    except Exception as e:
        logger.error(f"Error verifying payment signature: {e}")
        return False


def verify_webhook_signature(body, header_signature):
    """
    Verify Razorpay webhook signature.
    
    Razorpay webhook signatures are generated using HMAC SHA256:
    signature = HMAC-SHA256(webhook_secret, body)
    
    Args:
        body (bytes or str): Raw request body from webhook
        header_signature (str): Signature from X-Razorpay-Signature header
    
    Returns:
        bool: True if signature is valid, False otherwise
    """
    try:
        webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
        
        if not webhook_secret:
            logger.error("RAZORPAY_WEBHOOK_SECRET not configured")
            return False
        
        # Ensure body is bytes
        if isinstance(body, str):
            body = body.encode('utf-8')
        
        # Generate expected signature
        expected_signature = hmac.new(
            webhook_secret.encode('utf-8'),
            body,
            hashlib.sha256
        ).hexdigest()
        
        # Use constant-time comparison to prevent timing attacks
        is_valid = hmac.compare_digest(expected_signature, header_signature)
        
        if not is_valid:
            logger.warning("Invalid webhook signature")
        
        return is_valid
    
    except Exception as e:
        logger.error(f"Error verifying webhook signature: {e}")
        return False

