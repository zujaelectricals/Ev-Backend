"""
RazorpayX payout webhook signature verification utilities
"""
import hmac
import hashlib
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def verify_payout_webhook_signature(body, header_signature):
    """
    Verify RazorpayX payout webhook signature.
    
    RazorpayX webhook signatures are generated using HMAC SHA256:
    signature = HMAC-SHA256(webhook_secret, body)
    
    Args:
        body (bytes or str): Raw request body from webhook
        header_signature (str): Signature from X-Razorpay-Signature header
    
    Returns:
        bool: True if signature is valid, False otherwise
    """
    try:
        webhook_secret = settings.RAZORPAY_PAYOUT_WEBHOOK_SECRET
        
        if not webhook_secret:
            logger.error("RAZORPAY_PAYOUT_WEBHOOK_SECRET not configured")
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
            logger.warning("Invalid payout webhook signature")
        
        return is_valid
    
    except Exception as e:
        logger.error(f"Error verifying payout webhook signature: {e}")
        return False

