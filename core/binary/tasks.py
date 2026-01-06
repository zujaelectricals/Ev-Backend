from celery import shared_task
from .models import BinaryPair
from core.wallet.utils import add_wallet_balance


@shared_task
def pair_matched(pair_id):
    """
    Celery task triggered when binary pair is matched
    Handles wallet credit with business rules
    """
    try:
        pair = BinaryPair.objects.get(id=pair_id)
        user = pair.user
        
        # Count previous pairs
        previous_pairs = BinaryPair.objects.filter(user=user).count()
        
        # Add to wallet (business rules handled in add_wallet_balance)
        add_wallet_balance(
            user=user,
            amount=float(pair.earning_amount),
            transaction_type='BINARY_PAIR',
            description=f"Binary pair earning (Pair #{previous_pairs + 1})",
            reference_id=pair.id,
            reference_type='binary_pair'
        )
        
        # Update pair status
        pair.status = 'processed'
        pair.processed_at = timezone.now()
        pair.save(update_fields=['status', 'processed_at'])
        
    except BinaryPair.DoesNotExist:
        print(f"Binary pair {pair_id} not found")
    except Exception as e:
        print(f"Error in pair_matched task: {e}")

