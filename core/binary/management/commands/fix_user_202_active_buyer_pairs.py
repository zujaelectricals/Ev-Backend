"""
Fix user 202 (Unnikrishnan K / unni@toqse.com): backfill active_buyer_since and reverse
the 5th pair commission that was paid using nodes placed before he became an Active Buyer.

Rule: Pair 5+ should only use nodes placed after the distributor became an Active Buyer.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.users.models import User
from core.booking.models import Payment
from core.settings.models import PlatformSettings
from core.binary.models import BinaryPair, BinaryEarning, BinaryNode
from core.wallet.models import WalletTransaction
from core.wallet.utils import get_or_create_wallet, deduct_wallet_balance


def get_active_buyer_since_timestamp(user):
    """
    Return the datetime when user's total completed payments first reached activation_amount.
    Uses Payment completed_at when available, else payment_date.
    """
    settings = PlatformSettings.get_settings()
    activation_amount = settings.activation_amount
    if activation_amount <= 0:
        return None
    payments = (
        Payment.objects.filter(
            booking__user=user,
            booking__status__in=['active', 'completed'],
            status='completed',
        )
        .order_by('completed_at', 'payment_date')
    )
    total = Decimal('0')
    for p in payments:
        total += Decimal(str(p.amount))
        if total >= activation_amount:
            ts = p.completed_at or p.payment_date
            return ts
    return None


class Command(BaseCommand):
    help = (
        'Fix user 202: backfill active_buyer_since and reverse 5th pair commission '
        'that used nodes placed before becoming Active Buyer.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            default=202,
            help='User ID to fix (default: 202)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only print what would be done, do not change data',
        )

    def handle(self, *args, **options):
        user_id = options['user_id']
        dry_run = options['dry_run']

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User id={user_id} not found.'))
            return

        settings = PlatformSettings.get_settings()
        max_before = settings.max_earnings_before_active_buyer
        activation_amount = settings.activation_amount

        # 1) Backfill active_buyer_since
        active_buyer_since = get_active_buyer_since_timestamp(user)
        if not active_buyer_since and user.is_active_buyer:
            self.stdout.write(
                self.style.WARNING(
                    f'User {user.email} is Active Buyer but could not derive active_buyer_since from payments. '
                    f'Using pair 5 matched_at if available.'
                )
            )
            fifth = BinaryPair.objects.filter(
                user=user,
                pair_number_after_activation=5,
            ).first()
            if fifth and fifth.matched_at:
                active_buyer_since = fifth.matched_at
                self.stdout.write(
                    f'Using 5th pair matched_at as active_buyer_since: {active_buyer_since}'
                )
            else:
                active_buyer_since = timezone.now()
                self.stdout.write(
                    self.style.WARNING('Using now() as fallback for active_buyer_since.')
                )

        if dry_run:
            self.stdout.write(
                f'[DRY RUN] Would set user {user.email} active_buyer_since = {active_buyer_since}'
            )
        else:
            if user.is_active_buyer and active_buyer_since and (not getattr(user, 'active_buyer_since', None) or user.active_buyer_since != active_buyer_since):
                user.active_buyer_since = active_buyer_since
                user.save(update_fields=['active_buyer_since'])
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Set active_buyer_since = {active_buyer_since} for user {user.email}'
                    )
                )
            else:
                self.stdout.write(
                    f'active_buyer_since already set or unchanged: {getattr(user, "active_buyer_since", None)}'
                )
        user.refresh_from_db()

        # 2) Find pairs 5+ where both left and right were placed before active_buyer_since
        cutoff = getattr(user, 'active_buyer_since', None) or active_buyer_since
        if not cutoff:
            self.stdout.write(self.style.WARNING('No active_buyer_since; skipping pair reversal.'))
            return

        pairs_to_fix = BinaryPair.objects.filter(
            user=user,
            pair_number_after_activation__gte=max_before + 1,
        ).order_by('pair_number_after_activation')

        for pair in pairs_to_fix:
            left_created = None
            right_created = None
            if pair.left_user_id:
                try:
                    left_node = BinaryNode.objects.get(user_id=pair.left_user_id)
                    left_created = left_node.created_at
                except BinaryNode.DoesNotExist:
                    pass
            if pair.right_user_id:
                try:
                    right_node = BinaryNode.objects.get(user_id=pair.right_user_id)
                    right_created = right_node.created_at
                except BinaryNode.DoesNotExist:
                    pass

            # Both must be placed before cutoff to consider this pair "wrong"
            if left_created is None or right_created is None:
                self.stdout.write(
                    f'  Pair id={pair.id} (#{pair.pair_number_after_activation}): '
                    f'skip (missing node created_at)'
                )
                continue
            if left_created >= cutoff or right_created >= cutoff:
                self.stdout.write(
                    f'  Pair id={pair.id} (#{pair.pair_number_after_activation}): '
                    f'skip (at least one node placed after cutoff)'
                )
                continue

            self.stdout.write(
                f'  Pair id={pair.id} (#{pair.pair_number_after_activation}): '
                f'both nodes placed before active_buyer_since -> reverse commission'
            )

            if dry_run:
                txns = WalletTransaction.objects.filter(
                    user=user,
                    transaction_type='BINARY_PAIR_COMMISSION',
                    reference_type='binary_pair',
                    reference_id=pair.id,
                    amount__gt=0,
                )
                total = sum(Decimal(str(t.amount)) for t in txns)
                self.stdout.write(
                    f'    [DRY RUN] Would reverse commission: {total} (pair id={pair.id})'
                )
                continue

            txns = WalletTransaction.objects.filter(
                user=user,
                transaction_type='BINARY_PAIR_COMMISSION',
                reference_type='binary_pair',
                reference_id=pair.id,
                amount__gt=0,
            )
            total_credited = sum(Decimal(str(t.amount)) for t in txns)

            if total_credited <= 0:
                self.stdout.write(
                    self.style.WARNING(
                        f'    Pair id={pair.id}: no positive commission to reverse; deleting pair and earning.'
                    )
                )
                BinaryEarning.objects.filter(binary_pair=pair).delete()
                pair.delete()
                continue

            try:
                with transaction.atomic():
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
                            f'Reversal: pair #{pair.pair_number_after_activation} used nodes placed '
                            f'before Active Buyer (active_buyer_since={cutoff}). Pair id={pair.id}.'
                        ),
                        reference_id=pair.id,
                        reference_type='binary_pair',
                    )
                    wallet.refresh_from_db()
                    wallet.total_earned -= total_credited
                    if wallet.total_earned < 0:
                        wallet.total_earned = Decimal('0')
                    wallet.save(update_fields=['total_earned'])

                    pair_id = pair.id
                    pair_num = pair.pair_number_after_activation
                    BinaryEarning.objects.filter(binary_pair=pair).delete()
                    pair.delete()

                    self.stdout.write(
                        self.style.SUCCESS(
                            f'    Reversed commission {total_credited} for pair id={pair_id}, '
                            f'deleted pair and earning (user now has one fewer pair; next pair will be #{pair_num}).'
                        )
                    )
            except ValueError as e:
                self.stdout.write(self.style.ERROR(f'    Aborted: {e}'))

        self.stdout.write(self.style.SUCCESS('Done.'))
