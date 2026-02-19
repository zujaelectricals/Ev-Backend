"""
Diagnostic script to check why user 18 has total_earnings = 900
when they should have earned more from commissions.

Usage:
    python manage.py shell < check_user_18_earnings.py
    OR
    python manage.py shell
    >>> exec(open('check_user_18_earnings.py').read())
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ev_backend.settings')
django.setup()

from core.users.models import User
from core.binary.models import BinaryNode, BinaryPair
from core.booking.models import Booking, Payment
from core.wallet.models import WalletTransaction
from core.binary.utils import (
    has_activation_payment, 
    get_active_descendants_count,
    get_all_ancestors,
)
from core.settings.models import PlatformSettings
from decimal import Decimal

# User ID from the JSON (node_id: 8, user_id: 18)
user_id = 18

try:
    user = User.objects.get(id=user_id)
    print(f"\n{'='*80}")
    print(f"DIAGNOSTIC REPORT FOR USER: {user.email} (ID: {user.id})")
    print(f"{'='*80}\n")
    
    # Check if user has binary node
    try:
        node = BinaryNode.objects.get(user=user)
        print(f"✓ Binary node exists (node_id: {node.id})")
        print(f"  - binary_commission_activated: {node.binary_commission_activated}")
        print(f"  - activation_timestamp: {node.activation_timestamp}")
        print(f"  - left_count: {node.left_count}, right_count: {node.right_count}")
        print(f"  - total_descendants: {node.left_count + node.right_count}")
    except BinaryNode.DoesNotExist:
        print(f"✗ User has no binary node!")
        exit()
    
    # Get platform settings
    settings = PlatformSettings.get_settings()
    activation_amount = settings.activation_amount
    activation_count = settings.binary_commission_activation_count
    commission_amount = settings.direct_user_commission_amount
    binary_initial_bonus = getattr(settings, 'binary_commission_initial_bonus', Decimal('0'))
    binary_pair_commission = getattr(settings, 'binary_pair_commission_amount', Decimal('2000'))
    
    print(f"\nPlatform Settings:")
    print(f"  - activation_amount: ₹{activation_amount}")
    print(f"  - binary_commission_activation_count: {activation_count}")
    print(f"  - direct_user_commission_amount: ₹{commission_amount}")
    print(f"  - binary_commission_initial_bonus: ₹{binary_initial_bonus}")
    print(f"  - binary_pair_commission_amount: ₹{binary_pair_commission}")
    
    # Check wallet transactions
    print(f"\n{'='*80}")
    print("WALLET TRANSACTIONS FOR USER")
    print(f"{'='*80}\n")
    
    transactions = WalletTransaction.objects.filter(user=user).order_by('created_at')
    print(f"Total transactions: {transactions.count()}\n")
    
    # Check all transaction types
    all_types = transactions.values_list('transaction_type', flat=True).distinct()
    print("All transaction types found:")
    for tx_type in all_types:
        count = transactions.filter(transaction_type=tx_type).count()
        total = sum(tx.amount for tx in transactions.filter(transaction_type=tx_type))
        print(f"  - {tx_type}: {count} transaction(s), Total: ₹{total}")
    
    print()
    
    # Check earning types specifically
    earning_types = ['BINARY_PAIR_COMMISSION', 'DIRECT_USER_COMMISSION', 'BINARY_INITIAL_BONUS']
    print("EARNING TRANSACTIONS (used for total_earnings calculation):")
    total_earnings_calc = Decimal('0')
    for tx_type in earning_types:
        txs = transactions.filter(transaction_type=tx_type)
        if txs.exists():
            total = sum(tx.amount for tx in txs)
            total_earnings_calc += total
            print(f"  {tx_type}: {txs.count()} transaction(s), Total: ₹{total}")
            for tx in txs:
                print(f"    - ₹{tx.amount} on {tx.created_at} - {tx.description}")
        else:
            print(f"  {tx_type}: No transactions")
    
    print(f"\n  Calculated total_earnings: ₹{total_earnings_calc}")
    
    # Check children
    print(f"\n{'='*80}")
    print("CHILDREN ANALYSIS")
    print(f"{'='*80}\n")
    
    left_child = node.left_child
    right_child = node.right_child
    
    children = []
    if left_child:
        children.append(('left', left_child))
    if right_child:
        children.append(('right', right_child))
    
    for side, child_node in children:
        child_user = child_node.user
        print(f"{side.upper()} CHILD: {child_user.email} (ID: {child_user.id})")
        print(f"  - Created at: {child_node.created_at}")
        print(f"  - Activation timestamp: {node.activation_timestamp}")
        
        # Check if child was added before or after activation
        if node.activation_timestamp and child_node.created_at:
            if child_node.created_at <= node.activation_timestamp:
                print(f"  - ✓ Added BEFORE activation (eligible for direct commission)")
            else:
                print(f"  - ✗ Added AFTER activation (not eligible for direct commission)")
        
        # Check bookings and payments
        bookings = Booking.objects.filter(user=child_user)
        total_paid = sum(b.total_paid for b in bookings)
        print(f"  - Total bookings: {bookings.count()}")
        print(f"  - Total paid: ₹{total_paid}")
        print(f"  - Has activation payment: {has_activation_payment(child_user)}")
        
        # Check if commission was paid for this child
        commission_paid = WalletTransaction.objects.filter(
            user=user,
            transaction_type='DIRECT_USER_COMMISSION',
            reference_id=child_user.id,
            reference_type='user'
        ).exists()
        print(f"  - Direct commission paid to parent: {commission_paid}")
        
        if commission_paid:
            tx = WalletTransaction.objects.filter(
                user=user,
                transaction_type='DIRECT_USER_COMMISSION',
                reference_id=child_user.id,
                reference_type='user'
            ).first()
            print(f"    Transaction: ₹{tx.amount} on {tx.created_at}")
        
        print()
    
    # Check binary pairs
    print(f"\n{'='*80}")
    print("BINARY PAIRS ANALYSIS")
    print(f"{'='*80}\n")
    
    pairs = BinaryPair.objects.filter(user=user).order_by('created_at')
    print(f"Total binary pairs: {pairs.count()}\n")
    
    for pair in pairs:
        print(f"Pair #{pair.id}:")
        print(f"  - Created: {pair.created_at}")
        print(f"  - Status: {pair.status}")
        print(f"  - Processed: {pair.processed_at if pair.processed_at else 'NOT PROCESSED'}")
        print(f"  - Left user: {pair.left_user.email if pair.left_user else 'N/A'}")
        print(f"  - Right user: {pair.right_user.email if pair.right_user else 'N/A'}")
        
        # Check if commission was paid
        commission_tx = WalletTransaction.objects.filter(
            user=user,
            transaction_type='BINARY_PAIR_COMMISSION',
            reference_id=pair.id,
            reference_type='binary_pair'
        ).first()
        
        if commission_tx:
            print(f"  - Commission paid: ₹{commission_tx.amount} on {commission_tx.created_at}")
        else:
            print(f"  - ✗ NO COMMISSION PAID!")
        print()
    
    # Check binary initial bonus
    print(f"\n{'='*80}")
    print("BINARY INITIAL BONUS CHECK")
    print(f"{'='*80}\n")
    
    if node.binary_commission_activated:
        bonus_tx = WalletTransaction.objects.filter(
            user=user,
            transaction_type='BINARY_INITIAL_BONUS'
        ).first()
        
        if bonus_tx:
            print(f"✓ Initial bonus paid: ₹{bonus_tx.amount} on {bonus_tx.created_at}")
            print(f"  Description: {bonus_tx.description}")
        else:
            print(f"✗ NO INITIAL BONUS PAID!")
            print(f"  Expected: ₹{binary_initial_bonus} - 20% TDS = ₹{binary_initial_bonus * Decimal('0.8')}")
    else:
        print("Binary commission not activated yet - no initial bonus expected")
    
    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}\n")
    
    print(f"Current total_earnings: ₹{total_earnings_calc}")
    print(f"\nExpected earnings breakdown:")
    
    # Count direct commissions expected
    direct_commissions_expected = 0
    for side, child_node in children:
        if node.activation_timestamp and child_node.created_at:
            if child_node.created_at <= node.activation_timestamp:
                if has_activation_payment(child_node.user):
                    direct_commissions_expected += 1
    
    if direct_commissions_expected > 0:
        direct_commissions_total = commission_amount * Decimal('0.8') * direct_commissions_expected
        print(f"  - Direct user commissions ({direct_commissions_expected} children): ₹{direct_commissions_total}")
    
    # Initial bonus
    if node.binary_commission_activated:
        initial_bonus_net = binary_initial_bonus * Decimal('0.8')
        print(f"  - Binary initial bonus: ₹{initial_bonus_net}")
    
    # Binary pairs
    processed_pairs = pairs.filter(status='processed')
    if processed_pairs.exists():
        pairs_total = Decimal('0')
        for pair in processed_pairs:
            # Pairs 1-5: ₹1600 net, Pairs 6+: ₹1200 net (assuming active buyer)
            pair_num = processed_pairs.filter(created_at__lte=pair.created_at).count()
            if pair_num <= 5:
                pairs_total += Decimal('1600')
            else:
                pairs_total += Decimal('1200')
        print(f"  - Binary pair commissions ({processed_pairs.count()} pairs): ₹{pairs_total}")
    
    print(f"\n{'='*80}")
    print("ANALYSIS COMPLETE")
    print(f"{'='*80}\n")
    
except User.DoesNotExist:
    print(f"User with ID {user_id} not found!")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

