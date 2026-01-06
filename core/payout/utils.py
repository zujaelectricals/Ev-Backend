from decimal import Decimal
from django.db import transaction
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
    Process payout request
    """
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
        
        # Update payout status
        payout.status = 'processing'
        payout.save()
        
        return payout

