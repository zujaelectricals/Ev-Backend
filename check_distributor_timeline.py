import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ev_backend.settings')
django.setup()

from core.binary.models import BinaryNode
from core.users.models import User
from core.booking.models import Booking, Payment
from core.binary.utils import has_activation_payment

user = User.objects.get(id=249)
node = BinaryNode.objects.get(user=user)

print("=" * 80)
print("CHECKING IF DISTRIBUTOR STATUS AFFECTS COMMISSIONS")
print("=" * 80)
print()

print(f"User 249 (Rosmi Shaji): {user.email}")
print(f"  is_distributor: {user.is_distributor}")
print(f"  date_joined: {user.date_joined}")
print()

# Check when children were added
left_child_node = BinaryNode.objects.filter(parent=node, side='left').first()
right_child_node = BinaryNode.objects.filter(parent=node, side='right').first()

print("CHILDREN ADDED TO TREE:")
if left_child_node:
    left_user = left_child_node.user
    print(f"  Left child: {left_user.email}")
    print(f"    Added to tree: {left_child_node.created_at}")
    print(f"    User 249 was distributor at that time: {user.is_distributor}")
    print(f"    User 249 date_joined: {user.date_joined}")
    if user.date_joined < left_child_node.created_at:
        print(f"    User 249 joined BEFORE left child was added")
    else:
        print(f"    User 249 joined AFTER left child was added")
    print()

if right_child_node:
    right_user = right_child_node.user
    print(f"  Right child: {right_user.email}")
    print(f"    Added to tree: {right_child_node.created_at}")
    print(f"    User 249 was distributor at that time: {user.is_distributor}")
    if user.date_joined < right_child_node.created_at:
        print(f"    User 249 joined BEFORE right child was added")
    else:
        print(f"    User 249 joined AFTER right child was added")
    print()

# Check when payments were made
print("PAYMENT TIMELINE:")
if left_child_node:
    left_user = left_child_node.user
    payments = Payment.objects.filter(booking__user=left_user, status='completed').order_by('payment_date')
    if payments.exists():
        first_payment = payments.first()
        print(f"  Left child first payment: {first_payment.payment_date}")
        print(f"    Payment made: {first_payment.payment_date}")
        print(f"    Child added to tree: {left_child_node.created_at}")
        print(f"    User 249 was distributor: {user.is_distributor}")
        print(f"    Payment amount: Rs.{first_payment.amount}")
        print(f"    Has activation payment: {has_activation_payment(left_user)}")
        print()

if right_child_node:
    right_user = right_child_node.user
    payments = Payment.objects.filter(booking__user=right_user, status='completed').order_by('payment_date')
    if payments.exists():
        first_payment = payments.first()
        print(f"  Right child first payment: {first_payment.payment_date}")
        print(f"    Payment made: {first_payment.payment_date}")
        print(f"    Child added to tree: {right_child_node.created_at}")
        print(f"    User 249 was distributor: {user.is_distributor}")
        print(f"    Payment amount: Rs.{first_payment.amount}")
        print(f"    Has activation payment: {has_activation_payment(right_user)}")
        print()

# Check commission logic
print("=" * 80)
print("COMMISSION ELIGIBILITY CHECK:")
print("=" * 80)
print()
print("For DIRECT USER COMMISSION to be paid:")
print("  1. New user must have activation payment (>= Rs.5000)")
print("  2. Ancestor must have < 3 descendants")
print("  3. Ancestor's binary commission not activated")
print("  4. Commission is paid when new user is added to tree")
print()
print("For BINARY PAIR COMMISSION to be paid:")
print("  1. Binary commission must be activated (3+ descendants)")
print("  2. Both users in pair must have activation payments")
print("  3. Pair must be created (manually or automatically)")
print()
print("DISTRIBUTOR STATUS:")
print("  - User must be a distributor to receive commissions")
print("  - But commissions are paid based on tree structure and payment status")
print("  - NOT based on when user became distributor")
print()

