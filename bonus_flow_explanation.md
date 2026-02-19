# Active Buyer Bonus Flow - When Bonus is Applied

## Complete Flow Diagram

```
1. User makes a payment
   ↓
2. Payment.save() is called (status='completed')
   ↓
3. Payment.save() calls booking.make_payment(amount, payment_id)
   ↓
4. make_payment() updates booking:
   - booking.total_paid += amount
   - booking.remaining_amount = booking.total_amount - booking.total_paid
   - booking.save()
   ↓
5. make_payment() calls booking.user.update_active_buyer_status(booking=self)
   ↓
6. update_active_buyer_status() calculates:
   - total_paid = Sum of all bookings' total_paid (status='active' or 'completed')
   - Checks: total_paid >= activation_amount (₹5000)?
   ↓
7. If user JUST became active buyer (was_active=False, now is_active_buyer=True):
   ↓
8. Calls process_active_buyer_bonus(user, booking)
   ↓
9. process_active_buyer_bonus() does:
   - Checks if bonus already given (prevents duplicates)
   - Verifies user qualifies (total_paid >= activation_amount)
   - Adds ₹5000 to booking.total_paid
   - Recalculates: booking.remaining_amount = booking.total_amount - booking.total_paid
   - Updates booking status if fully paid
   - Creates WalletTransaction record (for audit)
   - booking.save()
   ↓
10. Bonus is now reflected in:
    - booking.total_paid (includes ₹5000 bonus)
    - booking.remaining_amount (reduced by ₹5000)
    - API response (via serializer)
```

## Key Points

### When Bonus is Applied:
- **Immediately** when user becomes an Active Buyer
- **Trigger**: Payment that makes total_paid >= ₹5000
- **Timing**: Same transaction as the payment processing
- **Booking**: Applied to the booking that triggered the active buyer status

### Conditions for Bonus:
1. User's total_paid (across all active/completed bookings) >= activation_amount (₹5000)
2. User was NOT an active buyer before this payment
3. User becomes an active buyer after this payment
4. Bonus has NOT been given before (checked via WalletTransaction)

### What Happens:
1. **total_paid increases by ₹5000**
   - Example: ₹4550 (payments) → ₹9550 (payments + bonus)

2. **remaining_amount decreases by ₹5000**
   - Example: ₹54350 → ₹49350

3. **Booking status may change**
   - If remaining_amount <= 0, booking becomes 'completed'

4. **Audit trail created**
   - WalletTransaction record with type='ACTIVE_BUYER_BONUS'

## Example Scenario

**User: anamika@gmail.com**
- Makes payment: ₹4000
  - total_paid: ₹4000
  - remaining_amount: ₹54900
  - is_active_buyer: False (₹4000 < ₹5000)
  
- Makes payment: ₹550
  - total_paid: ₹4550 (after payment)
  - remaining_amount: ₹54350
  - **Now total_paid >= ₹5000, so:**
    - is_active_buyer: True
    - Bonus applied: +₹5000
    - **Final total_paid: ₹9550**
    - **Final remaining_amount: ₹49350**

## Important Notes

1. **Bonus is applied to the booking that triggered active buyer status**
   - Not necessarily the first booking
   - The booking that made total_paid cross the ₹5000 threshold

2. **Bonus is applied only once per user**
   - Checked via WalletTransaction records
   - Prevents duplicate bonuses

3. **Bonus is applied in the same transaction as payment**
   - Atomic operation
   - Either both succeed or both fail

4. **API reflects bonus immediately**
   - Serializer calculates: payments + bonus
   - Shows correct total_paid and remaining_amount

