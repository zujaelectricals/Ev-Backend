"""
Diagnostic script to check why a user has total_earnings = 0
when their children have activation payments.

Usage:
    python manage.py shell < check_user_earnings.py
    OR
    python manage.py shell
    >>> exec(open('check_user_earnings.py').read())
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ev_backend.settings')
django.setup()

from core.users.models import User
from core.binary.models import BinaryNode
from core.booking.models import Booking
from core.wallet.models import WalletTransaction
from core.binary.utils import (
    has_activation_payment, 
    get_active_descendants_count,
    get_all_ancestors,
    process_retroactive_commissions,
    process_direct_user_commission
)
from core.settings.models import PlatformSettings

# User ID from the JSON (node_id: 6, user_id: 19)
# Change this to the user ID you want to check
user_id = 19

# If user not found, list available users with binary nodes
list_users_if_not_found = True

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
    
    print(f"\nPlatform Settings:")
    print(f"  - activation_amount: ₹{activation_amount}")
    print(f"  - binary_commission_activation_count: {activation_count}")
    print(f"  - direct_user_commission_amount: ₹{commission_amount}")
    
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
        
        # Check bookings and payments
        bookings = Booking.objects.filter(user=child_user)
        total_paid = sum(b.total_paid for b in bookings)
        print(f"  - Total bookings: {bookings.count()}")
        print(f"  - Total paid: ₹{total_paid}")
        print(f"  - Activation amount required: ₹{activation_amount}")
        print(f"  - Has activation payment: {has_activation_payment(child_user)}")
        
        # Check if commission was paid for this child
        commission_paid = WalletTransaction.objects.filter(
            user=user,
            transaction_type='DIRECT_USER_COMMISSION',
            reference_id=child_user.id,
            reference_type='user'
        ).exists()
        print(f"  - Commission paid to parent: {commission_paid}")
        
        # Check referrer
        referrer = child_user.referred_by
        if not referrer:
            booking = Booking.objects.filter(user=child_user).order_by('-created_at').first()
            if booking:
                referrer = booking.referred_by
        print(f"  - Referrer: {referrer.email if referrer else 'NOT SET'}")
        print()
    
    # Check active descendants count
    active_descendants = get_active_descendants_count(node)
    print(f"Active descendants count: {active_descendants} (required: {activation_count})")
    
    # Check wallet transactions
    print(f"\n{'='*80}")
    print("WALLET TRANSACTIONS FOR PARENT USER")
    print(f"{'='*80}\n")
    
    transactions = WalletTransaction.objects.filter(user=user).order_by('created_at')
    print(f"Total transactions: {transactions.count()}\n")
    
    earning_types = ['BINARY_PAIR_COMMISSION', 'DIRECT_USER_COMMISSION', 'BINARY_INITIAL_BONUS']
    for tx_type in earning_types:
        txs = transactions.filter(transaction_type=tx_type)
        if txs.exists():
            total = sum(tx.amount for tx in txs)
            print(f"{tx_type}: {txs.count()} transaction(s), Total: ₹{total}")
        else:
            print(f"{tx_type}: No transactions")
    
    # Check if commissions should be paid
    print(f"\n{'='*80}")
    print("COMMISSION ELIGIBILITY CHECK")
    print(f"{'='*80}\n")
    
    for side, child_node in children:
        child_user = child_node.user
        print(f"Checking {side.upper()} child: {child_user.email}")
        
        if not has_activation_payment(child_user):
            print(f"  ✗ Child does NOT have activation payment (needs ₹{activation_amount})")
            continue
        
        # Check if commission already paid
        commission_paid = WalletTransaction.objects.filter(
            user=user,
            transaction_type='DIRECT_USER_COMMISSION',
            reference_id=child_user.id,
            reference_type='user'
        ).exists()
        
        if commission_paid:
            print(f"  ✓ Commission already paid")
            continue
        
        # Check if user's binary commission is activated
        if node.binary_commission_activated:
            print(f"  ✗ Parent's binary commission is already activated - no direct commission")
            continue
        
        # Check active descendants count before this child
        # Simulate: if we remove this child, how many active descendants remain?
        # Actually, we need to check if at the time this child became active,
        # the parent had < activation_count active descendants
        
        # For now, check current state
        # Count active descendants excluding this child
        all_descendants = []
        if node.left_child:
            from core.binary.utils import get_all_descendant_nodes
            all_descendants.extend(get_all_descendant_nodes(node, 'left'))
        if node.right_child:
            all_descendants.extend(get_all_descendant_nodes(node, 'right'))
        
        # Count active descendants excluding current child
        active_count_excluding_child = sum(
            1 for n in all_descendants 
            if n.user.id != child_user.id and has_activation_payment(n.user)
        )
        
        print(f"  - Active descendants (excluding this child): {active_count_excluding_child}")
        print(f"  - Activation threshold: {activation_count}")
        
        if active_count_excluding_child < activation_count:
            print(f"  ✓ ELIGIBLE for commission payment!")
            print(f"  - Should pay: ₹{commission_amount} - 20% TDS = ₹{commission_amount * 0.8}")
        else:
            print(f"  ✗ NOT eligible (parent already has {active_count_excluding_child} active descendants)")
        print()
    
    # Check referrer for retroactive commission processing
    print(f"\n{'='*80}")
    print("RETROACTIVE COMMISSION PROCESSING CHECK")
    print(f"{'='*80}\n")
    
    for side, child_node in children:
        child_user = child_node.user
        print(f"Checking {side.upper()} child: {child_user.email}")
        
        referrer = child_user.referred_by
        if not referrer:
            booking = Booking.objects.filter(user=child_user).order_by('-created_at').first()
            if booking:
                referrer = booking.referred_by
        
        if not referrer:
            print(f"  ✗ NO REFERRER SET - This is why process_retroactive_commissions() failed!")
            print(f"     process_retroactive_commissions() requires a referrer to work.")
            print(f"     Fix: Set child_user.referred_by = parent user, or set booking.referred_by")
        else:
            print(f"  ✓ Referrer: {referrer.email} (ID: {referrer.id})")
            if referrer.id == user.id:
                print(f"     ✓ Referrer matches parent - retroactive processing should work")
            else:
                print(f"     ⚠ Referrer is different from parent - may cause issues")
        print()
    
    print(f"\n{'='*80}")
    print("RECOMMENDED FIX")
    print(f"{'='*80}\n")
    
    print("To fix missing commissions, you can:")
    print("1. Ensure children have referrer set correctly")
    print("2. Manually trigger process_retroactive_commissions() for each child")
    print("3. Or manually call process_direct_user_commission() for each child")
    print("\nExample fix code:")
    print("-" * 80)
    print("""
# Fix referrer if missing
for side, child_node in children:
    child_user = child_node.user
    if not child_user.referred_by:
        child_user.referred_by = user  # Set parent as referrer
        child_user.save()
        print(f"Set referrer for {child_user.email}")

# Process retroactive commissions
for side, child_node in children:
    child_user = child_node.user
    if has_activation_payment(child_user):
        result = process_retroactive_commissions(child_user)
        print(f"Processed retroactive commissions for {child_user.email}: {result}")
""")
    print("-" * 80)
    
except User.DoesNotExist:
    print(f"User with ID {user_id} not found!")
    if list_users_if_not_found:
        print(f"\nAvailable users with binary nodes:")
        print("-" * 80)
        nodes = BinaryNode.objects.select_related('user').all()[:20]
        if nodes:
            for node in nodes:
                print(f"  User ID: {node.user.id}, Email: {node.user.email}, "
                      f"Activated: {node.binary_commission_activated}")
        else:
            print("  No users with binary nodes found in local database.")
        print(f"\nNote: This script is designed for user ID 19 from the live server.")
        print(f"To check a different user, modify the user_id variable at the top of this script.")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

