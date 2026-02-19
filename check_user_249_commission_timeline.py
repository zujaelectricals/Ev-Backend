import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ev_backend.settings')
django.setup()

from core.binary.models import BinaryNode, BinaryPair
from core.users.models import User
from core.wallet.models import WalletTransaction
from core.booking.models import Booking, Payment
from core.binary.utils import has_activation_payment

user = User.objects.get(id=249)
node = BinaryNode.objects.get(user=user)

print("=" * 80)
print("USER 249 COMMISSION TIMELINE ANALYSIS")
print("=" * 80)
print()

# Get children
left_child_node = BinaryNode.objects.filter(parent=node, side='left').first()
right_child_node = BinaryNode.objects.filter(parent=node, side='right').first()

print("LEFT CHILD (nizamol007@gmail.com):")
if left_child_node:
    left_user = left_child_node.user
    print(f"  User ID: {left_user.id}")
    print(f"  Created in tree: {left_child_node.created_at}")
    
    # Check payments
    payments = Payment.objects.filter(booking__user=left_user, status='completed').order_by('payment_date')
    print(f"  Payments count: {payments.count()}")
    for p in payments:
        print(f"    Payment {p.id}: Rs.{p.amount} on {p.payment_date}")
    
    total_payments = sum(float(p.amount) for p in payments)
    print(f"  Total payments: Rs.{total_payments}")
    print(f"  Has activation payment now: {has_activation_payment(left_user)}")
    
    # Check when first payment was made
    if payments.exists():
        first_payment = payments.first()
        print(f"  First payment date: {first_payment.payment_date}")
        print(f"  Was payment made before being added to tree?")
        print(f"    Tree entry: {left_child_node.created_at}")
        print(f"    First payment: {first_payment.payment_date}")
        if first_payment.payment_date < left_child_node.created_at:
            print("    YES - Payment was made BEFORE being added to tree")
        else:
            print("    NO - Payment was made AFTER being added to tree")
print()

print("RIGHT CHILD (anamikasoman09@gmail.com):")
if right_child_node:
    right_user = right_child_node.user
    print(f"  User ID: {right_user.id}")
    print(f"  Created in tree: {right_child_node.created_at}")
    
    # Check payments
    payments = Payment.objects.filter(booking__user=right_user, status='completed').order_by('payment_date')
    print(f"  Payments count: {payments.count()}")
    for p in payments:
        print(f"    Payment {p.id}: Rs.{p.amount} on {p.payment_date}")
    
    total_payments = sum(float(p.amount) for p in payments)
    print(f"  Total payments: Rs.{total_payments}")
    print(f"  Has activation payment now: {has_activation_payment(right_user)}")
    
    # Check when first payment was made
    if payments.exists():
        first_payment = payments.first()
        print(f"  First payment date: {first_payment.payment_date}")
        print(f"  Was payment made before being added to tree?")
        print(f"    Tree entry: {right_child_node.created_at}")
        print(f"    First payment: {first_payment.payment_date}")
        if first_payment.payment_date < right_child_node.created_at:
            print("    YES - Payment was made BEFORE being added to tree")
        else:
            print("    NO - Payment was made AFTER being added to tree")
print()

print("=" * 80)
print("WHY NO COMMISSIONS?")
print("=" * 80)
print()
print("DIRECT USER COMMISSIONS:")
print("  - Paid when new user is added to tree")
print("  - Only if new user has activation payment at that time")
print("  - Only if ancestor has < 3 descendants")
print("  - Only if ancestor's binary commission not activated")
print()
print("BINARY PAIR COMMISSIONS:")
print("  - Paid when binary pair is created")
print("  - Only if binary commission is activated (needs 3+ descendants)")
print("  - Only if BOTH users in pair have activation payments")
print()
print("CURRENT STATUS:")
print(f"  - Binary commission activated: {node.binary_commission_activated}")
print(f"  - Total descendants: {node.left_count + node.right_count}")
print(f"  - Left child has activation payment: {has_activation_payment(left_child_node.user) if left_child_node else False}")
print(f"  - Right child has activation payment: {has_activation_payment(right_child_node.user) if right_child_node else False}")
print()
print("CONCLUSION:")
if not node.binary_commission_activated:
    print("  1. Binary commission NOT activated (needs 3+ descendants)")
    print("     - Current: {} descendants".format(node.left_count + node.right_count))
    print("     - Need: 3+ descendants")
if left_child_node and right_child_node:
    left_has = has_activation_payment(left_child_node.user)
    right_has = has_activation_payment(right_child_node.user)
    if not (left_has and right_has):
        print("  2. Cannot create binary pair:")
        if not left_has:
            print("     - Left child (nizamol) doesn't have activation payment (Rs.4800 < Rs.5000)")
        if not right_has:
            print("     - Right child doesn't have activation payment")
    else:
        print("  2. Both children have activation payments - pair can be created")
        print("     - But binary commission must be activated first (needs 3+ descendants)")

