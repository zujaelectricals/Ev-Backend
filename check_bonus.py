import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ev_backend.settings')
django.setup()

from core.wallet.models import WalletTransaction
from core.users.models import User
from core.booking.models import Booking, Payment

user = User.objects.get(id=250)
print(f"User: {user.email}")
print(f"is_active_buyer: {user.is_active_buyer}")

# Check bonuses
bonuses = WalletTransaction.objects.filter(user=user, transaction_type='ACTIVE_BUYER_BONUS')
print(f"\nActive buyer bonus transactions: {bonuses.count()}")
for b in bonuses:
    print(f"  ID {b.id}: Amount={b.amount}, Booking ID={b.reference_id}, Date={b.created_at}")

# Check booking
booking = Booking.objects.get(id=306)
print(f"\nBooking 306:")
print(f"  total_paid: {booking.total_paid}")
print(f"  booking_amount: {booking.booking_amount}")

# Check payments
payments = Payment.objects.filter(booking=booking, status='completed')
total_payments = sum(float(p.amount) for p in payments)
print(f"  Sum of payments: {total_payments}")
print(f"  Difference (bonus + extra): {float(booking.total_paid) - total_payments}")

print(f"\nPayments:")
for p in payments:
    print(f"  Payment {p.id}: {p.amount} on {p.payment_date}")

