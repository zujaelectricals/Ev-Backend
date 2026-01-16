from decimal import Decimal
from django.conf import settings
from django.db import transaction
from .models import Wallet, WalletTransaction
from core.users.models import User


def get_or_create_wallet(user):
    """Get or create wallet for user"""
    wallet, created = Wallet.objects.get_or_create(user=user)
    return wallet


def add_wallet_balance(user, amount, transaction_type, description='', reference_id=None, reference_type=''):
    """
    Add balance to user's wallet
    Handles business rules for Active Buyer, EMI deduction, and Distributor requirement
    """
    with transaction.atomic():
        wallet = get_or_create_wallet(user)
        balance_before = wallet.balance
        
        # Business Rule: Only distributors can earn from binary pairs and direct user commissions
        if transaction_type in ['BINARY_PAIR', 'BINARY_PAIR_COMMISSION', 'DIRECT_USER_COMMISSION']:
            if not user.is_distributor:
                # Log warning but don't raise error (silent failure for non-distributors)
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Attempted to credit {transaction_type} to non-distributor user {user.username}. "
                    f"Amount: {amount}. Transaction blocked."
                )
                return wallet  # Return wallet without crediting
        
        # Business Rule: Non-Active Buyer distributors can only earn commission for first 5 binary pairs
        # This check only applies to BINARY_PAIR_COMMISSION (not DIRECT_USER_COMMISSION)
        if transaction_type == 'BINARY_PAIR_COMMISSION' and user.is_distributor and not user.is_active_buyer:
            from core.binary.utils import get_binary_pairs_after_activation_count
            paid_pairs_count = get_binary_pairs_after_activation_count(user)
            
            # If 6th+ pair and not Active Buyer, block the commission
            if paid_pairs_count >= 5:
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"Binary pair commission blocked for non-Active Buyer distributor {user.username}. "
                    f"Already earned {paid_pairs_count} pairs. Commission will resume when user becomes Active Buyer. "
                    f"Amount: {amount}. Transaction blocked."
                )
                return wallet  # Return wallet without crediting
        
        # Handle TDS_DEDUCTION (negative transaction)
        if transaction_type == 'TDS_DEDUCTION':
            # TDS is a deduction, so amount should be negative
            final_amount = -Decimal(str(abs(amount)))
        else:
            # Business Rule: Check if user is Active Buyer
            is_active_buyer = user.is_active_buyer
            
            # For BINARY_PAIR transactions (legacy), apply business rules
            if transaction_type == 'BINARY_PAIR':
                # Count previous binary pair earnings
                previous_pairs = WalletTransaction.objects.filter(
                    user=user,
                    transaction_type='BINARY_PAIR'
                ).count()
                
                # Rule: First 5 earnings allowed without Active Buyer
                if previous_pairs < settings.MAX_EARNINGS_BEFORE_ACTIVE_BUYER:
                    # Full amount credited
                    final_amount = Decimal(str(amount))
                else:
                    # From 6th pair: Deduct 20% to EMI if not Active Buyer
                    if not is_active_buyer:
                        emi_deduction = Decimal(str(amount)) * Decimal(str(settings.EMI_DEDUCTION_PERCENTAGE)) / Decimal('100')
                        final_amount = Decimal(str(amount)) - emi_deduction
                        
                        # Create EMI deduction transaction
                        WalletTransaction.objects.create(
                            user=user,
                            wallet=wallet,
                            transaction_type='EMI_DEDUCTION',
                            amount=-emi_deduction,
                            balance_before=balance_before,
                            balance_after=balance_before,
                            description=f"EMI deduction (20%) from binary pair earning",
                            reference_id=reference_id,
                            reference_type=reference_type
                        )
                    else:
                        # Active Buyer gets full amount
                        final_amount = Decimal(str(amount))
            elif transaction_type in ['BINARY_PAIR_COMMISSION', 'DIRECT_USER_COMMISSION']:
                # New commission types: credit full amount (TDS already handled if applicable)
                final_amount = Decimal(str(amount))
            else:
                # For other transaction types, credit full amount
                final_amount = Decimal(str(amount))
        
        # Update wallet balance
        wallet.balance += final_amount
        
        # Update total earned for credit transactions
        if transaction_type in ['BINARY_PAIR', 'BINARY_PAIR_COMMISSION', 'DIRECT_USER_COMMISSION']:
            # Only add positive amounts to total_earned
            if final_amount > 0:
                wallet.total_earned += final_amount
        
        wallet.save()
        balance_after = wallet.balance
        
        # Create transaction record
        WalletTransaction.objects.create(
            user=user,
            wallet=wallet,
            transaction_type=transaction_type,
            amount=final_amount,
            balance_before=balance_before,
            balance_after=balance_after,
            description=description,
            reference_id=reference_id,
            reference_type=reference_type
        )
        
        return wallet


def deduct_wallet_balance(user, amount, transaction_type, description='', reference_id=None, reference_type=''):
    """
    Deduct balance from user's wallet
    """
    with transaction.atomic():
        wallet = get_or_create_wallet(user)
        balance_before = wallet.balance
        
        if wallet.balance < Decimal(str(amount)):
            raise ValueError("Insufficient wallet balance")
        
        wallet.balance -= Decimal(str(amount))
        
        # Update total withdrawn for payout
        if transaction_type == 'PAYOUT':
            wallet.total_withdrawn += Decimal(str(amount))
        
        wallet.save()
        balance_after = wallet.balance
        
        # Create transaction record
        WalletTransaction.objects.create(
            user=user,
            wallet=wallet,
            transaction_type=transaction_type,
            amount=-Decimal(str(amount)),
            balance_before=balance_before,
            balance_after=balance_after,
            description=description,
            reference_id=reference_id,
            reference_type=reference_type
        )
        
        return wallet

