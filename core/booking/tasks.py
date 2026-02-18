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


@shared_task
def send_booking_confirmation_email_task(booking_id):
    """
    Celery task to send booking confirmation email via MSG91.
    Triggered when booking status changes to 'active' after payment verification.
    
    Args:
        booking_id: ID of the Booking instance
    """
    try:
        booking = Booking.objects.select_related('user').get(id=booking_id)
        
        # Check if booking status is 'active' and has payment_receipt
        if booking.status != 'active':
            logger.warning(
                f"Booking {booking_id} status is '{booking.status}', not 'active'. "
                f"Skipping confirmation email."
            )
            return
        
        if not booking.payment_receipt:
            logger.warning(
                f"Booking {booking_id} has no payment receipt. Skipping confirmation email."
            )
            return
        
        # Send confirmation email
        from core.booking.utils import send_booking_confirmation_email_msg91
        success, error_msg = send_booking_confirmation_email_msg91(booking)
        
        if success:
            logger.info(f"Booking confirmation email sent successfully for booking {booking_id}")
        else:
            logger.error(
                f"Failed to send booking confirmation email for booking {booking_id}: {error_msg}"
            )
            
    except Booking.DoesNotExist:
        logger.error(f"Booking {booking_id} not found in send_booking_confirmation_email_task")
    except Exception as e:
        logger.error(
            f"Error in send_booking_confirmation_email_task for booking {booking_id}: {e}",
            exc_info=True
        )

