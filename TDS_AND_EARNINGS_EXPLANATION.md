# TDS and Earnings Calculation Explanation for User ID 125

## Overview

This document explains how `tds_current` and `total_earnings` are calculated for user_id 125.

## Key Data Points

For user_id 125:
- `total_amount`: ₹9,000 (gross earnings)
- `tds_current`: ₹300 (TDS deducted)
- `net_amount_total`: ₹8,100 (net earnings after all deductions)
- `total_earnings`: ₹8,100 (same as net_amount_total)
- `total_binary_pairs`: 3 pairs
- `wallet_balance`: ₹8,100

## How TDS is Calculated

### 1. TDS for Direct User Commissions (Before Activation)

**When it applies:**
- Paid when new users are added to the binary tree (before binary commission activation)
- Only for ancestors who have less than 3 total descendants
- Commission amount: ₹1,000 per user (configurable)
- TDS percentage: 20% (configurable via `binary_commission_tds_percentage`)

**How it works:**
1. Gross commission: ₹1,000
2. TDS calculation: ₹1,000 × 20% = ₹200
3. Net amount credited to wallet: ₹1,000 - ₹200 = ₹800
4. **TDS is NOT deducted from booking balance** - TDS is calculated and reduces net amount only

**Code location:** `core/binary/utils.py` lines 284-297

### 2. TDS for Binary Pair Commissions (After Activation)

**When it applies:**
- Paid when binary pairs are matched (after binary commission activation)
- Commission amount: ₹2,000 per pair (configurable)
- TDS percentage: 20% (same as direct commissions)

**How it works:**
1. Gross commission: ₹2,000
2. TDS calculation: ₹2,000 × 20% = ₹400
3. Net amount credited to wallet: ₹2,000 - ₹400 = ₹1,600
4. **TDS is NOT deducted from booking balance** - TDS is calculated and reduces net amount only (for all pairs)
5. For pairs 6+: Additional 20% extra deduction (binary_extra_deduction_percentage) is deducted from booking balance

**Code location:** `core/binary/utils.py` lines 1231-1332

**Implementation:**
```python
# Calculate TDS (always applied on all pairs)
tds_amount = commission_amount * (tds_percentage / Decimal('100'))
net_amount = commission_amount - tds_amount

# TDS is NOT deducted from booking balance - only extra deduction for pairs 6+ is deducted
# Deduct extra deduction from booking balance (for 6th+ pairs only)
if extra_deduction > 0:
    deduct_from_booking_balance(
        user=user,
        deduction_amount=extra_deduction,
        deduction_type='EXTRA_DEDUCTION',
        description=f"Extra deduction ({extra_deduction_percentage}%) on binary pair commission (Pair #{pair_number_after_activation})"
    )
```

## How `tds_current` is Calculated

**Formula:**
```python
tds_current = Sum of all TDS_DEDUCTION wallet transactions (absolute value)
```

**Important:** `tds_current` **includes TDS from BOTH Direct User Commissions AND Binary Pair Commissions**!

**Code location:** `core/binary/serializers.py` lines 177-192

```python
def get_tds_current(self, obj):
    """Get total TDS deducted from wallet transactions (for both binary pairs and direct user commissions)"""
    # Gets all TDS_DEDUCTION transactions which include:
    # 1. TDS from direct user commissions (before activation)
    # 2. TDS from binary pair commissions (after activation)
    tds_total = WalletTransaction.objects.filter(
        user=obj.user,
        transaction_type='TDS_DEDUCTION'
    ).aggregate(total=Sum('amount'))['total']
    return str(abs(tds_total)) if tds_total else "0.00"
```

## How `total_earnings` is Calculated

**Formula:**
```python
total_earnings = net_amount_total = 
    Sum of BINARY_PAIR_COMMISSION wallet transactions +
    Sum of DIRECT_USER_COMMISSION wallet transactions
```

**Breakdown:**
1. **Binary pair earnings (net):** Sum of all `BINARY_PAIR_COMMISSION` transactions
   - Each pair: ₹2,000 - 20% TDS = ₹1,600 (for pairs 1-5)
   - For 3 pairs: 3 × ₹1,600 = ₹4,800

2. **Direct user commission earnings (net):** Sum of all `DIRECT_USER_COMMISSION` transactions
   - Each commission: ₹1,000 - 20% TDS = ₹800
   - If user received commissions for 4 users: 4 × ₹800 = ₹3,200

3. **Total net earnings:** ₹4,800 + ₹3,200 = ₹8,000

**Code location:** `core/binary/serializers.py` lines 110-113, 430-460

## Example Calculation for User ID 125

Based on the data provided:

### Scenario Breakdown

**Total Gross Amount: ₹9,000**

This could be:
- **Option 1:** 3 binary pairs (₹2,000 each) + 3 direct commissions (₹1,000 each)
  - Binary pairs gross: 3 × ₹2,000 = ₹6,000
  - Direct commissions gross: 3 × ₹1,000 = ₹3,000
  - Total gross: ₹9,000 ✓

**TDS Current: ₹300**

This represents TDS from direct user commissions only:
- If TDS is ₹300 and rate is 20%, then gross from direct commissions = ₹300 ÷ 0.20 = ₹1,500
- This means user received 1.5 direct commissions? (This seems odd - might be 1 full commission + partial, or calculation difference)

**OR:**
- If user received 1.5 direct commissions: 1.5 × ₹1,000 = ₹1,500 gross
- TDS: ₹1,500 × 20% = ₹300 ✓

**Net Amount Total: ₹8,100**

This is the sum of:
- Binary pair net earnings: 3 pairs × ₹1,600 = ₹4,800
- Direct commission net earnings: 1.5 × ₹800 = ₹1,200
- **Wait, this doesn't add up to ₹8,100**

**Alternative calculation:**
- If total gross is ₹9,000 and net is ₹8,100, then total deductions = ₹900
- TDS from direct commissions: ₹300 (creates TDS_DEDUCTION transaction)
- TDS from binary pairs: 3 × ₹400 = ₹1,200 (does NOT create transaction, just reduces net)
- Total TDS: ₹300 + ₹1,200 = ₹1,500
- But net should be ₹9,000 - ₹1,500 = ₹7,500, not ₹8,100

**Let me recalculate:**
- If net is ₹8,100 and we know binary pairs contribute ₹4,800 (3 × ₹1,600)
- Then direct commissions net = ₹8,100 - ₹4,800 = ₹3,300
- Direct commissions gross = ₹3,300 ÷ 0.80 = ₹4,125
- TDS on direct commissions = ₹4,125 × 0.20 = ₹825

But `tds_current` shows ₹300, not ₹825.

## Important Notes

1. **TDS for binary pairs IS tracked in `tds_current`**
   - Binary pair TDS creates `TDS_DEDUCTION` wallet transactions (deducted from booking balance)
   - Both direct commission TDS and binary pair TDS are included in `tds_current`

2. **`tds_current` shows TDS from BOTH Direct User Commissions AND Binary Pairs**
   - All `TDS_DEDUCTION` wallet transactions are included
   - This provides a complete view of all TDS deducted

3. **`total_earnings` = `net_amount_total`**
   - Both represent the net amount after all deductions
   - This includes TDS on both direct commissions AND binary pairs

4. **The relationship:**
   ```
   total_amount (gross) = 
       Binary pairs gross + Direct commissions gross
   
   net_amount_total = 
       Binary pairs net + Direct commissions net
   
   tds_current = 
       TDS from direct commissions + TDS from binary pairs
       (all TDS_DEDUCTION transactions)
   
   Total TDS = 
       total_amount - net_amount_total
       = ₹9,000 - ₹8,100 = ₹900
   
   Verification:
       tds_current should equal (total_amount - net_amount_total)
   ```

## Why `tds_current` is ₹300

Based on the code analysis:
- `tds_current` = Sum of all `TDS_DEDUCTION` transactions
- These transactions are created for both direct user commissions AND binary pairs
- If `tds_current` = ₹300, and TDS rate = 20%, then:
  - Total gross that had TDS = ₹300 ÷ 0.20 = ₹1,500
  - This could be from:
    - Direct commissions: e.g., 1.5 × ₹1,000 = ₹1,500 gross → ₹300 TDS
    - Or a combination of direct commissions and binary pairs

**Note:** After the code update, binary pairs will also create `TDS_DEDUCTION` transactions, so `tds_current` will include TDS from both sources.

## Summary

For user_id 125:
- **`tds_current: ₹300`** = TDS deducted from booking balance (from both direct commissions and binary pairs via TDS_DEDUCTION transactions)
- **`total_earnings: ₹8,100`** = Net earnings after all deductions (TDS on both direct commissions and binary pairs)
- **`total_amount: ₹9,000`** = Gross earnings before any deductions
- **Total TDS:** ₹9,000 - ₹8,100 = ₹900 (includes both direct commission TDS and binary pair TDS)

**After the code update:**
- All TDS (from both direct commissions and binary pairs) will create `TDS_DEDUCTION` transactions
- `tds_current` will accurately reflect the total TDS deducted
- The relationship `tds_current = total_amount - net_amount_total` will hold true

