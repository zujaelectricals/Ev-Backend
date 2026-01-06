from celery import shared_task
from django.conf import settings
from .models import Booking
from core.wallet.models import WalletTransaction
from core.wallet.utils import add_wallet_balance


@shared_task
def payment_completed(booking_id, amount):
    """
    Celery task triggered when payment is completed
    Handles referral bonus, wallet updates, etc.
    """
    try:
        booking = Booking.objects.get(id=booking_id)
        user = booking.user
        
        # Check if user was referred and this is their first booking
        if user.referred_by and booking.status == 'confirmed':
            # Add referral bonus to referrer's wallet
            referral_bonus = float(amount) * 0.05  # 5% referral bonus (adjust as needed)
            
            add_wallet_balance(
                user=user.referred_by,
                amount=referral_bonus,
                transaction_type='REFERRAL_BONUS',
                description=f"Referral bonus for {user.username}'s booking",
                reference_id=booking.id
            )
        
        # Update wallet if payment was from wallet
        # This is handled in the payment view
        
    except Booking.DoesNotExist:
        print(f"Booking {booking_id} not found")
    except Exception as e:
        print(f"Error in payment_completed task: {e}")

