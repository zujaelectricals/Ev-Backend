"""
Razorpay client utility for initializing and managing Razorpay API client
"""
import razorpay
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

_client = None


def get_razorpay_client():
    """
    Get or create Razorpay client instance.
    Uses singleton pattern to reuse the same client instance.
    
    Returns:
        razorpay.Client: Configured Razorpay client instance
    
    Raises:
        ValueError: If RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET is not configured
    """
    global _client
    
    if _client is None:
        key_id = settings.RAZORPAY_KEY_ID
        key_secret = settings.RAZORPAY_KEY_SECRET
        
        if not key_id or not key_secret:
            raise ValueError(
                "Razorpay credentials not configured. "
                "Please set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET in environment variables."
            )
        
        _client = razorpay.Client(auth=(key_id, key_secret))
        logger.info("Razorpay client initialized successfully")
    
    return _client

