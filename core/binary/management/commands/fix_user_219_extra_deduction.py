"""
Fix user 219 (Mohanlal A): For the last binary pair where extra_deduction was applied
while his remaining booking balance was 0, credit the waived extra deduction to wallet
and update pair/earning records so he effectively received full net (commission - TDS).

Rule: When remaining_balance <= 0, extra deduction must not be applied; full net to wallet.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.users.models import User
from core.binary.models import BinaryPair, BinaryEarning
from core.settings.models import PlatformSettings
from core.wallet.utils import add_wallet_balance


class Command(BaseCommand):
    help = (
        'Fix user 219 (Mohanlal): credit waived extra deduction for last pair when '
        'remaining balance was 0; update pair and earning records.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            default=219,
            help='User ID to fix (default: 219)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only show what would be done',
        )

    def handle(self, *args, **options):
        user_id = options['user_id']
        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - no changes will be saved'))

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User id={user_id} not found.'))
            return

        # Last pair with extra_deduction_applied > 0 (the one to fix)
        pair = (
            BinaryPair.objects.filter(
                user=user,
                extra_deduction_applied__gt=0,
                commission_blocked=False,
            )
            .order_by('-pair_number_after_activation')
            .first()
        )
        if not pair:
            self.stdout.write(
                self.style.WARNING(
                    f'No binary pair with extra_deduction_applied > 0 found for user {user.email}.'
                )
            )
            return

        platform_settings = PlatformSettings.get_settings()
        tds_pct = platform_settings.binary_commission_tds_percentage or Decimal('0')
        # Net = pair_amount - TDS (e.g. 2000 - 10% = 1800)
        correct_net = pair.pair_amount - (pair.pair_amount * tds_pct / Decimal('100'))
        extra = pair.extra_deduction_applied
        # Amount to credit = what he should have got minus what he got
        credit_amount = correct_net - pair.earning_amount
        if credit_amount <= 0:
            self.stdout.write(
                self.style.WARNING(
                    f'Pair id={pair.id} (pair #{pair.pair_number_after_activation}): '
                    f'earning_amount already >= correct_net. Nothing to credit.'
                )
            )
            return

        self.stdout.write(
            f'User: {user.email} (id={user_id})\n'
            f'Pair id={pair.id}, pair_number_after_activation={pair.pair_number_after_activation}\n'
            f'pair_amount={pair.pair_amount}, extra_deduction_applied={extra}, '
            f'earning_amount={pair.earning_amount}\n'
            f'correct_net (pair_amount - TDS)={correct_net}\n'
            f'Credit to wallet: {credit_amount}'
        )

        if dry_run:
            self.stdout.write(self.style.SUCCESS('[DRY RUN] Would credit wallet and update pair/earning.'))
            return

        with transaction.atomic():
            add_wallet_balance(
                user=user,
                amount=float(credit_amount),
                transaction_type='BINARY_PAIR_COMMISSION',
                description=(
                    f'Correction: extra deduction waived (zero remaining balance) '
                    f'for Pair #{pair.pair_number_after_activation}'
                ),
                reference_id=pair.id,
                reference_type='binary_pair',
            )
            pair.extra_deduction_applied = Decimal('0')
            pair.earning_amount = correct_net
            pair.save(update_fields=['extra_deduction_applied', 'earning_amount'])

            earning = BinaryEarning.objects.filter(binary_pair=pair).first()
            if earning:
                earning.net_amount = correct_net
                earning.save(update_fields=['net_amount'])
                self.stdout.write(self.style.SUCCESS(f'Updated BinaryEarning id={earning.id} net_amount={correct_net}'))

        self.stdout.write(
            self.style.SUCCESS(
                f'Credited {credit_amount} to wallet and set pair earning_amount={correct_net}, '
                f'extra_deduction_applied=0 for pair id={pair.id}.'
            )
        )
