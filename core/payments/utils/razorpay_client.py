"""
Razorpay client utility for initializing and managing Razorpay API client
"""
import razorpay
from django.conf import settings
import logging
import functools
import requests

logger = logging.getLogger(__name__)

_client = None

# Timeout configuration for Razorpay API calls (in seconds)
# Connect timeout: time to establish connection (increased for first connection)
# Read timeout: time to wait for response after connection
# Increased defaults to handle cold start scenarios (DNS resolution, SSL handshake)
# Read timeout increased to 60s to handle slow Razorpay API responses during peak times
RAZORPAY_CONNECT_TIMEOUT = getattr(settings, 'RAZORPAY_CONNECT_TIMEOUT', 15)
RAZORPAY_READ_TIMEOUT = getattr(settings, 'RAZORPAY_READ_TIMEOUT', 60)
RAZORPAY_TIMEOUT = (RAZORPAY_CONNECT_TIMEOUT, RAZORPAY_READ_TIMEOUT)


def _add_timeout_to_request(original_request_method):
    """
    Wrapper function to add default timeout to requests.Session request methods.
    The requests library doesn't support default timeout on Session, so we wrap
    the request methods to inject timeout if not provided.
    """
    @functools.wraps(original_request_method)
    def wrapper(*args, **kwargs):
        # Only add timeout if not explicitly provided
        # This ensures we don't override explicit timeouts but add defaults for all requests
        if 'timeout' not in kwargs:
            kwargs['timeout'] = RAZORPAY_TIMEOUT
            logger.debug(
                f"Added timeout {RAZORPAY_TIMEOUT} to Razorpay API request: "
                f"method={getattr(original_request_method, '__name__', 'unknown')}"
            )
        return original_request_method(*args, **kwargs)
    return wrapper


def get_razorpay_client():
    """
    Get or create Razorpay client instance.
    Uses singleton pattern to reuse the same client instance.
    Configures timeouts to prevent hanging requests.
    
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
        
        # Configure connection pooling and keep-alive for better performance
        # This helps reuse connections and reduces latency on subsequent requests
        if hasattr(_client, 'session') and _client.session:
            # Enable connection pooling
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=10,  # Number of connection pools to cache
                pool_maxsize=20,      # Maximum number of connections to save in the pool
                max_retries=0,        # Disable retries (we handle retries in views)
            )
            _client.session.mount('https://', adapter)
            _client.session.mount('http://', adapter)
            logger.debug("Configured Razorpay client with connection pooling")
        
        # Configure timeouts on the underlying requests session
        # The requests library doesn't support default timeout on Session,
        # so we wrap the request methods to inject timeout
        timeout_configured = False
        
        # Method 1: Patch the client's request method if it exists
        # (Razorpay SDK may have its own request method)
        if hasattr(_client, 'request'):
            original_request = _client.request
            _client.request = _add_timeout_to_request(original_request)
            timeout_configured = True
            logger.debug("Patched Razorpay client.request() method with timeout")
        
        # Method 2: Patch the session's request methods
        # (Razorpay SDK uses requests.Session internally)
        if hasattr(_client, 'session') and _client.session:
            # Wrap the request methods to add default timeout
            _client.session.request = _add_timeout_to_request(_client.session.request)
            _client.session.get = _add_timeout_to_request(_client.session.get)
            _client.session.post = _add_timeout_to_request(_client.session.post)
            _client.session.put = _add_timeout_to_request(_client.session.put)
            _client.session.patch = _add_timeout_to_request(_client.session.patch)
            _client.session.delete = _add_timeout_to_request(_client.session.delete)
            timeout_configured = True
            logger.debug("Patched Razorpay client.session methods with timeout")
        
        if timeout_configured:
            logger.info(
                f"Razorpay client initialized with timeouts: "
                f"connect={RAZORPAY_CONNECT_TIMEOUT}s, read={RAZORPAY_READ_TIMEOUT}s"
            )
        else:
            logger.warning(
                "⚠️ Razorpay client timeout configuration failed! "
                "Neither client.request() nor client.session found. "
                "Requests may hang indefinitely. Please verify Razorpay SDK version."
            )
            logger.info("Razorpay client initialized (without timeout configuration)")
    
    return _client

