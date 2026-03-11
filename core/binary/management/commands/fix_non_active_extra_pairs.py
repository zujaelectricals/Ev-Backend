"""
Management command to remove binary pairs that exceed max_earnings_before_active_buyer
for non-active buyers, and reverse any commission already credited.

Use when a non-active buyer has more pairs than allowed (e.g. 5 pairs when max is 4).
Removes the extra pair(s), reverses wallet credit and total_earned, and deletes
BinaryEarning and BinaryPair records.

Usage:
  python manage.py fix_non_active_extra_pairs --user-id 80 --dry-run
  python manage.py fix_non_active_extra_pairs --user-id 80 --execute
  python manage.py fix_non_active_extra_pairs --all --dry-run   # Fix all affected users
  python manage.py fix_non_active_extra_pairs --all --execute
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from core.binary.models import BinaryPair, BinaryEarning
from core.settings.models import PlatformSettings
from core.users.models import User
from core.wallet.models import WalletTransaction
from core.wallet.utils import get_or_create_wallet, deduct_wallet_balance


class Command(BaseCommand):
    help = (
        'Remove binary pairs for non-active buyer(s) that exceed max_earnings_before_active_buyer, '
        'and reverse any commission credited for those pairs. Use --all to fix every affected user.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            default=None,
            help='User ID of the non-active buyer to fix (e.g. 80). Required unless --all.',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Fix all non-active buyers who have extra pairs (pair_number_after_activation > max).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only list pairs and amounts; do not reverse or delete.',
        )
        parser.add_argument(
            '--execute',
            action='store_true',
            help='Actually reverse commission and delete extra pairs.',
        )

    def handle(self, *args, **options):
        user_id = options['user_id']
        fix_all = options['all']
        dry_run = options['dry_run']
        do_execute = options['execute']

        if not fix_all and user_id is None:
            self.stdout.write(
                self.style.ERROR('Specify --user-id <id> or --all.')
            )
            return
        if fix_all and user_id is not None:
            self.stdout.write(
                self.style.WARNING('Using --all; --user-id ignored.')
            )
            user_id = None

        if not dry_run and not do_execute:
            self.stdout.write(
                self.style.WARNING(
                    'Specify --dry-run to list only, or --execute to apply changes.'
                )
            )
            return

        platform_settings = PlatformSettings.get_settings()
        max_earnings = platform_settings.max_earnings_before_active_buyer

        if fix_all:
            # Find all non-active buyers who have at least one pair with pair_number_after_activation > max
            user_ids_with_extra = set(
                BinaryPair.objects.filter(
                    pair_number_after_activation__isnull=False,
                    pair_number_after_activation__gt=max_earnings,
                ).values_list('user_id', flat=True).distinct()
            )
            users_to_fix = list(
                User.objects.filter(
                    id__in=user_ids_with_extra,
                    is_distributor=True,
                    is_active_buyer=False,
                ).order_by('id')
            )
            if not users_to_fix:
                self.stdout.write(
                    self.style.SUCCESS(
                        'No non-active buyers with extra pairs found. Nothing to fix.'
                    )
                )
                return
            self.stdout.write(
                f'Found {len(users_to_fix)} non-active buyer(s) with extra pairs: '
                f'{[u.id for u in users_to_fix]}'
            )
            self.stdout.write('')
            total_reversed = 0
            total_deleted = 0
            for user in users_to_fix:
                rev, deleted, errs = self._fix_user(user, max_earnings, dry_run, do_execute)
                total_reversed += rev
                total_deleted += deleted
            self.stdout.write('')
            self.stdout.write('=' * 60)
            self.stdout.write(f'Total: Reversed commission for {total_reversed} pair(s), deleted {total_deleted} pair(s)')
            self.stdout.write(
                self.style.SUCCESS(
                    'Done. Run: python manage.py recalculate_wallet_balances if you need to reconcile.'
                )
            )
            return

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User id={user_id} not found.'))
            return

        self._fix_user(user, max_earnings, dry_run, do_execute)
        if do_execute:
            self.stdout.write(
                self.style.SUCCESS(
                    'Done. Run: python manage.py recalculate_wallet_balances if you need to reconcile.'
                )
            )

    def _fix_user(self, user, max_earnings, dry_run, do_execute):
        """Fix one user: remove extra pairs and reverse commission. Returns (reversed_count, deleted_count, errors)."""
        user_id = user.id
        if user.is_active_buyer:
            self.stdout.write(
                self.style.WARNING(
                    f'User {user_id} ({user.email}) is already an Active Buyer. Skip.'
                )
            )
            return 0, 0, []

        extra_pairs = (
            BinaryPair.objects.filter(
                user_id=user_id,
                pair_number_after_activation__isnull=False,
                pair_number_after_activation__gt=max_earnings,
            )
            .order_by('pair_number_after_activation')
            .select_related('user')
        )
        extra_pairs = list(extra_pairs)

        if not extra_pairs:
            self.stdout.write(
                self.style.SUCCESS(
                    f'User {user_id} has no pairs with pair_number_after_activation > {max_earnings}. Nothing to fix.'
                )
            )
            return 0, 0, []

        self.stdout.write('=' * 60)
        self.stdout.write(
            f'Extra pairs for user_id={user_id} ({user.email}) max_earnings_before_active_buyer={max_earnings}'
        )
        self.stdout.write('=' * 60)
        self.stdout.write(f'Pairs to remove: {len(extra_pairs)}')
        for p in extra_pairs:
            self.stdout.write(
                f'  Pair id={p.id} pair_number_after_activation={p.pair_number_after_activation} '
                f'earning_amount={p.earning_amount} commission_blocked={p.commission_blocked}'
            )
        self.stdout.write('')

        if dry_run:
            self.stdout.write(
                self.style.WARNING('[DRY RUN] No changes made. Use --execute to apply.')
            )
            return 0, 0, []

        if not do_execute:
            return 0, 0, []

        reversed_count = 0
        deleted_pairs = 0
        errors = []

        for pair in extra_pairs:
            try:
                with transaction.atomic():
                    txns = WalletTransaction.objects.filter(
                        user=user,
                        transaction_type='BINARY_PAIR_COMMISSION',
                        reference_type='binary_pair',
                        reference_id=pair.id,
                        amount__gt=0,
                    )
                    total_credited = sum(Decimal(str(t.amount)) for t in txns)

                    if total_credited > 0:
                        wallet = get_or_create_wallet(user)
                        if wallet.balance < total_credited:
                            raise ValueError(
                                f'Insufficient balance: {wallet.balance} < {total_credited}'
                            )
                        deduct_wallet_balance(
                            user=user,
                            amount=float(total_credited),
                            transaction_type='BINARY_PAIR_COMMISSION',
                            description=(
                                f'Reversal: pair #{pair.pair_number_after_activation} removed '
                                f'(max_earnings_before_active_buyer={max_earnings}). Pair id={pair.id}.'
                            ),
                            reference_id=pair.id,
                            reference_type='binary_pair',
                        )
                        wallet.refresh_from_db()
                        wallet.total_earned -= total_credited
                        if wallet.total_earned < 0:
                            wallet.total_earned = Decimal('0')
                        wallet.save(update_fields=['total_earned'])
                        reversed_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'  Reversed commission for pair id={pair.id}: {total_credited}'
                            )
                        )

                    pair_id = pair.id
                    BinaryEarning.objects.filter(binary_pair=pair).delete()
                    pair.delete()
                    deleted_pairs += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'  Deleted pair id={pair_id}')
                    )
            except ValueError as e:
                errors.append((pair.id, str(e)))
                self.stdout.write(
                    self.style.ERROR(f'  Skip pair id={pair.id}: {e}')
                )
            except Exception as e:
                errors.append((pair.id, str(e)))
                self.stdout.write(
                    self.style.ERROR(f'  Error processing pair id={pair.id}: {e}')
                )

        self.stdout.write('')
        self.stdout.write(f'User {user_id}: Reversed {reversed_count}, Deleted {deleted_pairs}')
        if errors:
            self.stdout.write(self.style.ERROR('Errors:'))
            for pair_id, msg in errors:
                self.stdout.write(f'  Pair {pair_id}: {msg}')
        return reversed_count, deleted_pairs, errors
