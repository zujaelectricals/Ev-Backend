"""
RazorpayX client utility for payout operations
Uses direct HTTP API calls since Razorpay SDK doesn't support RazorpayX payout operations
"""
import requests
import base64
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

# Timeout configuration for RazorpayX API calls (in seconds)
RAZORPAYX_CONNECT_TIMEOUT = getattr(settings, 'RAZORPAY_CONNECT_TIMEOUT', 10)
RAZORPAYX_READ_TIMEOUT = getattr(settings, 'RAZORPAY_READ_TIMEOUT', 30)
RAZORPAYX_TIMEOUT = (RAZORPAYX_CONNECT_TIMEOUT, RAZORPAYX_READ_TIMEOUT)

# RazorpayX API base URL
RAZORPAYX_API_BASE_URL = 'https://api.razorpay.com/v1'


def get_razorpayx_auth_headers():
    """
    Generate Basic Auth headers for RazorpayX API calls.
    
    Returns:
        dict: Headers dictionary with Authorization and Content-Type
    """
    key_id = settings.RAZORPAYX_KEY_ID
    key_secret = settings.RAZORPAYX_KEY_SECRET
    
    if not key_id or not key_secret:
        raise ValueError(
            "RazorpayX credentials not configured. "
            "Please set RAZORPAYX_KEY_ID and RAZORPAYX_KEY_SECRET in environment variables."
        )
    
    auth_string = f"{key_id}:{key_secret}"
    auth_bytes = auth_string.encode('ascii')
    auth_b64 = base64.b64encode(auth_bytes).decode('ascii')
    
    return {
        'Authorization': f'Basic {auth_b64}',
        'Content-Type': 'application/json'
    }


def create_razorpayx_contact(contact_data):
    """
    Create a RazorpayX contact.
    
    Args:
        contact_data (dict): Contact data with keys: name, email, contact, type
    
    Returns:
        dict: Contact response with 'id' field
    
    Raises:
        requests.exceptions.RequestException: On API errors
        ValueError: If credentials are missing
    """
    headers = get_razorpayx_auth_headers()
    url = f'{RAZORPAYX_API_BASE_URL}/contacts'
    
    try:
        response = requests.post(
            url,
            json=contact_data,
            headers=headers,
            timeout=RAZORPAYX_TIMEOUT
        )
        
        # Check if contact already exists (400 status)
        if response.status_code == 400:
            raise requests.exceptions.HTTPError("Contact may already exist", response=response)
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"RazorpayX API error creating contact: {e}")
        raise


def get_razorpayx_contact_by_email(email):
    """
    Find existing RazorpayX contact by email.
    
    Args:
        email (str): Contact email address
    
    Returns:
        dict or None: Contact data if found, None otherwise
    
    Raises:
        requests.exceptions.RequestException: On API errors
    """
    headers = get_razorpayx_auth_headers()
    url = f'{RAZORPAYX_API_BASE_URL}/contacts'
    
    try:
        response = requests.get(
            url,
            params={'email': email},
            headers=headers,
            timeout=RAZORPAYX_TIMEOUT
        )
        response.raise_for_status()
        result = response.json()
        
        if result.get('items') and len(result['items']) > 0:
            return result['items'][0]
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"RazorpayX API error fetching contact by email: {e}")
        raise


def create_razorpayx_fund_account(fund_account_data):
    """
    Create a RazorpayX fund account.
    
    Args:
        fund_account_data (dict): Fund account data with contact_id, account_type, bank_account
    
    Returns:
        dict: Fund account response with 'id' field
    
    Raises:
        requests.exceptions.RequestException: On API errors
        ValueError: If credentials are missing
    """
    headers = get_razorpayx_auth_headers()
    url = f'{RAZORPAYX_API_BASE_URL}/fund_accounts'
    
    try:
        response = requests.post(
            url,
            json=fund_account_data,
            headers=headers,
            timeout=RAZORPAYX_TIMEOUT
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"RazorpayX API error creating fund account: {e}")
        raise


def create_razorpayx_payout(payout_data):
    """
    Create a RazorpayX payout.
    
    Args:
        payout_data (dict): Payout data with fund_account, amount, currency, etc.
    
    Returns:
        dict: Payout response with 'id' field
    
    Raises:
        requests.exceptions.RequestException: On API errors
        ValueError: If credentials are missing
    """
    headers = get_razorpayx_auth_headers()
    url = f'{RAZORPAYX_API_BASE_URL}/payouts'
    
    try:
        response = requests.post(
            url,
            json=payout_data,
            headers=headers,
            timeout=RAZORPAYX_TIMEOUT
        )
        
        # Log response details for debugging
        if response.status_code >= 400:
            try:
                error_details = response.json()
                logger.error(
                    f"RazorpayX API error creating payout (status {response.status_code}): {error_details}"
                )
            except:
                logger.error(
                    f"RazorpayX API error creating payout (status {response.status_code}): {response.text}"
                )
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        # Extract error details from response
        error_msg = str(e)
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_body = e.response.json()
                error_msg = f"{error_msg} - Response: {error_body}"
            except:
                error_msg = f"{error_msg} - Response text: {e.response.text}"
        logger.error(f"RazorpayX API error creating payout: {error_msg}")
        raise requests.exceptions.HTTPError(error_msg, response=e.response) from e
    except requests.exceptions.RequestException as e:
        logger.error(f"RazorpayX API error creating payout: {e}")
        raise

