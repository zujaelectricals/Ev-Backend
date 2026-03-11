# Non-Active Buyer Commission Flow (Example Parameters)

**Scenario parameters:**
- `binary_commission_activation_count` = **2** (binary commission activates after 2 active direct referrals)
- `max_earnings_before_active_buyer` = **4** (non-active can earn only for pairs 1–4; pair 5+ blocked until Active Buyer)
- `max_commission_before_active_buyer_amount` = **₹10,000** (total commission cap while non-active; partial credit when near cap)
- `binary_daily_pair_limit` = **5** (max 5 pairs per day after activation)
- `direct_user_commission_amount` = ₹1000, `binary_pair_commission_amount` = ₹2000 (examples; TDS applies)

---

## Phase 1: Distributor, Not Yet Active Buyer

**State:** User is a distributor (`is_distributor=True`) but **not** an Active Buyer (`is_active_buyer=False`): total actual payments on their bookings < `activation_amount`.

### 1.1 Before binary activation (fewer than 2 active direct referrals)

- They can still earn **direct user commission** for each direct referral who has activation payment (e.g. ₹1000 − TDS per referral).
- Each direct commission counts toward the **₹10,000 cap**.
- They **cannot** earn binary pair commission yet (binary not activated).

### 1.2 Binary activation (2nd active direct referral)

- When the **2nd** direct referral gets activation payment:
  - **Direct commission** for that 2nd referral is credited (counts toward ₹10k cap).
  - **Binary commission activates** (2 ≥ activation_count).
  - Pair matching can start; pairs are created and may earn commission subject to the rules below.

### 1.3 After binary activation – pair and amount limits (still non-active)

**Pair limit (non-active):**

- Only **pairs 1–4** (after activation) can earn commission.
- **Pair 1** after activation: commission is **not** credited (business rule: first pair after activation no commission).
- **Pairs 2, 3, 4** after activation: commission is credited **if** under the amount cap and under daily limit.
- **Pair 5 and above:** commission is **blocked** until the user becomes an Active Buyer. Pair may still be created/matched for tree logic, but no wallet credit.

**Amount cap (₹10,000):**

- Total commission from **direct + binary + initial bonus** (only what was credited while non-active) is capped at **₹10,000**.
- When total is already ₹10,000: no further credit until they become Active Buyer.
- **Partial credit** when near cap, e.g.:
  - Total so far ₹9,700; next commission ₹1,000 → only **₹300** is credited (total becomes ₹10,000).

**Daily limit:**

- At most **5 pairs per day** (for the user who earns the commission). Applies regardless of active/non-active.

**Example (non-active, after 2 direct referrals):**

1. Direct 1: ₹1000 − TDS → e.g. ₹800 credited. Total ≈ ₹800.
2. Direct 2: ₹800 credited. Binary activates. Total ≈ ₹1,600.
3. Pair 1 (after activation): no commission (first-pair rule). Total still ≈ ₹1,600.
4. Pairs 2, 3, 4: e.g. ₹1,600 each (after TDS) → total grows. If total reaches ₹10,000, next commission is capped or zero.
5. Pair 5: **blocked** for non-active (exceeds `max_earnings_before_active_buyer` = 4). No commission until they become Active Buyer.

---

## Phase 2: User Becomes Active Buyer

**Trigger:** Their total **actual payments** (on bookings) reach or exceed `activation_amount` (e.g. ₹5,000).

**What happens:**

- `is_active_buyer` → `True`.
- `active_buyer_since` is set to that moment (used for “future placements only” for pair 5+).

**From this point:**

- **₹10,000 cap is no longer applied.** All new commission (direct and binary) is credited in full, subject only to other rules (daily limit, TDS, etc.).
- **Pair 5 and above** can now earn commission, but **only for “future placements”**:
  - For pair 5+, only nodes (members) **placed in the tree after `active_buyer_since`** are used for matching.
  - Pairs 5+ do **not** use members placed before they became Active Buyer.
- **Daily limit** (5 pairs per day) still applies.
- Long/weak leg and carry-forward rules apply as usual.

So: commission “resumes” only for **new** placements after they become Active Buyer, not for old placements that were waiting in the tree.

---

## Flow Summary (Your Parameters)

| Parameter                         | Value   | Effect |
|----------------------------------|---------|--------|
| activation_count                  | 2       | Binary commission activates after 2 active direct referrals. |
| max_earnings_before_active_buyer  | 4       | Non-active can earn only for pairs 1–4; pair 5+ blocked until Active Buyer. |
| max_commission_before_active_buyer_amount | ₹10,000 | Total commission cap while non-active; partial credit when near cap. |
| binary_daily_pair_limit          | 5       | Max 5 pairs per day (for the earning user). |

**Non-active:**

1. Earn direct commission per active direct referral (counts toward ₹10k).
2. After 2 such referrals, binary activates; pair 1 = no commission; pairs 2–4 can earn, within ₹10k cap and daily limit 5.
3. Once total commission (direct + binary + initial bonus) reaches ₹10,000, no more credit until Active Buyer.
4. Pair 5+ do not pay commission until they become Active Buyer.

**After becoming Active Buyer:**

1. No ₹10k cap; full commission for all new direct and binary earnings.
2. Pair 5+ pay commission only using members placed **after** `active_buyer_since` (future placements only).
3. Daily limit 5 still applies; long/weak leg and carry-forward unchanged.
