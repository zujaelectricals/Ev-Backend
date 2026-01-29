"""
Script to analyze wallet transactions and payouts for user_id 161
Run this with: python manage.py shell < check_user_161_transactions.py
Or use: python manage.py shell, then copy-paste the code
"""

from core.users.models import User
from core.wallet.models import Wallet, WalletTransaction
from core.payout.models import Payout
from decimal import Decimal
from django.db.models import Sum, Q, Count

# Get user
user_id = 161
try:
    user = User.objects.get(id=user_id)
    print(f"\n{'='*80}")
    print(f"WALLET ANALYSIS FOR USER: {user.username} (ID: {user_id})")
    print(f"{'='*80}\n")
except User.DoesNotExist:
    print(f"User with ID {user_id} not found!")
    exit()

# Get wallet
wallet = user.wallet if hasattr(user, 'wallet') else None
if wallet:
    print(f"Wallet Balance (from model): ₹{wallet.balance}")
    print(f"Total Earned (from model): ₹{wallet.total_earned}")
    print(f"Total Withdrawn (from model): ₹{wallet.total_withdrawn}")
    print()
else:
    print("No wallet found for user")
    print()

# Get all wallet transactions
transactions = WalletTransaction.objects.filter(user=user).order_by('-created_at')

print(f"{'='*80}")
print("ALL WALLET TRANSACTIONS (Most Recent First)")
print(f"{'='*80}\n")

total_balance = Decimal('0')
earnings_total = Decimal('0')
deductions_total = Decimal('0')

for txn in transactions:
    total_balance += txn.amount
    
    # Track earnings
    if txn.transaction_type in ['BINARY_PAIR_COMMISSION', 'DIRECT_USER_COMMISSION', 'BINARY_INITIAL_BONUS']:
        earnings_total += txn.amount
    
    # Track deductions (negative amounts)
    if txn.amount < 0:
        deductions_total += abs(txn.amount)
    
    sign = "+" if txn.amount >= 0 else ""
    print(f"{txn.created_at.strftime('%Y-%m-%d %H:%M:%S')} | "
          f"{txn.transaction_type:25s} | "
          f"{sign}₹{txn.amount:>10} | "
          f"Balance: ₹{txn.balance_after:>10} | "
          f"{txn.description[:50]}")

print(f"\n{'='*80}")
print("TRANSACTION SUMMARY")
print(f"{'='*80}\n")

print(f"Total Balance (sum of all transactions): ₹{total_balance}")
print(f"Total Earnings (BINARY_PAIR_COMMISSION + DIRECT_USER_COMMISSION + BINARY_INITIAL_BONUS): ₹{earnings_total}")
print(f"Total Deductions (negative transactions): ₹{deductions_total}")
print(f"Difference (Earnings - Balance): ₹{earnings_total - total_balance}")

# Breakdown by transaction type
print(f"\n{'='*80}")
print("BREAKDOWN BY TRANSACTION TYPE")
print(f"{'='*80}\n")

txn_types = WalletTransaction.objects.filter(user=user).values('transaction_type').annotate(
    total=Sum('amount'),
    count=Count('id')
).order_by('-total')

for txn_type in txn_types:
    print(f"{txn_type['transaction_type']:30s} | "
          f"Count: {txn_type['count']:3d} | "
          f"Total: ₹{txn_type['total']:>12}")

# Check payouts
print(f"\n{'='*80}")
print("PAYOUT HISTORY")
print(f"{'='*80}\n")

payouts = Payout.objects.filter(user=user).order_by('-created_at')

if payouts.exists():
    for payout in payouts:
        print(f"Payout ID: {payout.id}")
        print(f"  Status: {payout.status}")
        print(f"  Requested Amount: ₹{payout.requested_amount}")
        print(f"  TDS Amount: ₹{payout.tds_amount}")
        print(f"  Net Amount: ₹{payout.net_amount}")
        print(f"  EMI Auto-filled: {payout.emi_auto_filled}")
        print(f"  EMI Amount: ₹{payout.emi_amount}")
        print(f"  Created: {payout.created_at}")
        print(f"  Processed: {payout.processed_at if payout.processed_at else 'N/A'}")
        print(f"  Completed: {payout.completed_at if payout.completed_at else 'N/A'}")
        print()
else:
    print("No payout records found")

# Calculate wallet balance (excluding TDS, EXTRA_DEDUCTION, REFERRAL_BONUS)
print(f"\n{'='*80}")
print("WALLET BALANCE CALCULATION (as per serializer)")
print(f"{'='*80}\n")

excluded_types = ['REFERRAL_BONUS', 'TDS_DEDUCTION', 'EXTRA_DEDUCTION']
wallet_balance_calc = WalletTransaction.objects.filter(user=user).exclude(
    transaction_type__in=excluded_types
).aggregate(total=Sum('amount'))['total'] or Decimal('0')

print(f"Wallet Balance (excluding {', '.join(excluded_types)}): ₹{wallet_balance_calc}")

# Calculate total earnings (only earnings types)
earnings_calc = WalletTransaction.objects.filter(
    user=user,
    transaction_type__in=['BINARY_PAIR_COMMISSION', 'DIRECT_USER_COMMISSION', 'BINARY_INITIAL_BONUS']
).aggregate(total=Sum('amount'))['total'] or Decimal('0')

print(f"Total Earnings (BINARY_PAIR_COMMISSION + DIRECT_USER_COMMISSION + BINARY_INITIAL_BONUS): ₹{earnings_calc}")
print(f"Difference: ₹{earnings_calc - wallet_balance_calc}")

# Check for specific deduction types
print(f"\n{'='*80}")
print("DEDUCTION BREAKDOWN")
print(f"{'='*80}\n")

payout_deductions = WalletTransaction.objects.filter(
    user=user,
    transaction_type='PAYOUT'
).aggregate(total=Sum('amount'))['total'] or Decimal('0')

emi_deductions = WalletTransaction.objects.filter(
    user=user,
    transaction_type='EMI_DEDUCTION'
).aggregate(total=Sum('amount'))['total'] or Decimal('0')

reserve_deductions = WalletTransaction.objects.filter(
    user=user,
    transaction_type='RESERVE_DEDUCTION'
).aggregate(total=Sum('amount'))['total'] or Decimal('0')

print(f"PAYOUT Deductions: ₹{abs(payout_deductions)} (negative: {payout_deductions})")
print(f"EMI Deductions: ₹{abs(emi_deductions)} (negative: {emi_deductions})")
print(f"RESERVE Deductions: ₹{abs(reserve_deductions)} (negative: {reserve_deductions})")
print(f"Total Deductions: ₹{abs(payout_deductions) + abs(emi_deductions) + abs(reserve_deductions)}")

print(f"\n{'='*80}")
print("ANALYSIS COMPLETE")
print(f"{'='*80}\n")

