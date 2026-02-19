# Active Buyer Bonus System - Current Structure

## Overview

The system provides a **₹5,000 company bonus** to users when they become **Active Buyers**. This bonus is automatically added to their booking's `total_paid` and reduces the `remaining_amount`.

---

## 1. Active Buyer Definition

### Qualification Criteria
- User's **actual payments** (excluding bonuses) across all active/completed bookings >= **₹5,000** (activation_amount)
- This is checked using **actual Payment records**, NOT `bookings.total_paid` (which may include bonuses)

### Key Point
- **Actual payments** = Sum of all `Payment` records with `status='completed'`
- **NOT** `bookings.total_paid` (which includes bonuses and may have inconsistencies)

---

## 2. Bonus Application Flow

### Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ 1. User Makes Payment                                        │
│    - Payment.save() is called (status='completed')          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Payment.save() calls booking.make_payment(amount)        │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. make_payment() updates booking:                          │
│    - booking.total_paid += payment_amount                   │
│    - booking.remaining_amount = total_amount - total_paid    │
│    - booking.save()                                         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. make_payment() calls:                                     │
│    booking.user.update_active_buyer_status(booking=self)    │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. update_active_buyer_status() calculates:                  │
│    - actual_payments_total = Sum of Payment records          │
│      (status='completed') across all bookings                │
│    - Checks: actual_payments_total >= activation_amount?     │
│    - Sets: is_active_buyer = True/False                      │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 6. If user JUST became active buyer:                         │
│    (was_active=False → is_active_buyer=True)                 │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 7. Calls process_active_buyer_bonus(user, booking)          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 8. process_active_buyer_bonus() verifies:                    │
│    - Bonus not already given (checks WalletTransaction)      │
│    - User qualifies (actual_payments >= activation_amount)   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ 9. Applies bonus:                                            │
│    - booking.total_paid += ₹5,000                            │
│    - booking.remaining_amount = total_amount - total_paid    │
│    - Updates booking status if fully paid                    │
│    - Creates WalletTransaction record (audit trail)           │
│    - booking.save()                                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. Code Structure

### 3.1 User Model (`core/users/models.py`)

**Function: `update_active_buyer_status(booking=None)`**

**What it does:**
- Calculates actual payments from `Payment` records (NOT `bookings.total_paid`)
- Checks if `actual_payments >= activation_amount` (₹5,000)
- Sets `is_active_buyer` flag
- If user just became active buyer, calls `process_active_buyer_bonus()`

**Key Code:**
```python
# Calculate from ACTUAL PAYMENTS, not bookings.total_paid
actual_payments_total = Payment.objects.filter(
    booking__user=self,
    booking__status__in=['active', 'completed'],
    status='completed'
).aggregate(total=models.Sum('amount'))['total'] or 0

self.is_active_buyer = actual_payments_total >= activation_amount

if not was_active and self.is_active_buyer:
    # User just became Active Buyer - apply bonus
    process_active_buyer_bonus(self, booking)
```

---

### 3.2 Booking Utils (`core/booking/utils.py`)

**Function: `process_active_buyer_bonus(user, booking)`**

**What it does:**
- Checks if bonus already given (prevents duplicates)
- Verifies user qualifies (actual payments >= ₹5,000)
- Adds ₹5,000 to `booking.total_paid`
- Recalculates `booking.remaining_amount`
- Creates audit trail (WalletTransaction)

**Key Code:**
```python
# Verify using ACTUAL PAYMENTS
actual_payments_total = Payment.objects.filter(
    booking__user=user,
    booking__status__in=['active', 'completed'],
    status='completed'
).aggregate(total=Sum('amount'))['total'] or 0

if actual_payments_total < activation_amount:
    return False  # User doesn't qualify

# Apply bonus
bonus_amount = Decimal('5000.00')
booking.total_paid += bonus_amount
booking.remaining_amount = booking.total_amount - booking.total_paid
booking.save()
```

---

### 3.3 Booking Model (`core/booking/models.py`)

**Function: `make_payment(amount, payment_id=None)`**

**What it does:**
- Processes payment and updates booking
- Syncs `total_paid` with actual payments (preserves bonuses)
- Calls `update_active_buyer_status()` after payment

**Key Features:**
- Preserves bonuses when syncing `total_paid`
- Accounts for bonuses in duplicate payment checks
- Updates booking status based on payments

---

### 3.4 Booking Serializer (`core/booking/serializers.py`)

**Functions: `get_total_paid()`, `get_remaining_amount()`, `get_bonus_amount()`**

**What they do:**
- `get_total_paid()`: Calculates payments + bonus for API response
- `get_remaining_amount()`: Calculates remaining after payments + bonus
- `get_bonus_amount()`: Shows bonus amount separately (₹5,000 or 0)

**Key Code:**
```python
def get_total_paid(self, obj):
    # Sum actual payments
    completed_payments_sum = sum(...)
    
    # Add bonus if exists
    if bonus_exists:
        bonus_amount = Decimal('5000.00')
    
    return str(completed_payments_sum + bonus_amount)

def get_bonus_amount(self, obj):
    # Returns "5000.00" if bonus applied, "0.00" otherwise
    if bonus_exists:
        return "5000.00"
    return "0.00"
```

---

## 4. Database Structure

### Tables Involved

**1. `bookings` table:**
- `total_paid`: Includes payments + bonuses (may have inconsistencies)
- `remaining_amount`: Calculated as `total_amount - total_paid`
- `status`: 'pending', 'active', 'completed'

**2. `payments` table:**
- `amount`: Actual payment amount
- `status`: 'pending', 'completed', 'failed', 'refunded'
- `booking_id`: Foreign key to booking

**3. `wallet_transactions` table:**
- `transaction_type`: 'ACTIVE_BUYER_BONUS'
- `amount`: ₹5,000
- `reference_id`: Booking ID
- `reference_type`: 'booking'
- **Note**: This is for audit only, NOT a wallet credit

**4. `users` table:**
- `is_active_buyer`: Boolean flag (True/False)

---

## 5. API Response Structure

### Bookings API (`/api/bookings/bookings/`)

**Response Fields:**
```json
{
  "id": 306,
  "total_paid": "9550.00",        // Payments + Bonus
  "remaining_amount": "49350.00",  // Total - (Payments + Bonus)
  "total_amount": "58900.00",
  "bonus_amount": "5000.00",      // NEW: Shows bonus separately
  "payment_status": "completed",
  ...
}
```

**Calculation:**
- `total_paid` = Actual payments + Bonus (if applied)
- `remaining_amount` = `total_amount` - `total_paid`
- `bonus_amount` = ₹5,000 if bonus applied, else 0

---

## 6. Key Rules & Safeguards

### 6.1 Bonus Application Rules

1. **Only Once Per User**
   - Checked via `WalletTransaction` records
   - Prevents duplicate bonuses

2. **Only When Qualifying**
   - User must have actual payments >= ₹5,000
   - Checked using `Payment` records, NOT `bookings.total_paid`

3. **Applied to Triggering Booking**
   - Bonus added to the booking that made user cross ₹5,000 threshold
   - Not necessarily the first booking

4. **Immediate Application**
   - Applied in same transaction as payment
   - Atomic operation (all or nothing)

### 6.2 Data Integrity Safeguards

1. **Payment Sync Logic**
   - `make_payment()` syncs `total_paid` with actual payments
   - **Preserves bonuses** when syncing
   - Prevents overwriting bonuses

2. **Duplicate Payment Prevention**
   - Checks if payment already processed
   - Accounts for bonuses in duplicate checks

3. **API Calculation**
   - Serializer calculates from payments + bonus
   - Doesn't rely on potentially inconsistent `bookings.total_paid`

---

## 7. Example Scenarios

### Scenario 1: User Qualifies for Bonus

**User: anamika@gmail.com**

1. **Payment 1: ₹4,000**
   - `total_paid`: ₹4,000
   - `is_active_buyer`: False (₹4,000 < ₹5,000)
   - Bonus: Not applied

2. **Payment 2: ₹550**
   - `total_paid`: ₹4,550 (after payment)
   - Check: ₹4,550 < ₹5,000 → Still not active buyer
   - **Wait...** Actually, if user has other bookings, total might be different

3. **Actually, let's check total across all bookings:**
   - If total actual payments >= ₹5,000:
     - `is_active_buyer`: True
     - Bonus applied: +₹5,000
     - Final `total_paid`: ₹9,550 (₹4,550 + ₹5,000)
     - Final `remaining_amount`: ₹49,350

### Scenario 2: User Doesn't Qualify

**User: nizamol007@gmail.com**

1. **Payment: ₹4,800**
   - Actual payments: ₹4,800
   - Check: ₹4,800 < ₹5,000
   - `is_active_buyer`: False
   - Bonus: **Should NOT be applied**

2. **But if bonus was incorrectly applied:**
   - `total_paid`: ₹9,800 (₹4,800 + ₹5,000)
   - This is a bug (now fixed)

---

## 8. Integration with Binary Commission

### Binary Commission Eligibility

**Function: `has_activation_payment(user, booking=None)`**

**What it checks:**
- Whether user has actual payments >= activation_amount
- Used to determine if user counts for binary commission
- **Now fixed** to check actual payments, not `bookings.total_paid`

**Impact:**
- Prevents incorrect commission credits
- Ensures only users with actual payments >= ₹5,000 count for commission

---

## 9. Current Status & Fixes

### ✅ Fixed Issues

1. **Bonus Qualification Logic**
   - Now checks actual payments, not `bookings.total_paid`
   - Prevents circular dependency

2. **API Response**
   - Shows bonus in `total_paid` and `remaining_amount`
   - Added `bonus_amount` field for transparency

3. **Binary Commission**
   - `has_activation_payment()` now checks actual payments
   - Prevents incorrect commission credits

4. **Payment Sync**
   - Preserves bonuses when syncing `total_paid`
   - Accounts for bonuses in duplicate checks

### ⚠️ Known Issues

1. **Database Inconsistencies**
   - Some bookings may have incorrect `total_paid` values
   - Extra amounts (like ₹550 in booking 306) need investigation
   - API response is correct (calculates from payments + bonus)

2. **Past Incorrect Bonuses**
   - Some users may have received bonuses incorrectly
   - Need audit and potential reversal

---

## 10. Summary

### How It Works Now

1. **User makes payment** → `Payment.save()` → `booking.make_payment()`
2. **Check qualification** → `update_active_buyer_status()` checks actual payments
3. **Apply bonus** → If qualifies, `process_active_buyer_bonus()` adds ₹5,000
4. **Update booking** → `total_paid` increases, `remaining_amount` decreases
5. **API response** → Shows payments + bonus, with `bonus_amount` field

### Key Principles

- ✅ **Actual payments** determine qualification (not `bookings.total_paid`)
- ✅ **Bonus applied once** per user (checked via audit trail)
- ✅ **Bonus reduces remaining balance** (added to `total_paid`)
- ✅ **API shows correct values** (calculated from payments + bonus)
- ✅ **Bonus preserved** during payment sync operations

---

## 11. Testing

To verify the system works correctly:

1. **Check user qualification:**
   ```python
   from core.users.models import User
   user = User.objects.get(id=250)
   user.update_active_buyer_status()
   print(f"is_active_buyer: {user.is_active_buyer}")
   ```

2. **Check API response:**
   ```python
   from core.booking.serializers import BookingSerializer
   serializer = BookingSerializer(booking)
   print(serializer.data['bonus_amount'])
   print(serializer.data['total_paid'])
   ```

3. **Check actual payments:**
   ```python
   from core.booking.models import Payment
   payments = Payment.objects.filter(booking__user=user, status='completed')
   total = sum(float(p.amount) for p in payments)
   print(f"Actual payments: {total}")
   ```

---

## End of Document

