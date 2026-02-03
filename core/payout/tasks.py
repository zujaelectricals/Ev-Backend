from celery import shared_task
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
import logging
from .models import Payout, PayoutTransaction, PayoutWebhookLog
from core.wallet.utils import add_wallet_balance

logger = logging.getLogger(__name__)


@shared_task
def emi_autofill(user_id, amount):
    """
    Celery task for EMI auto-fill
    """
    from core.users.models import User
    
    try:
        user = User.objects.get(id=user_id)
        emi_used, remaining = auto_fill_emi_from_payout(user, amount)
        return {
            'emi_used': float(emi_used),
            'remaining': float(remaining)
        }
    except User.DoesNotExist:
        print(f"User {user_id} not found")
        return None
    except Exception as e:
        print(f"Error in emi_autofill task: {e}")
        return None


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_payout_success(self, razorpay_payout_id, event_payload):
    """
    Process successful payout webhook event.
    
    This task:
    1. Finds Payout by transaction_id (Razorpay payout ID)
    2. Updates status to 'completed'
    3. Sets completed_at timestamp
    4. Creates PayoutTransaction record
    5. Marks binary commission release if applicable
    
    Args:
        razorpay_payout_id (str): Razorpay payout ID (stored in Payout.transaction_id)
        event_payload (dict): Full webhook event payload
    
    Returns:
        dict: Processing result
    """
    try:
        with transaction.atomic():
            # Find payout by transaction_id (Razorpay payout ID)
            try:
                payout = Payout.objects.select_for_update().get(
                    transaction_id=razorpay_payout_id,
                    status='processing'
                )
            except Payout.DoesNotExist:
                logger.error(
                    f"Payout not found for Razorpay payout ID: {razorpay_payout_id} "
                    f"or payout is not in 'processing' status"
                )
                return {'success': False, 'error': 'Payout not found or invalid status'}
            
            # Update payout status
            payout.status = 'completed'
            payout.completed_at = timezone.now()
            
            # Update transaction_id if provided in payload (should already be set, but ensure consistency)
            payout_data = event_payload.get('payload', {}).get('payout', {})
            if payout_data and payout_data.get('id'):
                payout.transaction_id = payout_data.get('id')
            
            payout.save(update_fields=['status', 'completed_at', 'transaction_id'])
            
            # Create PayoutTransaction record
            PayoutTransaction.objects.create(
                payout=payout,
                user=payout.user,
                amount=payout.net_amount,
                transaction_type='payout',
                description=f"Payout completed via RazorpayX - {razorpay_payout_id}"
            )
            
            logger.info(
                f"Payout {payout.id} marked as completed via webhook. "
                f"Razorpay payout ID: {razorpay_payout_id}, Amount: ₹{payout.net_amount}"
            )
            
            # Note: Wallet is already deducted when payout was processed
            # No need to credit wallet on success
            
            # Mark binary commission release if applicable
            # Note: This may need clarification - currently commissions are credited immediately
            # when pairs are matched. This might be for future feature.
            # For now, we'll log that payout is completed which may trigger commission release logic
            # in the future.
            
            return {
                'success': True,
                'payout_id': payout.id,
                'razorpay_payout_id': razorpay_payout_id
            }
            
    except Exception as e:
        logger.error(
            f"Error processing payout success for Razorpay payout ID {razorpay_payout_id}: {e}",
            exc_info=True
        )
        # Retry on transient errors
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        return {'success': False, 'error': str(e)}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_payout_failure(self, razorpay_payout_id, event_payload):
    """
    Process failed payout webhook event.
    
    This task:
    1. Finds Payout by transaction_id (Razorpay payout ID)
    2. Updates status to 'rejected'
    3. Stores failure reason
    4. Refunds locked wallet amount (add back to wallet)
    5. Creates WalletTransaction for refund
    
    Args:
        razorpay_payout_id (str): Razorpay payout ID (stored in Payout.transaction_id)
        event_payload (dict): Full webhook event payload
    
    Returns:
        dict: Processing result
    """
    try:
        with transaction.atomic():
            # Find payout by transaction_id
            try:
                payout = Payout.objects.select_for_update().get(
                    transaction_id=razorpay_payout_id
                )
            except Payout.DoesNotExist:
                logger.error(
                    f"Payout not found for Razorpay payout ID: {razorpay_payout_id}"
                )
                return {'success': False, 'error': 'Payout not found'}
            
            # Extract failure reason from payload
            payout_data = event_payload.get('payload', {}).get('payout', {})
            failure_reason = payout_data.get('failure_reason', 'Payout failed via RazorpayX')
            if not failure_reason:
                failure_reason = 'Payout failed - no reason provided'
            
            # Update payout status
            payout.status = 'rejected'
            payout.rejection_reason = failure_reason
            payout.save(update_fields=['status', 'rejection_reason'])
            
            # Refund locked wallet amount (add back to wallet)
            # The wallet was deducted when payout was processed, so we need to refund it
            add_wallet_balance(
                user=payout.user,
                amount=float(payout.requested_amount),
                transaction_type='REFUND',
                description=f"Refund for failed payout {payout.id} - {failure_reason}",
                reference_id=payout.id,
                reference_type='payout'
            )
            
            logger.info(
                f"Payout {payout.id} marked as rejected via webhook. "
                f"Razorpay payout ID: {razorpay_payout_id}, "
                f"Amount refunded: ₹{payout.requested_amount}, "
                f"Reason: {failure_reason}"
            )
            
            return {
                'success': True,
                'payout_id': payout.id,
                'razorpay_payout_id': razorpay_payout_id,
                'refunded_amount': float(payout.requested_amount)
            }
            
    except Exception as e:
        logger.error(
            f"Error processing payout failure for Razorpay payout ID {razorpay_payout_id}: {e}",
            exc_info=True
        )
        # Retry on transient errors
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        return {'success': False, 'error': str(e)}

