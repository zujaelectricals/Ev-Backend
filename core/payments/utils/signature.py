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


def verify_webhook_signature_smart(body, header_signature, event_type=None):
    """
    Verify Razorpay webhook signature with smart routing based on event type.
    
    Routes to appropriate webhook secret:
    - Payment events (payment.*, refund.*) → RAZORPAY_WEBHOOK_SECRET
    - Payout events (payout.*) → RAZORPAY_PAYOUT_WEBHOOK_SECRET
    
    Razorpay webhook signatures are generated using HMAC SHA256:
    signature = HMAC-SHA256(webhook_secret, body)
    
    Args:
        body (bytes or str): Raw request body from webhook
        header_signature (str): Signature from X-Razorpay-Signature header
        event_type (str, optional): Event type to determine which secret to use.
                                   If None, tries both secrets (less secure but more flexible)
    
    Returns:
        bool: True if signature is valid, False otherwise
    """
    try:
        # Determine which secret to use based on event type
        if event_type:
            if event_type.startswith('payout.'):
                webhook_secret = settings.RAZORPAY_PAYOUT_WEBHOOK_SECRET
                secret_name = 'RAZORPAY_PAYOUT_WEBHOOK_SECRET'
            elif event_type.startswith('payment.') or event_type.startswith('refund.'):
                webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
                secret_name = 'RAZORPAY_WEBHOOK_SECRET'
            else:
                # Unknown event type - try payment webhook secret first (default)
                logger.warning(f"Unknown event type '{event_type}', using RAZORPAY_WEBHOOK_SECRET")
                webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
                secret_name = 'RAZORPAY_WEBHOOK_SECRET'
        else:
            # No event type provided - try payment webhook secret (most common)
            logger.warning("No event_type provided, using RAZORPAY_WEBHOOK_SECRET")
            webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
            secret_name = 'RAZORPAY_WEBHOOK_SECRET'
        
        if not webhook_secret:
            logger.error(f"{secret_name} not configured")
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
            logger.warning(
                f"Invalid webhook signature using {secret_name} "
                f"(event_type={event_type or 'unknown'})"
            )
        
        return is_valid
    
    except Exception as e:
        logger.error(f"Error verifying webhook signature: {e}")
        return False

