from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from django.conf import settings
import logging
from .models import Payout
from core.wallet.utils import deduct_wallet_balance
from core.booking.models import Booking
from core.payments.utils.razorpayx_client import (
    create_razorpayx_contact,
    get_razorpayx_contact_by_email,
    create_razorpayx_fund_account,
    create_razorpayx_payout
)

logger = logging.getLogger(__name__)


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
                if not booking.completed_at:
                    from django.utils import timezone
                    booking.completed_at = timezone.now()
            
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
        
        # Automatically trigger RazorpayX payout API
        # Use RazorpayX client utilities (separate from Razorpay payments client)
        try:
            # Extract bank details from payout model
            account_number = payout.account_number
            ifsc_code = payout.ifsc_code
            account_holder_name = payout.account_holder_name
            
            # Convert net_amount to paise (RazorpayX uses paise)
            amount_paise = int(float(payout.net_amount) * 100)
            
            # Get RazorpayX account number from settings (business account, not user account)
            razorpayx_account_number = settings.RAZORPAYX_ACCOUNT_NUMBER
            if not razorpayx_account_number:
                raise ValueError("RAZORPAYX_ACCOUNT_NUMBER must be set in environment variables")
            
            # Step 1: Create or get RazorpayX contact
            # RazorpayX requires a contact before creating fund account
            user = payout.user
            contact_data = {
                'name': account_holder_name,
                'email': user.email if hasattr(user, 'email') and user.email else f'user_{user.id}@example.com',
                'contact': getattr(user, 'phone', None) or getattr(user, 'mobile', None) or '9999999999',
                'type': 'customer',
            }
            
            try:
                # Try to create contact
                contact_result = create_razorpayx_contact(contact_data)
                contact_id = contact_result['id']
                logger.info(f"Created RazorpayX contact {contact_id} for user {user.id}")
            except Exception as contact_error:
                # If contact already exists, try to find existing contact
                error_str = str(contact_error).lower()
                if 'already exists' in error_str or 'duplicate' in error_str or 'email' in error_str:
                    # Try to fetch existing contact by email
                    try:
                        existing_contact = get_razorpayx_contact_by_email(contact_data['email'])
                        if existing_contact:
                            contact_id = existing_contact['id']
                            logger.info(f"Using existing RazorpayX contact {contact_id} for user {user.id}")
                        else:
                            raise Exception("Contact creation failed and no existing contact found")
                    except Exception as find_error:
                        error_msg = f"Failed to create or find RazorpayX contact: {contact_error}"
                        logger.error(error_msg, exc_info=True)
                        # Mark payout as failed
                        payout.status = 'failed'
                        payout.rejection_reason = error_msg
                        payout.save()
                        raise Exception(error_msg)
                else:
                    error_msg = f"Failed to create RazorpayX contact: {contact_error}"
                    logger.error(error_msg, exc_info=True)
                    # Mark payout as failed
                    payout.status = 'failed'
                    payout.rejection_reason = error_msg
                    payout.save()
                    raise Exception(error_msg)
            
            # Step 2: Create fund account with contact_id
            fund_account_data = {
                'contact_id': contact_id,
                'account_type': 'bank_account',
                'bank_account': {
                    'name': account_holder_name,
                    'ifsc': ifsc_code,
                    'account_number': account_number,
                }
            }
            
            try:
                # Create fund account using RazorpayX client
                fund_account_result = create_razorpayx_fund_account(fund_account_data)
                fund_account_id = fund_account_result['id']
                logger.info(f"Created RazorpayX fund account {fund_account_id} for payout {payout.id}")
            except Exception as fund_account_error:
                error_msg = f"Failed to create RazorpayX fund account: {fund_account_error}"
                logger.error(error_msg, exc_info=True)
                # Mark payout as failed
                payout.status = 'failed'
                payout.rejection_reason = error_msg
                payout.save()
                raise Exception(error_msg)
            
            # Step 3: Create payout using RazorpayX client
            # Ensure account_number is set (required for RazorpayX payouts)
            if not razorpayx_account_number:
                error_msg = "RAZORPAYX_ACCOUNT_NUMBER must be set in environment variables"
                logger.error(error_msg)
                payout.status = 'failed'
                payout.rejection_reason = error_msg
                payout.save()
                raise ValueError(error_msg)
            
            # Get user details for contact
            user = payout.user
            user_email = user.email if hasattr(user, 'email') and user.email else f'user_{user.id}@example.com'
            user_phone = getattr(user, 'phone', None) or getattr(user, 'mobile', None) or '9999999999'
            
            payout_data = {
                'account_number': razorpayx_account_number,  # RazorpayX business account number (required)
                'amount': amount_paise,
                'currency': 'INR',
                'mode': 'NEFT',  # or 'RTGS', 'IMPS' based on amount
                'purpose': 'payout',
                'narration': f'Payout{payout.id}'[:30],  # Max 30 chars, alphanumeric only (no spaces/special chars)
                'fund_account': {
                    'account_type': 'bank_account',
                    'bank_account': {
                        'name': account_holder_name,
                        'ifsc': ifsc_code,
                        'account_number': account_number,
                    },
                    'contact': {  # Contact must be an object with full details
                        'name': account_holder_name,
                        'email': user_email,
                        'contact': user_phone,
                        'type': 'customer',
                        'reference_id': f'user_{user.id}',
                    }
                }
            }
            
            # Log payout data structure (without sensitive values) for debugging
            logger.info(
                f"Creating RazorpayX payout for Payout {payout.id}: "
                f"account_number={razorpayx_account_number[:4]}*** (masked), "
                f"amount={amount_paise} paise, mode=NEFT"
            )
            
            try:
                # Create payout using RazorpayX API
                razorpay_payout_result = create_razorpayx_payout(payout_data)
                razorpay_payout_id = razorpay_payout_result['id']
                
                # Update payout transaction_id with RazorpayX payout ID
                payout.transaction_id = razorpay_payout_id
                payout.save(update_fields=['transaction_id'])
                
                logger.info(
                    f"Created RazorpayX payout {razorpay_payout_id} for Payout {payout.id}, "
                    f"amount={amount_paise} paise (auto-processed)"
                )
            except Exception as payout_error:
                error_msg = f"Failed to create RazorpayX payout: {payout_error}"
                logger.error(error_msg, exc_info=True)
                # Mark payout as failed
                payout.status = 'failed'
                payout.rejection_reason = error_msg
                payout.save()
                raise Exception(error_msg)
                
        except Exception as e:
            # If any RazorpayX API call fails, mark payout as failed and raise exception
            # This prevents HTTP 201 response on failure
            error_msg = f"RazorpayX API error for Payout {payout.id}: {e}"
            logger.error(error_msg, exc_info=True)
            
            # Ensure payout is marked as failed (may have been set in nested try/except)
            if payout.status != 'failed':
                payout.status = 'failed'
                payout.rejection_reason = error_msg
                payout.save()
            
            # Raise exception to prevent HTTP 201 response
            raise Exception(error_msg)
        
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

