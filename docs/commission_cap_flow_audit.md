# Commission Cap (₹10k Non-Active Buyer) – Flow Audit

This document confirms that **no other flows are broken** by the non-active buyer commission cap. All commission **credits** go through `add_wallet_balance` (where the cap and `credited_while_non_active_buyer` are applied), and other flows either do not credit commission or are reversals/deductions.

---

## 1. Commission credit paths (must apply cap)

| Location | Transaction type | How it credits | Cap applied? |
|----------|------------------|----------------|--------------|
| **core/binary/utils.py** | DIRECT_USER_COMMISSION | `add_wallet_balance` in `process_direct_user_commission` | Yes |
| **core/binary/utils.py** | BINARY_INITIAL_BONUS | `add_wallet_balance` in `process_binary_initial_bonus` | Yes |
| **core/binary/utils.py** | BINARY_PAIR_COMMISSION | `add_wallet_balance` in `check_and_create_pair` (with at-cap pre-check) | Yes |
| **core/binary/tasks.py** | BINARY_PAIR_COMMISSION | `add_wallet_balance` in `pair_matched` (with at-cap pre-check) | Yes |
| **core/binary/tasks.py** | BINARY_PAIR_COMMISSION | `add_wallet_balance` in recovery path (with at-cap check) | Yes |
| **core/binary/tasks.py** | BINARY_PAIR_COMMISSION | `add_wallet_balance` in `fix_missing_wallet_transactions` (with at-cap check) | Yes |
| **core/booking/tasks.py** | (indirect) | `process_retroactive_commissions` → `process_direct_user_commission` → `add_wallet_balance` | Yes |

All of the above go through `add_wallet_balance`, so the ₹10k cap and partial credit apply, and `credited_while_non_active_buyer` is set when the user is non-active.

---

## 2. Management commands that credit commission

| Command | How it credits | Cap applied? |
|---------|----------------|--------------|
| **fix_missing_direct_commissions** | `add_wallet_balance` (DIRECT_USER_COMMISSION) | Yes |
| **fix_activation_and_commissions** | `add_wallet_balance` (DIRECT_USER_COMMISSION) | Yes |
| **backfill_initial_bonus** | `process_binary_initial_bonus` → `add_wallet_balance` | Yes |

Retroactive/fix credits correctly respect the cap.

---

## 3. Flows that do NOT credit commission (unchanged)

| Location | What it does | Why not affected |
|----------|----------------|-------------------|
| **core/booking/utils.py** | `WalletTransaction.objects.create(ACTIVE_BUYER_BONUS, amount=bonus_amount)` | ACTIVE_BUYER_BONUS is not in the cap list; only records bonus applied to booking (balance unchanged). |
| **core/booking/views.py** | `add_wallet_balance(..., REFUND)` | REFUND is not commission; cap only applies to DIRECT_USER_COMMISSION, BINARY_PAIR_COMMISSION, BINARY_INITIAL_BONUS. |
| **core/wallet/views.py** | `add_wallet_balance(..., REFUND)` | Same. |
| **core/payout/tasks.py** | `add_wallet_balance(..., REFUND)` | Same (refund for failed payout). |
| **core/wallet/tasks.py** | `add_wallet_balance(..., transaction_type=...)` | Generic task; if called with a commission type, cap applies (correct). |

---

## 4. Reversals / deductions (do not need cap)

These **deduct** (reverse) commission. They use `deduct_wallet_balance` or similar and create **negative** transactions. They do not set `credited_while_non_active_buyer` (default False), and the cap logic only **sums positive** credits with `credited_while_non_active_buyer=True`, so reversals do not affect the cap. No change needed.

| Location | What it does |
|----------|----------------|
| **fix_user_202_active_buyer_pairs** | `deduct_wallet_balance(BINARY_PAIR_COMMISSION)` to reverse commission. |
| **fix_non_active_extra_pairs** | `deduct_wallet_balance(BINARY_PAIR_COMMISSION)` to reverse. |
| **fix_subsequent_day_pair_reversal** | `deduct_wallet_balance(BINARY_PAIR_COMMISSION)` to reverse. |
| **fix_overpaid_direct_commissions** | `deduct_wallet_balance(DIRECT_USER_COMMISSION)` to reverse. |

---

## 5. WalletTransaction creates inside add_wallet_balance

| Branch | Types | credited_while_non_active_buyer |
|--------|--------|----------------------------------|
| TDS_DEDUCTION / EXTRA_DEDUCTION | tracking only, no balance change | Not passed → default False (correct). |
| EMI_DEDUCTION | legacy BINARY_PAIR | Not passed → default False (correct). |
| Credit (final branch) | All types including commission | Set to `True` only for DIRECT_USER_COMMISSION, BINARY_PAIR_COMMISSION, BINARY_INITIAL_BONUS when user is non-active and amount credited > 0. |

---

## 6. deduct_wallet_balance

Creates a transaction with **negative** amount; does not pass `credited_while_non_active_buyer` (default False). Correct: reversals are not “credits” and should not increase cap usage.

---

## 7. Recalculate wallet balances

**core/wallet/management/commands/recalculate_wallet_balances.py** only **reads** `WalletTransaction` and updates `Wallet.balance`, `total_earned`, `total_withdrawn`. It does **not** create any `WalletTransaction`. No change needed.

---

## 8. API / serializers

- **WalletTransactionSerializer** uses an explicit `fields` list and does **not** include `credited_while_non_active_buyer`. API response is unchanged; no breaking change.
- **PlatformSettings** serializer now includes `max_commission_before_active_buyer_amount` (documented in apidoc).

---

## 9. Summary

- **All commission credits** (direct, binary pair, initial bonus) go through `add_wallet_balance`, where the ₹10k cap and partial credit apply, and `credited_while_non_active_buyer` is set when appropriate.
- **Reversals** use deductions and do not affect the cap sum.
- **Non-commission flows** (REFUND, ACTIVE_BUYER_BONUS, PAYOUT, etc.) are unchanged.
- **Recalc and API** do not create commission transactions and do not expose the new field in a way that would break clients.

No other flow is negatively affected by the commission cap implementation.
