from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Sum

from core.wallet.models import Wallet, WalletTransaction


class Command(BaseCommand):
    """
    Recalculate wallet balances and aggregates for all users.

    This command is primarily intended to fix historical data where
    TDS_DEDUCTION and EXTRA_DEDUCTION wallet transactions incorrectly
    reduced the wallet balance, even though commissions were already
    credited as net (after deductions).

    New logic:
    - Wallet balance is the sum of all wallet transactions EXCLUDING:
      REFERRAL_BONUS, TDS_DEDUCTION, EXTRA_DEDUCTION.
    - Total earned is the sum of positive earning transactions:
      BINARY_PAIR, BINARY_PAIR_COMMISSION, DIRECT_USER_COMMISSION,
      BINARY_INITIAL_BONUS.
    - Total withdrawn is the absolute sum of PAYOUT transactions.
    """

    help = "Recalculate wallet balances, total_earned, and total_withdrawn for all users."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Recalculating wallet balances..."))

        with transaction.atomic():
            wallets = Wallet.objects.select_related("user").all()
            total_wallets = wallets.count()
            fixed_count = 0

            for wallet in wallets:
                user = wallet.user

                tx_qs = WalletTransaction.objects.filter(user=user)

                # 1) Recalculate balance excluding TDS/extra/referral bonus
                balance_total = (
                    tx_qs.exclude(
                        transaction_type__in=[
                            "REFERRAL_BONUS",
                            "TDS_DEDUCTION",
                            "EXTRA_DEDUCTION",
                        ]
                    ).aggregate(total=Sum("amount"))["total"]
                    or Decimal("0")
                )

                # 2) Recalculate total_earned from earning transaction types
                earnings_total = (
                    tx_qs.filter(
                        transaction_type__in=[
                            "BINARY_PAIR",
                            "BINARY_PAIR_COMMISSION",
                            "DIRECT_USER_COMMISSION",
                            "BINARY_INITIAL_BONUS",
                        ]
                    ).aggregate(total=Sum("amount"))["total"]
                    or Decimal("0")
                )

                # 3) Recalculate total_withdrawn from PAYOUT transactions (absolute sum)
                payout_sum = (
                    tx_qs.filter(transaction_type="PAYOUT").aggregate(total=Sum("amount"))[
                        "total"
                    ]
                    or Decimal("0")
                )
                total_withdrawn = abs(payout_sum)

                # Only update if values actually differ
                if (
                    wallet.balance != balance_total
                    or wallet.total_earned != earnings_total
                    or wallet.total_withdrawn != total_withdrawn
                ):
                    self.stdout.write(
                        f"Fixing wallet for user {user.id} "
                        f"(old balance={wallet.balance}, new balance={balance_total})"
                    )
                    wallet.balance = balance_total
                    wallet.total_earned = earnings_total
                    wallet.total_withdrawn = total_withdrawn
                    wallet.save(update_fields=["balance", "total_earned", "total_withdrawn"])
                    fixed_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Completed. Processed {total_wallets} wallets, fixed {fixed_count}."
            )
        )


