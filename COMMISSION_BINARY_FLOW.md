# Commission and Binary Flow Documentation

## Overview

The system implements a two-phase commission structure:
1. **Direct User Commission (Referral Bonus)**: ₹1000 per user before activation
2. **Binary Pair Commission**: ₹2000 per pair after activation

---

## Phase 1: Direct User Commission (Before Activation)

### When It Triggers
- When a new user is added to the binary tree
- **Only if** the new user has completed at least one successful payment
- **Only for ancestors** who have **less than 3 total descendants**

### Commission Details
- **Amount**: ₹1000 (configurable via `direct_user_commission_amount`)
- **TDS**: 20% (₹200) deducted from booking balance
- **Net Amount**: ₹800 credited to wallet
- **Recipients**: ALL ancestors in the referral chain (not just direct parent)

### Flow Diagram

```
New User Added → Has Payment? → YES → Process Commission for All Ancestors
                                      ↓
                    For Each Ancestor:
                    ├─ Binary Commission Activated? → YES → Skip (No Commission)
                    ├─ Total Descendants >= 3? → YES → Skip (No Commission)
                    └─ Total Descendants < 3? → YES → Pay Commission
                                                      ├─ Calculate TDS (20%)
                                                      ├─ Credit ₹800 to Wallet
                                                      └─ Deduct ₹200 TDS from Booking
```

### Example Scenario

**User A's Tree:**
- User B added (left) → A gets ₹800
- User C added (right) → A gets ₹800
- User D added (left child of B) → A gets ₹800
  - **Total descendants = 3** → **Binary Commission Activates** ✅
  - `binary_commission_activated = True`
  - `activation_timestamp = D.created_at`

### Key Rules
1. ✅ Commission paid to **all ancestors** (entire referral chain)
2. ✅ Commission **stops immediately** when ancestor reaches 3 descendants
3. ✅ Uses **row locking** (`select_for_update()`) to prevent race conditions
4. ✅ Multiple safety checks to prevent duplicate payments
5. ✅ Commission only paid if user has successful payment

---

## Phase 2: Binary Pair Commission (After Activation)

### When It Triggers
- **Only after** binary commission is activated (3+ descendants)
- **Only for distributors** (`is_distributor = True`)
- **Only when** there's at least one unmatched member on **both** left and right sides
- **Manually triggered** via API: `POST /api/binary/pairs/check_pairs/`

### Pair Matching Rules

#### Strict Pairing Logic
- **Pair = 1 left-leg member + 1 right-leg member**
- **Two members on same leg (LL or RR) → NOT a pair**
- **Pre-activation members excluded**: Only members created at or after activation are eligible

#### Member Eligibility
- ✅ **Included**: Member that triggered activation (3rd member - D)
- ✅ **Included**: All members added after activation (E, F, G...)
- ❌ **Excluded**: Members created before activation (1st and 2nd - B, C)

### Commission Calculation

#### Base Amount
- **Gross**: ₹2000 per pair (configurable via `binary_pair_commission_amount`)

#### Deductions

1. **TDS (Tax Deducted at Source)**
   - **Rate**: 20% (₹400)
   - **Applied to**: All pairs
   - **Deducted from**: Booking balance (not wallet)

2. **Extra Deduction (6th+ Pairs)**
   - **Rate**: 20% (₹400)
   - **Applied to**: 6th pair and onwards
   - **Deducted from**: Booking balance (not wallet)
   - **Condition**: Only if user is **NOT Active Buyer**

3. **Active Buyer Requirement**
   - **Rule**: Non-Active Buyer distributors can only earn for **first 5 pairs**
   - **6th+ pairs**: Commission blocked until user becomes Active Buyer
   - **Active Buyer**: User with total paid bookings ≥ ₹5000

#### Net Amount Calculation

```
Pair 1-5 (Active Buyer):
  Gross: ₹2000
  TDS: ₹400
  Net: ₹1600 ✅

Pair 1-5 (Non-Active Buyer):
  Gross: ₹2000
  TDS: ₹400
  Net: ₹1600 ✅

Pair 6+ (Active Buyer):
  Gross: ₹2000
  TDS: ₹400
  Extra Deduction: ₹400
  Net: ₹1200 ✅

Pair 6+ (Non-Active Buyer):
  Gross: ₹2000
  TDS: ₹400
  Extra Deduction: ₹400
  Commission: BLOCKED ❌ (until Active Buyer)
```

### Daily Limit

- **Maximum pairs per day**: 10 pairs (configurable via `binary_daily_pair_limit`)
- **Excess members**: Carried forward to next day (long leg only)
- **Carry-forward**: Members from the side with more unmatched users

### Flow Diagram

```
Manual Pair Check API → User is Distributor? → YES → Binary Activated? → YES
                                                      ↓
                    Get Unmatched Users (Post-Activation Only)
                    ├─ Left Side: [D, F, H...] (excludes B)
                    └─ Right Side: [E, G, I...] (excludes C)
                                                      ↓
                    Both Sides Have Unmatched? → YES → Create Pair
                                                      ↓
                    Calculate Commission:
                    ├─ Pair Number (1st, 2nd, 3rd...)
                    ├─ TDS (20% = ₹400)
                    ├─ Extra Deduction (20% = ₹400 for 6th+)
                    ├─ Active Buyer Check (6th+ pairs)
                    └─ Daily Limit Check (max 10 pairs/day)
                                                      ↓
                    Create BinaryPair Record:
                    ├─ Status: 'matched'
                    ├─ Earning Amount: Net (after deductions)
                    └─ Commission Blocked: True/False
                                                      ↓
                    Deduct TDS & Extra from Booking Balance
                                                      ↓
                    Trigger Celery Task → Credit Net Amount to Wallet
                                                      ↓
                    Update Carry-Forward (if daily limit reached)
```

### Example Scenario

**User A's Tree After Activation:**
```
A (Distributor, Activated)
├─ B (left, T1) - EXCLUDED from pairing
├─ C (right, T2) - EXCLUDED from pairing
├─ D (left child of B, T3) - INCLUDED ✅
└─ E (right, T4) - INCLUDED ✅

Pair Check:
├─ Left post-activation: [D]
├─ Right post-activation: [E]
├─ Pair Created: D + E
├─ Gross: ₹2000
├─ TDS: ₹400 (deducted from booking)
├─ Net: ₹1600 (credited to wallet)
└─ Status: Processed ✅
```

---

## Complete Flow: User Registration to Commission

### Step-by-Step Process

```
1. User Registration
   ├─ User signs up with referral code
   └─ User placed in binary tree (automatic placement algorithm)

2. User Makes Payment
   ├─ Booking created
   ├─ Payment completed
   └─ Trigger: process_direct_user_commission()

3. Direct Commission Phase (Before Activation)
   ├─ Check: User has payment? → YES
   ├─ For each ancestor:
   │   ├─ Binary activated? → NO
   │   ├─ Total descendants < 3? → YES
   │   └─ Pay ₹800 (₹1000 - ₹200 TDS)
   └─ If ancestor reaches 3 descendants:
       ├─ Set binary_commission_activated = True
       ├─ Set activation_timestamp = new_user.created_at
       └─ Stop direct commissions for this ancestor

4. Binary Commission Phase (After Activation)
   ├─ User manually triggers pair check
   ├─ System finds unmatched members (post-activation only)
   ├─ Creates pair if both left and right available
   ├─ Calculates commission with deductions
   ├─ Deducts TDS/extra from booking balance
   └─ Credits net amount to wallet via Celery task
```

---

## Key Settings (PlatformSettings)

| Setting | Default | Description |
|---------|---------|-------------|
| `direct_user_commission_amount` | ₹1000 | Commission per user before activation |
| `binary_commission_activation_count` | 3 | Number of descendants to activate binary |
| `binary_pair_commission_amount` | ₹2000 | Commission per pair after activation |
| `binary_commission_tds_percentage` | 20% | TDS on all commissions |
| `binary_tds_threshold_pairs` | 5 | Pairs before extra deduction starts |
| `binary_extra_deduction_percentage` | 20% | Extra deduction for 6th+ pairs |
| `binary_daily_pair_limit` | 10 | Maximum pairs per day |

---

## Important Business Rules

### Commission Eligibility
1. ✅ **Only distributors** can earn commissions
2. ✅ **Direct commission**: Only if user has successful payment
3. ✅ **Binary commission**: Only after activation (3+ descendants)
4. ✅ **6th+ pairs**: Only for Active Buyers (or blocked)

### Pair Matching
1. ✅ **Strict left-right pairing**: Must have 1 left + 1 right
2. ✅ **Pre-activation exclusion**: B and C (1st, 2nd) excluded
3. ✅ **Post-activation inclusion**: D (3rd) and all subsequent members included
4. ✅ **Daily limit**: Max 10 pairs per day
5. ✅ **Carry-forward**: Excess members from long leg carried forward

### Deductions
1. ✅ **TDS**: Always 20% on all commissions (reduces net amount to wallet, NOT deducted from booking)
2. ✅ **Extra Deduction**: 20% on 6th+ pairs (deducted from booking balance)
3. ✅ **Net amount**: Credited to wallet after TDS (extra deduction already deducted from booking)

### Race Condition Protection
1. ✅ **Row locking**: `select_for_update()` prevents concurrent modifications
2. ✅ **Atomic transactions**: Ensures data consistency
3. ✅ **Multiple safety checks**: Prevents duplicate payments

---

## API Endpoints

### Direct Commission
- **Automatic**: Triggered when payment is completed
- **Function**: `process_direct_user_commission(referrer, new_user)`

### Binary Pair Commission
- **Manual**: `POST /api/binary/pairs/check_pairs/`
- **Function**: `check_and_create_pair(user)`
- **Task**: `pair_matched(pair_id)` (Celery async)

---

## Data Models

### BinaryNode
- `binary_commission_activated`: Boolean flag
- `activation_timestamp`: When activation occurred
- `left_count`: Total descendants on left
- `right_count`: Total descendants on right

### BinaryPair
- `left_user`: User from left side
- `right_user`: User from right side
- `pair_amount`: Gross commission (₹2000)
- `earning_amount`: Net commission (after deductions)
- `pair_number_after_activation`: Which pair (1st, 2nd, 3rd...)
- `commission_blocked`: Whether commission was blocked
- `is_carry_forward_pair`: Whether used carry-forward members

### BinaryCarryForward
- `side`: Long leg side ('left' or 'right')
- `initial_member_count`: Total members carried forward
- `matched_count`: How many have been matched
- `is_active`: Whether still active

---

## Summary

The commission system operates in two distinct phases:

1. **Before Activation (0-2 descendants)**:
   - Direct user commission: ₹800 per user
   - Paid to all ancestors
   - Stops at 3 descendants

2. **After Activation (3+ descendants)**:
   - Binary pair commission: ₹1600-₹1200 per pair
   - Only post-activation members eligible
   - Daily limit: 10 pairs
   - Active Buyer required for 6th+ pairs

The system ensures fair commission distribution, prevents duplicate payments, and enforces business rules through multiple validation layers.

