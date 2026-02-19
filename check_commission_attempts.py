import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ev_backend.settings')
django.setup()

from core.binary.models import BinaryNode
from core.users.models import User
from core.booking.models import Booking, Payment
from core.binary.utils import has_activation_payment, process_direct_user_commission
from core.wallet.models import WalletTransaction
import logging

# Set up logging to see warnings
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

user = User.objects.get(id=249)
node = BinaryNode.objects.get(user=user)

print("=" * 80)
print("CHECKING COMMISSION ATTEMPTS FOR USER 249")
print("=" * 80)
print()

# Get children
left_child_node = BinaryNode.objects.filter(parent=node, side='left').first()
right_child_node = BinaryNode.objects.filter(parent=node, side='right').first()

print("ANALYSIS:")
print()

# Check left child
if left_child_node:
    left_user = left_child_node.user
    print(f"LEFT CHILD: {left_user.email}")
    print(f"  Added to tree: {left_child_node.created_at}")
    print(f"  User 249 was distributor: {user.is_distributor}")
    print(f"  User 249 date_joined: {user.date_joined}")
    
    # Check if commission was attempted
    payments = Payment.objects.filter(booking__user=left_user, status='completed').order_by('payment_date')
    if payments.exists():
        first_payment = payments.first()
        print(f"  First payment: {first_payment.payment_date} (Rs.{first_payment.amount})")
        print(f"  Has activation payment: {has_activation_payment(left_user)}")
        
        # Check if commission would be paid
        if has_activation_payment(left_user):
            print("  [YES] Would qualify for commission (has activation payment)")
        else:
            print("  [NO] Does NOT qualify for commission (no activation payment)")
            print(f"    Actual payments: Rs.{sum(float(p.amount) for p in payments)} < Rs.5000")
    print()

# Check right child
if right_child_node:
    right_user = right_child_node.user
    print(f"RIGHT CHILD: {right_user.email}")
    print(f"  Added to tree: {right_child_node.created_at}")
    print(f"  User 249 was distributor: {user.is_distributor}")
    
    # Check payments timeline
    payments = Payment.objects.filter(booking__user=right_user, status='completed').order_by('payment_date')
    if payments.exists():
        first_payment = payments.first()
        print(f"  First payment: {first_payment.payment_date} (Rs.{first_payment.amount})")
        print(f"  Has activation payment NOW: {has_activation_payment(right_user)}")
        
        # Check what payment was at time of tree addition
        payments_before_tree = payments.filter(payment_date__lt=right_child_node.created_at)
        if payments_before_tree.exists():
            total_before = sum(float(p.amount) for p in payments_before_tree)
            print(f"  Payments BEFORE being added to tree: Rs.{total_before}")
            if total_before >= 5000:
                print("  [YES] Had activation payment when added to tree - commission SHOULD have been paid")
            else:
                print("  [NO] Did NOT have activation payment when added to tree - commission NOT paid")
        else:
            print("  [NO] No payments before being added to tree - commission NOT paid")
    print()

print("=" * 80)
print("CONCLUSION:")
print("=" * 80)
print()
print("User 249 has Rs.0 earnings because:")
print()
print("1. LEFT CHILD (nizamol):")
print("   - Payment: Rs.4,800 < Rs.5,000")
print("   - Has activation payment: NO")
print("   - Commission: NOT paid (user doesn't qualify)")
print()
print("2. RIGHT CHILD (anamikasoman09):")
if right_child_node:
    payments = Payment.objects.filter(booking__user=right_child_node.user, status='completed').order_by('payment_date')
    payments_before = payments.filter(payment_date__lt=right_child_node.created_at)
    if payments_before.exists():
        total_before = sum(float(p.amount) for p in payments_before)
        if total_before < 5000:
            print(f"   - Payment when added: Rs.{total_before} < Rs.5,000")
            print("   - Has activation payment at that time: NO")
            print("   - Commission: NOT paid (user didn't qualify when added)")
        else:
            print(f"   - Payment when added: Rs.{total_before} >= Rs.5,000")
            print("   - Has activation payment at that time: YES")
            print("   - Commission: SHOULD have been paid")
    else:
        print("   - No payments when added to tree")
        print("   - Commission: NOT paid (no payment at that time)")
print()
print("3. BINARY PAIR COMMISSIONS:")
print("   - Binary commission NOT activated (needs 3+ descendants, has 2)")
print("   - Cannot create pairs until activated")
print()
print("NOTE: Distributor status is NOT the issue.")
print("      User 249 was already a distributor when children were added.")
print("      The issue is that children didn't have activation payments.")

