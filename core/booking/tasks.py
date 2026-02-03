from celery import shared_task
from django.conf import settings
from .models import Booking
from core.wallet.models import WalletTransaction
from core.wallet.utils import add_wallet_balance
import logging

logger = logging.getLogger(__name__)


@shared_task
def payment_completed(booking_id, amount):
    """
    Celery task triggered when payment is completed
    Handles direct user commission, wallet updates, etc.
    """
    try:
        booking = Booking.objects.get(id=booking_id)
        user = booking.user
        
        # Check if booking has a referrer (priority: booking.referred_by, then user.referred_by)
        referrer = booking.referred_by or user.referred_by
        
        # Process retroactive commissions if user now has activation payment
        # This handles cases where:
        # 1. User was placed in tree without activation payment, now becomes active buyer
        # 2. User's payment triggers binary activation for ancestors
        # 3. User becomes eligible for future pairing
        try:
            from core.binary.utils import process_retroactive_commissions
            process_retroactive_commissions(user)
        except Exception as e:
            logger.error(
                f"Error processing retroactive commissions for user {user.username} "
                f"after payment completion: {e}",
                exc_info=True
            )
        
        # NOTE: Commission is no longer paid here during payment completion
        # Commission is now paid when user is placed in binary tree via placement APIs
        # OR retroactively when user becomes active buyer (handled above)
        # See: /api/binary/nodes/auto_place_pending/ and /api/binary/nodes/place_user/
        
        # Update wallet if payment was from wallet
        # This is handled in the payment view
        
    except Booking.DoesNotExist:
        logger.error(f"Booking {booking_id} not found in payment_completed task")
    except Exception as e:
        logger.error(f"Error in payment_completed task for booking {booking_id}: {e}")

