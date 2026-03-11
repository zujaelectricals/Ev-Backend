"""
Fix wallet transactions for user 219 (Mohanlal A) for pair 103 (Pair #8):
- Consolidate to one BINARY_PAIR_COMMISSION of 1800 (net after TDS; extra deduction waived)
- Void the separate correction transaction
- Mark EXTRA_DEDUCTION as waived (zero remaining balance)

Run after fix_user_219_extra_deduction. Pair 103 already has earning_amount=1800 and
extra_deduction_applied=0; this command only cleans up the wallet transaction ledger.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction

from core.users.models import User
from core.wallet.models import WalletTransaction


class Command(BaseCommand):
    help = 'Fix wallet transactions for user 219 (pair 103): one commission of 1800, mark extra deduction waived.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            default=219,
            help='User ID (default: 219)',
        )
        parser.add_argument(
            '--pair-id',
            type=int,
            default=103,
            help='Binary pair ID to fix (default: 103)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only show what would be done',
        )

    def handle(self, *args, **options):
        user_id = options['user_id']
        pair_id = options['pair_id']
        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - no changes will be saved'))

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User id={user_id} not found.'))
            return

        txns = list(
            WalletTransaction.objects.filter(
                user=user,
                reference_id=pair_id,
                reference_type='binary_pair',
            ).order_by('id')
        )
        if not txns:
            self.stdout.write(
                self.style.WARNING(
                    f'No wallet transactions found for user {user_id} pair_id={pair_id}.'
                )
            )
            return

        # Expected: EXTRA_DEDUCTION (-400), BINARY_PAIR_COMMISSION (1400), BINARY_PAIR_COMMISSION (400 correction)
        extra_txn = next((t for t in txns if t.transaction_type == 'EXTRA_DEDUCTION'), None)
        commission_txns = [t for t in txns if t.transaction_type == 'BINARY_PAIR_COMMISSION']
        if len(commission_txns) < 2:
            self.stdout.write(
                self.style.WARNING(
                    f'Expected at least 2 BINARY_PAIR_COMMISSION txns (original + correction). Found {len(commission_txns)}.'
                )
            )
            return

        original = commission_txns[0]   # 1400
        correction = commission_txns[1]  # 400
        correct_net = Decimal('1800')   # pair_amount - TDS for pair 103

        self.stdout.write(
            f'User: {user.email}\n'
            f'Pair id: {pair_id}\n'
            f'Original commission txn id={original.id} amount={original.amount} balance_after={original.balance_after}\n'
            f'Correction txn id={correction.id} amount={correction.amount}\n'
            f'Will set original amount={correct_net}, balance_after=13600 (or original.balance_before + 1800)\n'
            f'Will void correction: amount=0, balance_before/after=original new balance_after'
        )

        if dry_run:
            self.stdout.write(self.style.SUCCESS('[DRY RUN] Would update wallet transactions.'))
            return

        with transaction.atomic():
            new_balance_after_original = original.balance_before + correct_net

            # 1) Original BINARY_PAIR_COMMISSION: amount 1400 -> 1800, balance_after updated
            original.amount = correct_net
            original.balance_after = new_balance_after_original
            original.description = (
                'Binary pair commission (Pair #8) - Net after TDS (extra deduction waived: zero remaining balance)'
            )
            original.save(update_fields=['amount', 'balance_after', 'description'])

            # 2) Correction BINARY_PAIR_COMMISSION: void (amount=0, balance unchanged)
            correction.amount = Decimal('0')
            correction.balance_before = new_balance_after_original
            correction.balance_after = new_balance_after_original
            correction.description = 'Voided: consolidated into Pair #8 commission above (extra deduction waived - zero remaining balance)'
            correction.save(update_fields=['amount', 'balance_before', 'balance_after', 'description'])

            # 3) EXTRA_DEDUCTION: description only (transaction is tracking-only, balance unchanged)
            if extra_txn:
                extra_txn.description = (
                    'Extra deduction (20%) on binary pair commission (Pair #8) - Waived (zero remaining balance)'
                )
                extra_txn.save(update_fields=['description'])

        self.stdout.write(
            self.style.SUCCESS(
                f'Updated wallet transactions: original id={original.id} amount=1800, '
                f'correction id={correction.id} voided, EXTRA_DEDUCTION description updated.'
            )
        )
