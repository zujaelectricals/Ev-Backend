"""
Management command to completely erase all wallet transaction history for all users.

- Deletes ALL WalletTransaction rows.
- Resets every Wallet: balance=0, total_earned=0, total_withdrawn=0.

DANGER: This is irreversible. Use only when you need a full wallet ledger reset
(e.g. after fixing commission logic and re-running from scratch).

Usage:
  python manage.py erase_wallet_transaction_history --dry-run   # Show counts only
  python manage.py erase_wallet_transaction_history --confirm  # Actually delete and reset
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from core.wallet.models import Wallet, WalletTransaction


class Command(BaseCommand):
    help = (
        "Completely erase all wallet transaction history and reset all wallet "
        "balances/totals to zero. Requires --confirm to execute."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only show how many transactions and wallets would be affected; do not change anything.",
        )
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually delete all wallet transactions and reset all wallets. Required to perform the operation.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        confirm = options["confirm"]

        tx_count = WalletTransaction.objects.count()
        wallet_count = Wallet.objects.count()

        self.stdout.write("=" * 60)
        self.stdout.write("Erase wallet transaction history")
        self.stdout.write("=" * 60)
        self.stdout.write(f"WalletTransaction rows: {tx_count}")
        self.stdout.write(f"Wallet rows (will reset balance/total_earned/total_withdrawn to 0): {wallet_count}")
        self.stdout.write("")

        if tx_count == 0 and wallet_count == 0:
            self.stdout.write(self.style.WARNING("No wallet data to erase."))
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "[DRY RUN] Would delete all wallet transactions and reset all wallet balances. "
                    "Run with --confirm to execute."
                )
            )
            return

        if not confirm:
            self.stdout.write(
                self.style.ERROR(
                    "This will permanently delete ALL wallet transactions and set all wallet "
                    "balance/total_earned/total_withdrawn to 0. Add --confirm to proceed."
                )
            )
            return

        self.stdout.write(self.style.WARNING("Deleting all wallet transactions and resetting wallets..."))

        with transaction.atomic():
            deleted, _ = WalletTransaction.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} WalletTransaction row(s)."))

            Wallet.objects.all().update(
                balance=Decimal("0"),
                total_earned=Decimal("0"),
                total_withdrawn=Decimal("0"),
            )
            self.stdout.write(self.style.SUCCESS(f"Reset {wallet_count} Wallet(s) to balance=0, total_earned=0, total_withdrawn=0."))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Done. All wallet transaction history has been erased and wallets reset."))
