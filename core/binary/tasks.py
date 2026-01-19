from celery import shared_task
from celery.exceptions import Retry
from django.utils import timezone
from django.db import transaction
from .models import BinaryPair, BinaryEarning
from core.wallet.models import WalletTransaction
from core.wallet.utils import add_wallet_balance, get_or_create_wallet
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def pair_matched(self, pair_id):
    """
    Celery task triggered when binary pair is matched
    Handles wallet credit with new commission structure
    TDS and extra deduction are already deducted in check_and_create_pair, so we credit net amount
    
    Retry Logic:
    - Max 3 retries with 60 second delay
    - If pair doesn't exist, tries to recover from BinaryEarning record
    - If recovery fails, logs error and stops retrying
    """
    try:
        pair = BinaryPair.objects.get(id=pair_id)
        user = pair.user
        
        # Check if already processed (idempotency check)
        existing_txn = WalletTransaction.objects.filter(
            reference_id=pair.id,
            reference_type='binary_pair',
            transaction_type='BINARY_PAIR_COMMISSION'
        ).first()
        
        if existing_txn:
            logger.info(
                f"Pair {pair_id} already processed. Wallet transaction {existing_txn.id} exists. "
                f"Skipping duplicate processing."
            )
            # Update pair status if not already updated
            if pair.status != 'processed':
                pair.status = 'processed'
                pair.processed_at = timezone.now()
                pair.save(update_fields=['status', 'processed_at'])
            return
        
        # Safety check: Don't process blocked commissions
        if pair.commission_blocked:
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
        
        # IMPORTANT: Check if commission should be blocked based on pair_number_after_activation
        # NOT based on current paid count (which has off-by-one bug)
        # Business rule: Non-Active Buyer can only earn for first 5 pairs
        if not user.is_active_buyer and pair_number and pair_number > 5:
            logger.warning(
                f"Pair {pair_id} (Pair #{pair_number}) blocked for non-Active Buyer user {user.email}. "
                f"This is the 6th+ pair. Commission will resume when user becomes Active Buyer."
            )
            # Mark as blocked if not already
            if not pair.commission_blocked:
                pair.commission_blocked = True
                pair.blocked_reason = f"Not Active Buyer, 6th+ pair (Pair #{pair_number}). Commission will resume when user becomes Active Buyer."
                pair.save(update_fields=['commission_blocked', 'blocked_reason'])
            # Update status to processed (for tracking)
            pair.status = 'processed'
            pair.processed_at = timezone.now()
            pair.save(update_fields=['status', 'processed_at'])
            return
        
        # Add to wallet using new transaction type
        # earning_amount already has TDS and extra deduction deducted (net amount)
        # Use add_wallet_balance but it will do its own check - but we've already verified pair_number
        # So we bypass the check by creating transaction directly if needed
        from core.wallet.models import Wallet, WalletTransaction as WT
        
        wallet = get_or_create_wallet(user)
        balance_before = wallet.balance
        
        # Update wallet balance
        wallet.balance += Decimal(str(pair.earning_amount))
        wallet.total_earned += Decimal(str(pair.earning_amount))
        wallet.save()
        
        balance_after = wallet.balance
        
        # Create transaction record
        WT.objects.create(
            user=user,
            wallet=wallet,
            transaction_type='BINARY_PAIR_COMMISSION',
            amount=Decimal(str(pair.earning_amount)),
            balance_before=balance_before,
            balance_after=balance_after,
            description=description,
            reference_id=pair.id,
            reference_type='binary_pair'
        )
        
        # Update pair status
        pair.status = 'processed'
        pair.processed_at = timezone.now()
        pair.save(update_fields=['status', 'processed_at'])
        
        logger.info(f"Successfully processed pair {pair_id} for user {user.email}. Amount: ₹{pair.earning_amount}")
        
    except BinaryPair.DoesNotExist:
        logger.warning(
            f"Binary pair {pair_id} not found. Attempting recovery from BinaryEarning record..."
        )
        
        # RECOVERY ATTEMPT: Try to find BinaryEarning and process from that
        try:
            earning = BinaryEarning.objects.filter(binary_pair_id=pair_id).first()
            
            if earning:
                user = earning.user
                net_amount = earning.net_amount
                
                # Check if wallet transaction already exists
                existing_txn = WalletTransaction.objects.filter(
                    reference_id=pair_id,
                    reference_type='binary_pair',
                    transaction_type='BINARY_PAIR_COMMISSION'
                ).first()
                
                if existing_txn:
                    logger.info(
                        f"Recovery: Wallet transaction already exists for pair {pair_id}. "
                        f"Transaction ID: {existing_txn.id}"
                    )
                    return
                
                # Recover by creating wallet transaction from BinaryEarning
                logger.info(
                    f"Recovery: Creating wallet transaction from BinaryEarning for pair {pair_id}. "
                    f"User: {user.email}, Amount: ₹{net_amount}"
                )
                
                # Try to get the pair to check pair_number_after_activation
                # If pair was deleted, we'll use a safer approach
                try:
                    pair = BinaryPair.objects.get(id=pair_id)
                    pair_number = pair.pair_number_after_activation
                    
                    # Check if should be blocked based on pair_number
                    if not user.is_active_buyer and pair_number and pair_number > 5:
                        logger.warning(
                            f"Recovery: Pair {pair_id} (Pair #{pair_number}) should be blocked for non-Active Buyer. "
                            f"Skipping wallet credit."
                        )
                        return
                except BinaryPair.DoesNotExist:
                    # Pair doesn't exist - use wallet transaction count as fallback
                    # Count existing wallet transactions to determine if this should be blocked
                    existing_txns_count = WalletTransaction.objects.filter(
                        user=user,
                        transaction_type='BINARY_PAIR_COMMISSION'
                    ).count()
                    
                    if not user.is_active_buyer and existing_txns_count >= 5:
                        logger.warning(
                            f"Recovery: User {user.email} already has {existing_txns_count} wallet transactions. "
                            f"This recovery would be 6th+ pair. Skipping for non-Active Buyer."
                        )
                        return
                
                # Create wallet transaction directly (bypassing add_wallet_balance to avoid buggy count check)
                wallet = get_or_create_wallet(user)
                balance_before = wallet.balance
                
                wallet.balance += Decimal(str(net_amount))
                wallet.total_earned += Decimal(str(net_amount))
                wallet.save()
                
                balance_after = wallet.balance
                
                WalletTransaction.objects.create(
                    user=user,
                    wallet=wallet,
                    transaction_type='BINARY_PAIR_COMMISSION',
                    amount=Decimal(str(net_amount)),
                    balance_before=balance_before,
                    balance_after=balance_after,
                    description=f"Binary pair commission (recovered from BinaryEarning for pair #{pair_id})",
                    reference_id=pair_id,
                    reference_type='binary_pair'
                )
                
                logger.info(f"Successfully recovered and processed pair {pair_id} from BinaryEarning")
                return
            else:
                logger.error(
                    f"Recovery failed: BinaryEarning not found for pair {pair_id}. "
                    f"This will cause a mismatch between total_earnings and wallet_balance. "
                    f"Manual intervention required."
                )
                # Don't retry if we can't recover
                return
                
        except Exception as recovery_error:
            logger.error(
                f"Recovery attempt failed for pair {pair_id}: {recovery_error}. "
                f"This will cause a mismatch between total_earnings and wallet_balance."
            )
            # Don't retry if recovery fails
            return
            
    except Exception as e:
        logger.error(
            f"Error in pair_matched task for pair {pair_id}: {e}. "
            f"Attempt {self.request.retries + 1}/{self.max_retries}"
        )
        
        # Retry with exponential backoff for transient errors
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))
        else:
            logger.error(
                f"Max retries reached for pair {pair_id}. "
                f"This may cause a mismatch between total_earnings and wallet_balance. "
                f"Manual intervention required."
            )
            raise


@shared_task
def fix_missing_wallet_transactions():
    """
    Periodic task to find and fix missing wallet transactions for binary pairs
    Runs periodically to catch any pairs that failed processing
    This is a safety net to prevent permanent mismatches
    """
    from .models import BinaryPair, BinaryEarning
    from core.wallet.models import WalletTransaction
    
    logger.info("Starting periodic check for missing wallet transactions...")
    
    # Find pairs that have BinaryEarning but no wallet transaction
    # Check both 'matched' and 'processed' status pairs
    problematic_pairs = []
    
    for pair in BinaryPair.objects.filter(status__in=['matched', 'processed'], earning_amount__gt=0):
        earnings = BinaryEarning.objects.filter(binary_pair=pair).first()
        wallet_txns = WalletTransaction.objects.filter(
            reference_id=pair.id,
            reference_type='binary_pair',
            transaction_type='BINARY_PAIR_COMMISSION'
        )
        
        if earnings and not wallet_txns.exists() and not pair.commission_blocked:
            problematic_pairs.append(pair)
    
    if not problematic_pairs:
        logger.info("No missing wallet transactions found. All pairs are properly processed.")
        return {'fixed_count': 0, 'checked_count': BinaryPair.objects.filter(status='matched').count()}
    
    logger.warning(f"Found {len(problematic_pairs)} pairs with missing wallet transactions. Attempting to fix...")
    
    fixed_count = 0
    failed_count = 0
    
    for pair in problematic_pairs:
        try:
            user = pair.user
            earning_amount = pair.earning_amount
            
            # IMPORTANT: Check if this pair should be blocked based on pair_number_after_activation
            # Not based on current paid count (which would incorrectly block delayed pairs)
            pair_number = pair.pair_number_after_activation
            
            # Business rule: Non-Active Buyer can only earn for first 5 pairs
            # If pair_number > 5 and user is not Active Buyer, this pair should be blocked
            if not user.is_active_buyer and pair_number and pair_number > 5:
                logger.info(
                    f"Skipping pair {pair.id}: Pair #{pair_number} for non-Active Buyer user {user.email}. "
                    f"This pair should be blocked (6th+ pair)."
                )
                # Mark as blocked if not already
                if not pair.commission_blocked:
                    pair.commission_blocked = True
                    pair.blocked_reason = f"Not Active Buyer, 6th+ pair (Pair #{pair_number}). Commission will resume when user becomes Active Buyer."
                    pair.save(update_fields=['commission_blocked', 'blocked_reason'])
                # Update BinaryEarning to reflect blocked status
                earning = BinaryEarning.objects.filter(binary_pair=pair).first()
                if earning and earning.net_amount > 0:
                    earning.net_amount = Decimal('0')
                    earning.save(update_fields=['net_amount'])
                    logger.info(f"Updated BinaryEarning for pair {pair.id} to ₹0 (blocked)")
                continue
            
            # Get pair number for description
            pair_number_display = pair_number or BinaryPair.objects.filter(user=user).count()
            
            description = f"Binary pair commission (Pair #{pair_number_display} after activation - auto-recovered)"
            if pair.is_carry_forward_pair:
                description += " - Matched with carried-forward members"
            
            # IMPORTANT: For fix task, we need to bypass the Active Buyer check in add_wallet_balance
            # because we've already verified the pair_number_after_activation (5th pair is allowed)
            # Create wallet transaction directly to avoid double-checking
            from core.wallet.models import Wallet, WalletTransaction
            from core.wallet.utils import get_or_create_wallet
            
            wallet = get_or_create_wallet(user)
            balance_before = wallet.balance
            
            # Update wallet balance
            wallet.balance += Decimal(str(earning_amount))
            wallet.total_earned += Decimal(str(earning_amount))
            wallet.save()
            
            balance_after = wallet.balance
            
            # Create transaction record
            WalletTransaction.objects.create(
                user=user,
                wallet=wallet,
                transaction_type='BINARY_PAIR_COMMISSION',
                amount=Decimal(str(earning_amount)),
                balance_before=balance_before,
                balance_after=balance_after,
                description=description,
                reference_id=pair.id,
                reference_type='binary_pair'
            )
            
            # Update pair status
            pair.status = 'processed'
            pair.processed_at = timezone.now()
            pair.save(update_fields=['status', 'processed_at'])
            
            fixed_count += 1
            logger.info(f"Fixed missing wallet transaction for pair {pair.id} (user: {user.email}, amount: ₹{earning_amount})")
            
        except Exception as e:
            failed_count += 1
            logger.error(f"Failed to fix pair {pair.id}: {e}")
    
    logger.info(f"Fixed {fixed_count} missing wallet transactions. {failed_count} failed.")
    return {'fixed_count': fixed_count, 'failed_count': failed_count, 'total_checked': len(problematic_pairs)}

