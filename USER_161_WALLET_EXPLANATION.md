# Wallet and Earnings Explanation for User ID 161

## Overview
This document explains the difference between `wallet_balance` and `total_earnings` for user_id 161 (Unnikrishnan K), and details about payment transactions.

## Key Data Points

For user_id 161:
- **wallet_balance**: ₹3,600 (current available balance)
- **total_earnings**: ₹4,800 (total net earnings from commissions)
- **total_amount**: ₹4,000 (gross earnings before TDS)
- **tds_current**: ₹800 (total TDS deducted)
- **net_amount_total**: ₹4,800 (net earnings after TDS)
- **total_binary_pairs**: 1 pair
- **binary_commission_activated**: true (activated on 2026-01-29)

## Understanding the Difference: ₹1,200

**Difference = total_earnings - wallet_balance = ₹4,800 - ₹3,600 = ₹1,200**

This ₹1,200 difference indicates that **₹1,200 has been deducted from the wallet** through one or more of the following transaction types:

### Possible Deduction Types:

1. **PAYOUT** - Withdrawal requests
   - When a user requests a payout, the full requested amount is deducted from wallet immediately
   - Creates a negative `PAYOUT` transaction in wallet
   - Example: If user requested ₹1,200 payout, wallet balance reduces by ₹1,200

2. **EMI_DEDUCTION** - Automatic EMI payments
   - For non-Active Buyer distributors: 20% EMI deduction from 6th+ binary pair earnings
   - However, user 161 is Active Buyer (`is_active_buyer: false` but `is_distributor: true`)
   - Only 1 binary pair, so EMI deduction unlikely unless from other sources

3. **RESERVE_DEDUCTION** - Reserve fund deductions
   - System-level deductions for reserve funds

4. **Other Deductions** - Any other negative transactions

## How `wallet_balance` is Calculated

`wallet_balance` = Sum of ALL wallet transactions **EXCEPT**:
- `REFERRAL_BONUS` (removed feature)
- `TDS_DEDUCTION` (deducted from booking balance, not wallet)
- `EXTRA_DEDUCTION` (deducted from booking balance, not wallet)

**Included in wallet_balance:**
- ✅ `BINARY_PAIR_COMMISSION` (credited - positive)
- ✅ `DIRECT_USER_COMMISSION` (credited - positive)
- ✅ `BINARY_INITIAL_BONUS` (credited - positive)
- ✅ `PAYOUT` (deducted - negative)
- ✅ `EMI_DEDUCTION` (deducted - negative)
- ✅ `RESERVE_DEDUCTION` (deducted - negative)
- ✅ `DEPOSIT` (credited - positive)
- ✅ `REFUND` (credited - positive)

## How `total_earnings` is Calculated

`total_earnings` = Sum of **ONLY** earnings transactions:
- `BINARY_PAIR_COMMISSION` (net amount after TDS)
- `DIRECT_USER_COMMISSION` (net amount after TDS)
- `BINARY_INITIAL_BONUS` (net amount after TDS)

**Key Point:** `total_earnings` represents **gross earnings** (what you've earned), while `wallet_balance` represents **current available balance** (what you can spend/withdraw).

## TDS and Net Amount Calculation

### For Binary Pair Commissions:
1. **Gross Commission**: ₹2,000 per pair (configurable)
2. **TDS (20%)**: ₹2,000 × 20% = ₹400
3. **Net Amount Credited**: ₹2,000 - ₹400 = ₹1,600

### For Direct User Commissions (Before Activation):
1. **Gross Commission**: ₹1,000 per user (configurable)
2. **TDS (20%)**: ₹1,000 × 20% = ₹200
3. **Net Amount Credited**: ₹1,000 - ₹200 = ₹800

### For User 161:
- **total_amount**: ₹4,000 (gross earnings)
- **tds_current**: ₹800 (20% of ₹4,000)
- **net_amount_total**: ₹4,800 (this seems to include initial bonus or other earnings)

**Note:** The `net_amount_total` of ₹4,800 being higher than `total_amount` of ₹4,000 suggests there might be:
- Binary Initial Bonus included (which may not be counted in `total_amount`)
- Or a calculation discrepancy that needs investigation

## Binary Tree Structure for User 161

```
Unnikrishnan K (User 161) - Level 0
├── Left Child: Rubina Mol (User 162) - Level 1
│   └── Right Child: Anupriya Raj (User 165) - Level 2
└── Right Child: Anamika Soman (User 163) - Level 1

Left Count: 2 (Rubina + Anupriya)
Right Count: 1 (Anamika)
```

## Binary Commission Activation

- **Activated**: Yes (on 2026-01-29 at 09:21:34)
- **Activation Count Setting**: 2 (not the default 3)
- **Activation Requirement**: 2 descendants needed to activate
- **Status**: User has 3 total descendants, but activation happened when 2nd member was added

## How the ₹1,600 Binary Pair Commission Was Earned

### Timeline of Events:

1. **1st Member Added** (09:17:40):
   - **Rubina Mol** (User 162) added to **LEFT** side
   - Created at: 2026-01-29 09:17:40
   - Status: Pre-activation member (will be EXCLUDED from pairing)

2. **2nd Member Added** (09:20:47):
   - **Anamika Soman** (User 163) added to **RIGHT** side
   - Created at: 2026-01-29 09:20:47
   - **ACTIVATION TRIGGERED** (activation_count = 2 reached)
   - Activation timestamp: 2026-01-29 09:21:34 (set to 2nd member's created_at)
   - Status: Post-activation member (ELIGIBLE for pairing)

3. **3rd Member Added** (15:04:44):
   - **Anupriya Raj** (User 165) added to **LEFT** side (child of Rubina)
   - Created at: 2026-01-29 15:04:44
   - Status: Post-activation member (ELIGIBLE for pairing)

### Pair Formation Logic:

**Key Rule**: Only members created **at or after activation** are eligible for pairing.

- ✅ **Anamika** (right, created 09:20:47) - Eligible (created_at >= activation_timestamp)
- ✅ **Anupriya** (left, created 15:04:44) - Eligible (created_at >= activation_timestamp)
- ❌ **Rubina** (left, created 09:17:40) - NOT Eligible (created_at < activation_timestamp)

### The Pair That Generated ₹1,600:

When `check_and_create_pair()` was called (manually via API or automatically):
- **Left member**: Anupriya Raj (User 165) - eligible
- **Right member**: Anamika Soman (User 163) - eligible
- **Pair created**: Anupriya (left) + Anamika (right)
- **Commission**: ₹2,000 gross - ₹400 TDS = **₹1,600 net**

### Why Rubina Wasn't Used:

Rubina (1st member) was created **before activation** (09:17:40 < 09:21:34), so she is **excluded** from pairing according to the system rules. Only the 2nd member (Anamika) and 3rd member (Anupriya) were eligible because they were created at or after the activation timestamp.

## Summary: How ₹1,600 Was Earned

**Question**: If activation count is 2 and user only has 3 descendants, how did they get ₹1,600 (binary pair commission) if no pair was created after activation?

**Answer**: 
1. **Activation happened** when 2nd member (Anamika) was added
2. **At activation time**: Only Anamika (right) was eligible for pairing (Rubina was excluded as pre-activation)
3. **No pair possible** immediately after activation (need both left AND right eligible members)
4. **When 3rd member (Anupriya) was added**: Now both Anamika (right) and Anupriya (left) were eligible
5. **Pair was formed**: Anupriya (left) + Anamika (right) = ₹1,600 commission

**Key Point**: The pair was NOT created "after 2 members" - it was created when the 3rd member was added, using the 2nd member (who triggered activation) and the 3rd member (who was added after activation).

## Last Payment Transaction

To find the **last payment transaction**, you need to check:

1. **Wallet Transactions** - Query all transactions for user 161:
   ```python
   WalletTransaction.objects.filter(user_id=161).order_by('-created_at')
   ```

2. **Payout Records** - Check if there are any payout requests:
   ```python
   Payout.objects.filter(user_id=161).order_by('-created_at')
   ```

3. **Transaction Types to Check**:
   - `PAYOUT` - Most likely source of ₹1,200 deduction
   - `EMI_DEDUCTION` - If EMI was auto-deducted
   - `RESERVE_DEDUCTION` - If reserve fund deduction occurred

## Recommended Actions

1. **Query Wallet Transactions**:
   - Get all transactions for user 161
   - Filter for negative transactions (PAYOUT, EMI_DEDUCTION, etc.)
   - Sum negative transactions to verify ₹1,200 deduction

2. **Check Payout History**:
   - Query `Payout` model for user 161
   - Check status (pending/processing/completed)
   - Verify payout amounts match deductions

3. **Verify Calculations**:
   - Confirm `total_amount` calculation
   - Verify `net_amount_total` includes all earnings types
   - Check if Binary Initial Bonus is included in calculations

## Summary

- **Total Earnings**: ₹4,800 (what you've earned from commissions)
- **Current Wallet Balance**: ₹3,600 (what's available now)
- **Difference**: ₹1,200 (withdrawn/deducted)
- **Most Likely Cause**: Payout request of ₹1,200

The difference indicates that ₹1,200 was withdrawn from the wallet, most likely through a payout request. To get exact details, query the `WalletTransaction` and `Payout` tables for user 161.

