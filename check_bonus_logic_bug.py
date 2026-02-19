import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ev_backend.settings')
django.setup()

from core.booking.models import Booking, Payment
from core.users.models import User
from core.settings.models import PlatformSettings
from django.db.models import Sum

booking = Booking.objects.get(id=307)
user = booking.user

print("=" * 80)
print("CHECKING BONUS LOGIC BUG")
print("=" * 80)
print()

# What update_active_buyer_status() does:
print("STEP 1: What update_active_buyer_status() calculates:")
print("  It sums total_paid from all bookings (status='active' or 'completed')")
all_bookings = Booking.objects.filter(user=user, status__in=['active', 'completed'])
total_from_bookings = all_bookings.aggregate(total=Sum('total_paid'))['total'] or 0
print(f"  Sum of bookings.total_paid: Rs.{total_from_bookings}")
print()

# What it should check:
print("STEP 2: What it SHOULD check (actual payments):")
all_payments = Payment.objects.filter(
    booking__user=user,
    booking__status__in=['active', 'completed'],
    status='completed'
)
total_from_payments = sum(float(p.amount) for p in all_payments)
print(f"  Sum of actual payments: Rs.{total_from_payments}")
print()

# Activation amount
platform_settings = PlatformSettings.get_settings()
activation_amount = platform_settings.activation_amount
print(f"STEP 3: Activation threshold: Rs.{activation_amount}")
print()

print("STEP 4: Comparison:")
print(f"  Using bookings.total_paid: Rs.{total_from_bookings} >= Rs.{activation_amount}? {total_from_bookings >= activation_amount}")
print(f"  Using actual payments: Rs.{total_from_payments} >= Rs.{activation_amount}? {total_from_payments >= activation_amount}")
print()

print("=" * 80)
print("THE BUG:")
print("=" * 80)
print("update_active_buyer_status() checks:")
print("  total_paid (from bookings) >= activation_amount")
print()
print("But total_paid might already include bonuses from previous bookings!")
print("This creates a circular dependency:")
print("  1. Bonus is applied → increases total_paid")
print("  2. Next payment → checks total_paid (which includes bonus)")
print("  3. User qualifies even if actual payments < activation_amount")
print()
print("SOLUTION:")
print("  Should check actual payments, not bookings.total_paid")
print("  OR exclude bonuses when checking qualification")

