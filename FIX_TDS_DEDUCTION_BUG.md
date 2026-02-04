# Fix for Incorrect TDS Deduction from Booking Balance

## Problem

The system was incorrectly deducting TDS from booking balance for **all binary pairs** (1-5 and 6+). According to the business rules:

- **Pairs 1-5**: TDS should be calculated and reduce net amount, but **NOT deducted from booking balance**
- **Pairs 6+**: TDS should be deducted from booking balance (correct behavior)

## Solution

### Code Fix

The code has been updated in `core/binary/utils.py` to only deduct TDS from booking balance for pairs 6+:

```python
# Deduct TDS from booking balance (ONLY for 6th+ pairs, not for pairs 1-5)
if tds_amount > 0 and pair_number_after_activation > tds_threshold:
    deduct_from_booking_balance(...)
```

### Fix Existing Data

A management command has been created to fix existing bookings that were incorrectly affected:

**Command:** `fix_incorrect_tds_deductions`

**Location:** `core/binary/management/commands/fix_incorrect_tds_deductions.py`

## Usage

### 1. Dry Run (Recommended First)

Check what will be fixed without making changes:

```bash
python manage.py fix_incorrect_tds_deductions --dry-run
```

### 2. Fix All Affected Bookings

```bash
python manage.py fix_incorrect_tds_deductions
```

### 3. Fix Specific User

```bash
python manage.py fix_incorrect_tds_deductions --user-id 190
```

### 4. Fix Specific Pair

```bash
python manage.py fix_incorrect_tds_deductions --pair-id 123
```

### 5. Remove TDS Transactions (Optional)

By default, the command keeps the incorrect TDS_DEDUCTION transactions but marks them as reversed. To remove them completely:

```bash
python manage.py fix_incorrect_tds_deductions --remove-tds-transactions
```

## What the Command Does

1. **Finds all binary pairs 1-5** that have TDS_DEDUCTION transactions
2. **Reverses the TDS deduction** from booking balance:
   - Decreases `total_paid` by the TDS amount
   - Increases `remaining_amount` by the TDS amount
3. **Handles TDS transactions**:
   - Option 1 (default): Marks them as reversed in description
   - Option 2 (with flag): Removes them completely
4. **Updates booking status** if needed (if remaining_amount becomes 0)

## Example Output

```
================================================================================
FIX INCORRECT TDS DEDUCTIONS FOR PAIRS 1-5
================================================================================

Found 5 pairs to check (pairs 1-5)

  [DRY RUN] Would reverse TDS deduction for Pair 123 (User: user@example.com, Pair #1): 
    Rs 400.00 from booking EVKFURZLR6
    Current booking state: total_paid=5300.00, remaining_amount=68700.00
    After reversal: total_paid=4900.00, remaining_amount=69100.00
    TDS transactions to keep: 1

================================================================================
SUMMARY
================================================================================
Fixed (reversed TDS deductions): 5
Skipped (no TDS deduction found or no active booking): 0
Errors: 0
Total pairs checked: 5
```

## Important Notes

1. **Always run with `--dry-run` first** to see what will be changed
2. **The command is safe** - it only affects pairs 1-5 that have TDS deductions
3. **Booking status will be updated** if remaining_amount changes
4. **TDS transactions are kept by default** for audit trail (can be removed with flag)

## Verification

After running the command, verify:

1. Check booking `total_paid` - should be decreased by TDS amount
2. Check booking `remaining_amount` - should be increased by TDS amount
3. Check TDS_DEDUCTION transactions - should be marked as reversed (or removed)

## Related Files

- **Code fix**: `core/binary/utils.py` (lines 1323-1332)
- **Management command**: `core/binary/management/commands/fix_incorrect_tds_deductions.py`
- **Documentation**: `COMMISSION_BINARY_FLOW.md`, `TDS_AND_EARNINGS_EXPLANATION.md`

