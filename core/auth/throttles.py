from rest_framework.throttling import SimpleRateThrottle
from django.core.cache import cache
from django.conf import settings


class OTPRateThrottle(SimpleRateThrottle):
    """
    Custom throttle for OTP endpoints - limits to 5 requests per minute per IP
    """
    scope = 'otp'
    
    def get_cache_key(self, request, view):
        # Use IP address for rate limiting
        ident = self.get_ident(request)
        return self.cache_format % {
            'scope': self.scope,
            'ident': ident
        }


class OTPIdentifierThrottle(SimpleRateThrottle):
    """
    Throttle based on email/mobile identifier to prevent abuse even with different IPs
    Limits to 5 requests per minute per identifier
    Handles both send-otp (identifier field) and signup (email/mobile fields) endpoints
    """
    scope = 'otp_identifier'
    
    def get_cache_key(self, request, view):
        # Try to get identifier from request data
        # For send-otp endpoint: uses 'identifier' field
        identifier = request.data.get('identifier', '').strip().lower()
        
        # For signup endpoint: uses 'email' or 'mobile' fields
        if not identifier:
            email = request.data.get('email', '').strip().lower()
            mobile = request.data.get('mobile', '').strip()
            if email:
                identifier = f'email_{email}'
            elif mobile:
                identifier = f'mobile_{mobile}'
        
        if not identifier:
            # Fallback to IP if no identifier found
            ident = self.get_ident(request)
            return self.cache_format % {
                'scope': self.scope,
                'ident': f'ip_{ident}'
            }
        
        # Use identifier for rate limiting
        return self.cache_format % {
            'scope': self.scope,
            'ident': identifier
        }

