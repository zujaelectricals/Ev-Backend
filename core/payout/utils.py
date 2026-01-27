from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from .models import Payout
from core.wallet.utils import deduct_wallet_balance
from core.booking.models import Booking


def auto_fill_emi_from_payout(user, payout_amount):
    """
    Auto-fill EMI from payout amount
    Returns amount used for EMI and remaining amount
    """
    # Get active bookings with pending EMI
    active_bookings = Booking.objects.filter(
        user=user,
        status__in=['confirmed', 'pre_booked'],
        emi_amount__gt=0
    ).order_by('emi_start_date')
    
    total_emi_used = Decimal('0')
    
    for booking in active_bookings:
        if total_emi_used >= payout_amount:
            break
        
        # Calculate pending EMI
        pending_emi_months = booking.emi_total_count - booking.emi_paid_count
        if pending_emi_months <= 0:
            continue
        
        # Calculate how much EMI can be paid from remaining payout
        remaining_payout = payout_amount - total_emi_used
        emi_to_pay = min(remaining_payout, booking.emi_amount * pending_emi_months)
        
        # Calculate how many months can be paid
        months_to_pay = int(emi_to_pay / booking.emi_amount)
        if months_to_pay > 0:
            booking.emi_paid_count += months_to_pay
            booking.total_paid += booking.emi_amount * months_to_pay
            booking.remaining_amount = booking.total_amount - booking.total_paid
            
            # Update booking status
            if booking.remaining_amount <= 0:
                booking.status = 'completed'
            
            booking.save()
            total_emi_used += booking.emi_amount * months_to_pay
    
    return total_emi_used, payout_amount - total_emi_used


def process_payout(payout):
    """
    Process payout request - deducts from wallet and sets status to 'processing'
    
    This function:
    1. Calculates TDS and net amount
    2. Handles EMI auto-fill if enabled
    3. Deducts amount from user's wallet
    4. Sets status to 'processing' and records processed_at timestamp
    
    NOTE: Payment gateway integration will be added here in the future.
    After deducting from wallet, this function should:
    - Call payment gateway API to initiate transfer
    - Handle gateway response (success/failure)
    - If gateway supports webhooks, the webhook will call complete_payout()
    
    Args:
        payout: Payout instance with status='pending'
    
    Returns:
        payout: Updated Payout instance with status='processing'
    
    Raises:
        ValueError: If payout status is not 'pending'
        Exception: If wallet deduction fails
    """
    if payout.status != 'pending':
        raise ValueError(f"Cannot process payout with status '{payout.status}'. Expected 'pending'.")
    
    with transaction.atomic():
        # Calculate TDS
        payout.calculate_tds()
        
        # Auto-fill EMI if enabled
        if payout.emi_auto_filled:
            emi_used, remaining = auto_fill_emi_from_payout(payout.user, payout.requested_amount)
            payout.emi_amount = emi_used
            payout.net_amount = remaining
        
        # Deduct from wallet
        deduct_wallet_balance(
            user=payout.user,
            amount=float(payout.requested_amount),
            transaction_type='PAYOUT',
            description=f"Payout request #{payout.id}",
            reference_id=payout.id,
            reference_type='payout'
        )
        
        # Update payout status and timestamp
        payout.status = 'processing'
        payout.processed_at = timezone.now()
        payout.save()
        
        # TODO: Future payment gateway integration
        # After this point, integrate with payment gateway:
        # 1. Call payment gateway API with payout details
        # 2. Store gateway transaction reference
        # 3. Handle gateway response:
        #    - If synchronous success: call complete_payout() automatically
        #    - If asynchronous: wait for webhook to call complete_payout()
        #    - If failure: set status to 'rejected' and refund wallet
        
        return payout


def complete_payout(payout, transaction_id=None, notes=None):
    """
    Mark payout as completed - called after payment gateway confirms successful transfer
    
    This function should be called:
    - Manually by admin after verifying bank transfer
    - Automatically by payment gateway webhook when transfer succeeds
    - After synchronous payment gateway API returns success
    
    Args:
        payout: Payout instance with status='processing'
        transaction_id: Transaction ID from payment gateway (optional)
        notes: Additional notes (optional)
    
    Returns:
        payout: Updated Payout instance with status='completed'
    
    Raises:
        ValueError: If payout status is not 'processing'
    """
    if payout.status != 'processing':
        raise ValueError(f"Cannot complete payout with status '{payout.status}'. Expected 'processing'.")
    
    payout.status = 'completed'
    payout.completed_at = timezone.now()
    
    if transaction_id:
        payout.transaction_id = transaction_id
    
    if notes:
        payout.notes = notes
    
    payout.save()
    return payout

