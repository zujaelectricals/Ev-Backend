"""
Management command to reverse direct user commissions that were paid to
non-direct-parents under the old "pay all ancestors" logic.

After switching to "direct parent only", run this to:
1. Find all DIRECT_USER_COMMISSION transactions where the recipient was not
   the direct parent of the referenced user (overpayments).
2. Optionally reverse them (deduct from wallet, create reversal transaction).

Usage:
  python manage.py fix_overpaid_direct_commissions --dry-run   # List overpayments only
  python manage.py fix_overpaid_direct_commissions --execute   # Actually reverse
  python manage.py fix_overpaid_direct_commissions --execute --limit 10  # Limit for testing
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from core.binary.models import BinaryNode
from core.wallet.models import WalletTransaction
from core.wallet.utils import deduct_wallet_balance


class Command(BaseCommand):
    help = (
        'Find and optionally reverse direct user commissions paid to non-direct-parents '
        '(overpayments from old "all ancestors" logic).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only list overpayments; do not deduct or create reversals.',
        )
        parser.add_argument(
            '--execute',
            action='store_true',
            help='Actually reverse overpayments (deduct from wallet, create reversal transaction).',
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit number of overpayments to process (for testing).',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        do_execute = options['execute']
        limit = options['limit']

        if not dry_run and not do_execute:
            self.stdout.write(
                self.style.WARNING(
                    'Specify --dry-run to list overpayments only, or --execute to reverse them.'
                )
            )
            return

        # All DIRECT_USER_COMMISSION with reference_type='user' (reference_id = new user id)
        txns = (
            WalletTransaction.objects.filter(
                transaction_type='DIRECT_USER_COMMISSION',
                reference_type='user',
                amount__gt=0,
            )
            .select_related('user', 'wallet')
            .order_by('id')
        )

        overpayments = []
        skipped_no_node = []
        skipped_no_parent = []

        for tx in txns:
            new_user_id = tx.reference_id
            recipient_user_id = tx.user_id

            try:
                new_user_node = BinaryNode.objects.get(user_id=new_user_id)
            except BinaryNode.DoesNotExist:
                skipped_no_node.append((tx.id, new_user_id, recipient_user_id, tx.amount))
                continue

            if new_user_node.parent_id is None:
                # New user is root; no one should get commission for them under new logic
                correct_recipient_user_id = None
            else:
                correct_recipient_user_id = new_user_node.parent.user_id

            if recipient_user_id != correct_recipient_user_id:
                overpayments.append({
                    'tx': tx,
                    'new_user_id': new_user_id,
                    'correct_recipient_user_id': correct_recipient_user_id,
                })

        if limit is not None:
            overpayments = overpayments[:limit]

        total_amount = sum(Decimal(str(o['tx'].amount)) for o in overpayments)

        self.stdout.write('=' * 60)
        self.stdout.write('Overpaid direct user commissions (recipient was not direct parent)')
        self.stdout.write('=' * 60)
        self.stdout.write(f'Total overpayments found: {len(overpayments)}')
        self.stdout.write(f'Total amount to reverse: {total_amount}')
        if skipped_no_node:
            self.stdout.write(
                self.style.WARNING(
                    f'Skipped {len(skipped_no_node)} transactions (new user has no binary node)'
                )
            )
        self.stdout.write('')

        if not overpayments:
            self.stdout.write(self.style.SUCCESS('No overpayments to fix.'))
            return

        for i, o in enumerate(overpayments, 1):
            tx = o['tx']
            self.stdout.write(
                f"  {i}. Tx id={tx.id} | recipient user_id={tx.user_id} | "
                f"new_user_id={o['new_user_id']} | amount={tx.amount} | "
                f"correct_recipient_user_id={o['correct_recipient_user_id']}"
            )

        if dry_run:
            self.stdout.write('')
            self.stdout.write(
                self.style.WARNING('[DRY RUN] No changes made. Use --execute to reverse these.')
            )
            return

        if not do_execute:
            return

        self.stdout.write('')
        self.stdout.write('Reversing overpayments...')

        reversed_count = 0
        errors = []

        for o in overpayments:
            tx = o['tx']
            amount = abs(Decimal(str(tx.amount)))
            user = tx.user

            try:
                with transaction.atomic():
                    deduct_wallet_balance(
                        user=user,
                        amount=float(amount),
                        transaction_type='DIRECT_USER_COMMISSION',
                        description=(
                            f"Reversal: overpaid commission (direct-parent-only policy). "
                            f"Original tx id={tx.id}, new_user_id={o['new_user_id']}. "
                            f"Commission should have gone to direct parent only."
                        ),
                        reference_id=tx.reference_id,
                        reference_type='user',
                    )
                    # total_earned was increased when the original commission was credited
                    wallet = user.wallet
                    wallet.total_earned -= amount
                    if wallet.total_earned < 0:
                        wallet.total_earned = Decimal('0')
                    wallet.save(update_fields=['total_earned'])

                reversed_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Reversed tx id={tx.id} | user_id={user.id} | amount={amount}"
                    )
                )
            except ValueError as e:
                errors.append((tx.id, str(e)))
                self.stdout.write(
                    self.style.ERROR(
                        f"  Skip tx id={tx.id} (user_id={user.id}): {e} (e.g. insufficient balance)"
                    )
                )
            except Exception as e:
                errors.append((tx.id, str(e)))
                self.stdout.write(
                    self.style.ERROR(f"  Error reversing tx id={tx.id}: {e}")
                )

        self.stdout.write('')
        self.stdout.write('=' * 60)
        self.stdout.write(f'Reversed: {reversed_count} | Errors: {len(errors)}')
        if errors:
            self.stdout.write(self.style.ERROR('Errors (review manually):'))
            for tx_id, msg in errors:
                self.stdout.write(f'  Tx {tx_id}: {msg}')
        self.stdout.write(
            self.style.SUCCESS(
                'Run: python manage.py recalculate_wallet_balances to reconcile balances if needed.'
            )
        )
