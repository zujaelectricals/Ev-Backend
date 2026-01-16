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
        
        if referrer and booking.referrer_was_distributor and booking.status in ['active', 'completed']:
            # Process direct user commission if this is the first payment for this booking
            # and the user is a direct child of the referrer
            from core.binary.utils import process_direct_user_commission
            from core.binary.models import BinaryNode
            from core.wallet.models import WalletTransaction
            from core.booking.models import Payment
            
            try:
                referrer_node = BinaryNode.objects.get(user=referrer)
                user_node = BinaryNode.objects.filter(user=user, parent=referrer_node).first()
                
                # Check if user is a direct child and if this is the first payment for this booking
                if user_node and user_node.parent == referrer_node:
                    # Check if this is the first completed payment for this booking
                    completed_payments_count = Payment.objects.filter(
                        booking=booking,
                        status='completed'
                    ).count()
                    
                    # Only process commission on the first payment confirmation
                    if completed_payments_count == 1:
                        # Check if commission was already paid for this user (safety check)
                        commission_paid = WalletTransaction.objects.filter(
                            user=referrer,
                            transaction_type='DIRECT_USER_COMMISSION',
                            reference_id=user.id,
                            reference_type='user'
                        ).exists()
                        
                        if not commission_paid:
                            # Process direct user commission (only on first payment confirmation)
                            process_direct_user_commission(referrer, user)
            except BinaryNode.DoesNotExist:
                pass  # Referrer or user doesn't have a binary node yet
            except Exception as e:
                logger.error(
                    f"Error processing direct user commission for {referrer.username} "
                    f"for booking {booking.booking_number}: {e}"
                )
        
        # Update wallet if payment was from wallet
        # This is handled in the payment view
        
    except Booking.DoesNotExist:
        logger.error(f"Booking {booking_id} not found in payment_completed task")
    except Exception as e:
        logger.error(f"Error in payment_completed task for booking {booking_id}: {e}")

