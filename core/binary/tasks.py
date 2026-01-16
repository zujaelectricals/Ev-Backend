from celery import shared_task
from django.utils import timezone
from .models import BinaryPair
from core.wallet.utils import add_wallet_balance


@shared_task
def pair_matched(pair_id):
    """
    Celery task triggered when binary pair is matched
    Handles wallet credit with new commission structure
    TDS and extra deduction are already deducted in check_and_create_pair, so we credit net amount
    """
    try:
        pair = BinaryPair.objects.get(id=pair_id)
        user = pair.user
        
        # Safety check: Don't process blocked commissions
        if pair.commission_blocked:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Attempted to process blocked commission for pair {pair_id}. "
                f"Reason: {pair.blocked_reason}. Skipping wallet credit."
            )
            # Still update status to processed (for tracking)
            pair.status = 'processed'
            pair.processed_at = timezone.now()
            pair.save(update_fields=['status', 'processed_at'])
            return
        
        # Get pair number for description
        pair_number = pair.pair_number_after_activation or BinaryPair.objects.filter(user=user).count()
        
        # Build description
        description = f"Binary pair commission (Pair #{pair_number} after activation)"
        if pair.is_carry_forward_pair:
            description += " - Matched with carried-forward members"
        
        # Add to wallet using new transaction type
        # earning_amount already has TDS and extra deduction deducted (net amount)
        add_wallet_balance(
            user=user,
            amount=float(pair.earning_amount),
            transaction_type='BINARY_PAIR_COMMISSION',
            description=description,
            reference_id=pair.id,
            reference_type='binary_pair'
        )
        
        # Update pair status
        pair.status = 'processed'
        pair.processed_at = timezone.now()
        pair.save(update_fields=['status', 'processed_at'])
        
    except BinaryPair.DoesNotExist:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Binary pair {pair_id} not found")
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in pair_matched task: {e}")

