"""
Correct wallet credit for pair #6 (users 108, 109, etc.).

Pair #6 was credited with 1800 (net after TDS only). Per business rule, wallet
should receive amount after all deductions: 2000 - 200 (TDS) - 400 (extra) = 1400.
We over-credited 400. This command deducts 400 from wallet, reduces total_earned,
and updates BinaryPair.earning_amount and BinaryEarning.net_amount to 1400.
EXTRA_DEDUCTION (400) was correctly applied to booking balance; we do not touch that.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction

from core.users.models import User
from core.binary.models import BinaryPair, BinaryEarning
from core.wallet.models import WalletTransaction
from core.wallet.utils import get_or_create_wallet, deduct_wallet_balance


class Command(BaseCommand):
    help = (
        'Correct pair #6 wallet credit: deduct over-credited 400, set earning_amount/net_amount to 1400. '
        'Use --user-id for specific user (default: 108).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            default=108,
            help='User id to fix (default: 108).',
        )

    def handle(self, *args, **options):
        user_id = options['user_id']
        pair_number = 6
        correct_wallet_amount = Decimal('1400')  # 2000 - 200 - 400

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User id={user_id} not found.'))
            return

        pair = BinaryPair.objects.filter(
            user_id=user_id,
            pair_number_after_activation=pair_number
        ).first()

        if not pair:
            self.stdout.write(
                self.style.WARNING(
                    f'No pair with pair_number_after_activation={pair_number} for user id={user_id}.'
                )
            )
            return

        txns = WalletTransaction.objects.filter(
            user=user,
            transaction_type='BINARY_PAIR_COMMISSION',
            reference_type='binary_pair',
            reference_id=pair.id,
            amount__gt=0,
        )
        total_credited = sum(Decimal(str(t.amount)) for t in txns)

        over_credited = total_credited - correct_wallet_amount
        if over_credited <= 0:
            self.stdout.write(
                self.style.WARNING(
                    f'Pair id={pair.id} credited {total_credited}; expected <={correct_wallet_amount}. Nothing to fix.'
                )
            )
            return

        try:
            with transaction.atomic():
                wallet = get_or_create_wallet(user)
                if wallet.balance < over_credited:
                    raise ValueError(
                        f'Insufficient balance: {wallet.balance} < {over_credited}'
                    )
                deduct_wallet_balance(
                    user=user,
                    amount=float(over_credited),
                    transaction_type='BINARY_PAIR_COMMISSION',
                    description=(
                        f'Correction: Pair #{pair_number} should credit {correct_wallet_amount} '
                        f'(after TDS+extra). Was {total_credited}; deducting {over_credited}. Pair id={pair.id}.'
                    ),
                    reference_id=pair.id,
                    reference_type='binary_pair',
                )
                wallet.refresh_from_db()
                wallet.total_earned -= over_credited
                if wallet.total_earned < 0:
                    wallet.total_earned = Decimal('0')
                wallet.save(update_fields=['total_earned'])

                pair.earning_amount = correct_wallet_amount
                pair.save(update_fields=['earning_amount'])

                BinaryEarning.objects.filter(binary_pair=pair).update(net_amount=correct_wallet_amount)

                self.stdout.write(
                    self.style.SUCCESS(
                        f'Deducted {over_credited} from wallet; set pair id={pair.id} and earning to {correct_wallet_amount}.'
                    )
                )
        except ValueError as e:
            self.stdout.write(self.style.ERROR(f'Aborted: {e}'))
