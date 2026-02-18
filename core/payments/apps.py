from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class PaymentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.payments'
    label = 'payments'
    
    def ready(self):
        """
        Pre-initialize Razorpay client at application startup.
        This prevents cold start delays on the first payment request.
        
        The first request to Razorpay API can be slow due to:
        - Client initialization overhead
        - DNS resolution
        - SSL/TLS handshake
        - Connection establishment
        
        By pre-initializing at startup, we ensure the client is ready
        and connections can be established before the first user request.
        """
        try:
            from core.payments.utils.razorpay_client import get_razorpay_client
            # Pre-initialize the client to avoid cold start timeout on first request
            client = get_razorpay_client()
            logger.info("Razorpay client pre-initialized successfully at startup")
        except ValueError as e:
            # Don't fail startup if Razorpay credentials are not configured
            # This allows the app to start even in development without Razorpay keys
            logger.warning(
                f"Razorpay credentials not configured: {e}. "
                "Client will be initialized on first use."
            )
        except Exception as e:
            # Log other exceptions but don't fail startup
            logger.warning(
                f"Failed to pre-initialize Razorpay client at startup: {e}. "
                "Client will be initialized on first use.",
                exc_info=True
            )

