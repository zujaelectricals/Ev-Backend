"""
Utility functions for compliance module
"""
from core.users.models import User


def get_client_ip(request):
    """
    Extract client IP address from request
    Handles both direct connections and reverse proxy setups (Nginx, load balancers, etc.)
    
    Priority order:
    1. HTTP_X_REAL_IP - Set by Nginx (most reliable in reverse proxy setups)
    2. HTTP_X_FORWARDED_FOR - Standard header for proxied requests (first IP in chain)
    3. REMOTE_ADDR - Direct connection IP (fallback)
    
    Returns: IP address string or 'unknown' if none found
    """
    # First, try X-Real-IP (set by Nginx in reverse proxy setups)
    ip_address = request.META.get('HTTP_X_REAL_IP', '').strip()
    
    if not ip_address:
        # Try X-Forwarded-For (standard header for proxied requests)
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '').strip()
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs in a chain (client, proxy1, proxy2, ...)
            # Take the first one (original client IP)
            ip_address = forwarded_for.split(',')[0].strip()
    
    if not ip_address:
        # Fallback to REMOTE_ADDR (direct connection)
        ip_address = request.META.get('REMOTE_ADDR', '').strip()
    
    # Validate IP address format (basic check)
    if ip_address and (ip_address == 'unknown' or not ip_address):
        return 'unknown'
    
    return ip_address or 'unknown'


def create_user_info_snapshot(user):
    """
    Create a snapshot of user information at a specific point in time
    This is stored for legal compliance and audit purposes
    """
    return {
        'user_id': user.id,
        'username': user.username,
        'email': user.email,
        'mobile': user.mobile,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'role': user.role,
        'is_distributor': user.is_distributor,
        'is_active_buyer': user.is_active_buyer,
        'date_joined': user.date_joined.isoformat() if user.date_joined else None,
        'last_login': user.last_login.isoformat() if user.last_login else None,
        'address': {
            'address_line1': user.address_line1,
            'address_line2': user.address_line2,
            'city': user.city,
            'state': user.state,
            'pincode': user.pincode,
            'country': user.country,
        }
    }


def create_timeline_data(user, document, ip_address, user_agent=None):
    """
    Create timeline data for document acceptance
    Includes metadata about the acceptance event
    """
    return {
        'event_type': 'document_acceptance',
        'document_id': document.id,
        'document_title': document.title,
        'document_version': document.version,
        'document_type': document.document_type,
        'user_id': user.id,
        'user_username': user.username,
        'ip_address': ip_address,
        'user_agent': user_agent,
        'acceptance_method': 'otp_verified',
    }

