"""
Diagnostic script to check booking 296 and why payment creation is failing.
Run with: python manage.py shell < check_booking_296.py
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ev_backend.settings')
django.setup()

from core.booking.models import Booking
from decimal import Decimal

booking_id = 296
requested_amount = 74000

print(f"\n{'='*80}")
print(f"CHECKING BOOKING {booking_id} FOR PAYMENT VALIDATION")
print(f"{'='*80}\n")

try:
    booking = Booking.objects.get(id=booking_id)
    
    print(f"[OK] Booking {booking_id} EXISTS")
    print(f"   Booking Number: {booking.booking_number}")
    print(f"   User: {booking.user.username} (ID: {booking.user.id})")
    print(f"   Status: {booking.status}")
    print(f"\n   PAYMENT DETAILS:")
    print(f"   - Booking Amount: Rs.{booking.booking_amount}")
    print(f"   - Total Amount: Rs.{booking.total_amount}")
    print(f"   - Total Paid: Rs.{booking.total_paid}")
    print(f"   - Remaining Amount: Rs.{booking.remaining_amount}")
    
    print(f"\n   VALIDATION CHECK:")
    
    # Check what the max allowed amount would be
    if booking.total_paid == 0:
        max_allowed = float(booking.booking_amount)
        print(f"   - No payments made yet")
        print(f"   - Max allowed amount: Rs.{max_allowed:.2f} (booking_amount)")
    else:
        max_allowed = float(booking.remaining_amount)
        print(f"   - Payments already made: Rs.{booking.total_paid}")
        print(f"   - Max allowed amount: Rs.{max_allowed:.2f} (remaining_amount)")
    
    print(f"\n   REQUESTED AMOUNT: Rs.{requested_amount}")
    
    if requested_amount > max_allowed:
        print(f"   [ERROR] Requested amount (Rs.{requested_amount}) exceeds max allowed (Rs.{max_allowed:.2f})")
        print(f"   [INFO] This is why you're getting a 400 Bad Request error!")
        print(f"   [INFO] The error message should be: 'Amount cannot exceed remaining amount (Rs.{max_allowed:.2f})'")
    elif requested_amount <= 0:
        print(f"   [ERROR] Requested amount must be greater than 0")
    else:
        print(f"   [OK] Requested amount is valid!")
    
    # Check if booking is in a valid state for payment
    print(f"\n   BOOKING STATE:")
    if booking.status == 'cancelled':
        print(f"   [WARNING] Booking is cancelled - may not be eligible for payment")
    elif booking.status == 'completed':
        print(f"   [WARNING] Booking is completed - may not need more payments")
    elif booking.status == 'expired':
        print(f"   [WARNING] Booking is expired - may not be eligible for payment")
    else:
        print(f"   [OK] Booking status is valid for payment")
    
except Booking.DoesNotExist:
    print(f"[ERROR] Booking with id {booking_id} NOT FOUND")
    print(f"[INFO] This is why you're getting a 400 Bad Request error!")
    print(f"[INFO] The error message should be: 'Booking with id {booking_id} not found'")
    
    # Show some available bookings
    print(f"\n   Available bookings (showing first 5):")
    bookings = Booking.objects.all()[:5]
    for b in bookings:
        print(f"   - Booking {b.id}: {b.booking_number} (User: {b.user.username})")

print(f"\n{'='*80}\n")

