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
    Handles referral bonus, wallet updates, etc.
    """
    try:
        booking = Booking.objects.get(id=booking_id)
        user = booking.user
        
        # Check if booking has a referrer (priority: booking.referred_by, then user.referred_by)
        referrer = booking.referred_by or user.referred_by
        
        # Grant commission if referrer exists and booking is active or completed
        if referrer and booking.status in ['active', 'completed']:
            # Calculate commission using configurable percentage
            commission_percentage = getattr(settings, 'REFERRAL_COMMISSION_PERCENTAGE', 5)
            referral_bonus = float(amount) * (commission_percentage / 100)
            
            try:
                add_wallet_balance(
                    user=referrer,
                    amount=referral_bonus,
                    transaction_type='REFERRAL_BONUS',
                    description=f"Referral bonus for {user.username}'s booking {booking.booking_number}",
                    reference_id=booking.id,
                    reference_type='booking'
                )
                logger.info(
                    f"Referral commission granted: ₹{referral_bonus} to {referrer.username} "
                    f"for booking {booking.booking_number} (payment: ₹{amount})"
                )
            except Exception as e:
                logger.error(
                    f"Error granting referral commission to {referrer.username} "
                    f"for booking {booking.booking_number}: {e}"
                )
        
        # Update wallet if payment was from wallet
        # This is handled in the payment view
        
    except Booking.DoesNotExist:
        logger.error(f"Booking {booking_id} not found in payment_completed task")
    except Exception as e:
        logger.error(f"Error in payment_completed task for booking {booking_id}: {e}")

