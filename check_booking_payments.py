"""
Diagnostic script to check booking 296 payments and total_paid calculation.
Run with: python check_booking_payments.py
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ev_backend.settings')
django.setup()

from core.booking.models import Booking, Payment
from decimal import Decimal

booking_id = 296

print(f"\n{'='*80}")
print(f"CHECKING BOOKING {booking_id} PAYMENTS AND TOTAL_PAID")
print(f"{'='*80}\n")

try:
    booking = Booking.objects.get(id=booking_id)
    
    print(f"Booking {booking_id}: {booking.booking_number}")
    print(f"   Total Amount: Rs.{booking.total_amount}")
    print(f"   Booking Amount: Rs.{booking.booking_amount}")
    print(f"   Total Paid (from DB): Rs.{booking.total_paid}")
    print(f"   Remaining Amount: Rs.{booking.remaining_amount}")
    print(f"   Status: {booking.status}")
    
    print(f"\n   {'='*76}")
    print(f"   PAYMENT RECORDS:")
    print(f"   {'='*76}\n")
    
    payments = Payment.objects.filter(booking=booking).order_by('payment_date')
    
    if not payments.exists():
        print(f"   [WARNING] No payment records found!")
    else:
        total_from_payments = Decimal('0')
        completed_payments_sum = Decimal('0')
        
        for i, payment in enumerate(payments, 1):
            status_indicator = "[COMPLETED]" if payment.status == 'completed' else f"[{payment.status.upper()}]"
            print(f"   {i}. Payment ID: {payment.id}")
            print(f"      Transaction ID: {payment.transaction_id or 'N/A'}")
            print(f"      Amount: Rs.{payment.amount}")
            print(f"      Status: {status_indicator}")
            print(f"      Method: {payment.payment_method}")
            print(f"      Date: {payment.payment_date}")
            if payment.completed_at:
                print(f"      Completed At: {payment.completed_at}")
            print()
            
            total_from_payments += Decimal(str(payment.amount))
            if payment.status == 'completed':
                completed_payments_sum += Decimal(str(payment.amount))
        
        print(f"   {'='*76}")
        print(f"   SUMMARY:")
        print(f"   {'='*76}")
        print(f"   Total from ALL payments: Rs.{total_from_payments}")
        print(f"   Total from COMPLETED payments only: Rs.{completed_payments_sum}")
        print(f"   Booking.total_paid (from DB): Rs.{booking.total_paid}")
        print()
        
        if abs(completed_payments_sum - Decimal(str(booking.total_paid))) > Decimal('0.01'):
            print(f"   [ERROR] MISMATCH DETECTED!")
            print(f"   - Completed payments sum: Rs.{completed_payments_sum}")
            print(f"   - Booking.total_paid: Rs.{booking.total_paid}")
            print(f"   - Difference: Rs.{abs(completed_payments_sum - Decimal(str(booking.total_paid)))}")
            print()
            print(f"   [INFO] This indicates payments are being counted incorrectly!")
            print(f"   [INFO] The booking.total_paid should equal the sum of completed payments.")
        else:
            print(f"   [OK] Booking.total_paid matches sum of completed payments!")
        
        if abs(total_from_payments - completed_payments_sum) > Decimal('0.01'):
            print(f"   [INFO] There are non-completed payments totaling Rs.{total_from_payments - completed_payments_sum}")
    
except Booking.DoesNotExist:
    print(f"[ERROR] Booking with id {booking_id} NOT FOUND")

print(f"\n{'='*80}\n")

