"""
Diagnostic script to check booking 298 and why status is not active.
Run with: python check_booking_298.py
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ev_backend.settings')
django.setup()

from core.booking.models import Booking, Payment
from decimal import Decimal

booking_id = 298

print(f"\n{'='*80}")
print(f"CHECKING BOOKING {booking_id} STATUS AND COMMISSIONS")
print(f"{'='*80}\n")

try:
    booking = Booking.objects.get(id=booking_id)
    
    print(f"Booking {booking_id}: {booking.booking_number}")
    print(f"   Status: {booking.status}")
    print(f"   Booking Amount: Rs.{booking.booking_amount}")
    print(f"   Total Amount: Rs.{booking.total_amount}")
    print(f"   Total Paid (from DB): Rs.{booking.total_paid}")
    print(f"   Remaining Amount: Rs.{booking.remaining_amount}")
    print(f"   Confirmed At: {booking.confirmed_at}")
    
    print(f"\n   {'='*76}")
    print(f"   PAYMENT RECORDS:")
    print(f"   {'='*76}\n")
    
    payments = Payment.objects.filter(booking=booking).order_by('payment_date')
    
    if not payments.exists():
        print(f"   [WARNING] No payment records found!")
    else:
        completed_payments_sum = Decimal('0')
        
        for i, payment in enumerate(payments, 1):
            status_indicator = "[COMPLETED]" if payment.status == 'completed' else f"[{payment.status.upper()}]"
            print(f"   {i}. Payment ID: {payment.id}")
            print(f"      Transaction ID: {payment.transaction_id or 'N/A'}")
            print(f"      Amount: Rs.{payment.amount}")
            print(f"      Status: {status_indicator}")
            print(f"      Date: {payment.payment_date}")
            print()
            
            if payment.status == 'completed':
                completed_payments_sum += Decimal(str(payment.amount))
        
        print(f"   {'='*76}")
        print(f"   SUMMARY:")
        print(f"   {'='*76}")
        print(f"   Total from COMPLETED payments: Rs.{completed_payments_sum}")
        print(f"   Booking.total_paid (from DB): Rs.{booking.total_paid}")
        print(f"   Booking Amount: Rs.{booking.booking_amount}")
        print()
        
        # Check if status should be active
        actual_total_paid = completed_payments_sum
        if actual_total_paid >= Decimal(str(booking.booking_amount)):
            if booking.status != 'active':
                print(f"   [ERROR] STATUS MISMATCH!")
                print(f"   - Actual total_paid: Rs.{actual_total_paid} >= Booking Amount: Rs.{booking.booking_amount}")
                print(f"   - But status is: {booking.status} (should be 'active')")
                print(f"   - This is why commissions are not being processed!")
            else:
                print(f"   [OK] Status is correct: {booking.status}")
        else:
            print(f"   [INFO] Total paid ({actual_total_paid}) < Booking Amount ({booking.booking_amount})")
            print(f"   [INFO] Status should remain 'pending' until booking_amount is paid")
        
        # Check user and referrer
        print(f"\n   {'='*76}")
        print(f"   USER AND REFERRER:")
        print(f"   {'='*76}")
        print(f"   User: {booking.user.username} (ID: {booking.user.id})")
        print(f"   Referred By: {booking.referred_by.username if booking.referred_by else 'None'} (ID: {booking.referred_by.id if booking.referred_by else 'N/A'})")
        print(f"   Referrer Was Distributor: {booking.referrer_was_distributor}")
        
        # Check if user is active buyer
        print(f"\n   User Active Buyer Status:")
        print(f"   - is_active_buyer: {booking.user.is_active_buyer}")
        
        # Check binary node
        try:
            from core.binary.models import BinaryNode
            user_node = BinaryNode.objects.get(user=booking.user)
            print(f"\n   Binary Node Info:")
            print(f"   - Node ID: {user_node.id}")
            print(f"   - Parent: {user_node.parent.user.username if user_node.parent else 'None'}")
            print(f"   - Side: {user_node.side}")
            print(f"   - Level: {user_node.level}")
            
            # Check parent node
            if user_node.parent:
                parent_node = user_node.parent
                print(f"\n   Parent Node Info (User {parent_node.user.id}):")
                print(f"   - Username: {parent_node.user.username}")
                print(f"   - Is Distributor: {parent_node.user.is_distributor}")
                print(f"   - Binary Commission Activated: {parent_node.binary_commission_activated}")
                print(f"   - Total Descendants: {parent_node.total_descendants}")
                print(f"   - Left Count: {parent_node.left_count}")
                print(f"   - Right Count: {parent_node.right_count}")
        except Exception as e:
            print(f"\n   [WARNING] Could not get binary node info: {e}")
    
except Booking.DoesNotExist:
    print(f"[ERROR] Booking with id {booking_id} NOT FOUND")

print(f"\n{'='*80}\n")

