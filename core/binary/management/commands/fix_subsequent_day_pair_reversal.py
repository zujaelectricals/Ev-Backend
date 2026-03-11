"""
Reverse the 6th binary pair and its commission for user unni1@toqse.com (user_id=109).

That pair was created on a subsequent day without a new weak-leg member (equal left/right
counts were not treated as weak leg, so the subsequent-day rule did not apply). After
fixing the logic (right=weak when equal), we reverse the incorrectly created pair and
commission for this user.
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
        'Reverse the 6th binary pair and commission for user_id=109 (unni1@toqse.com) '
        'created on subsequent day without new weak-leg member.'
    )

    def handle(self, *args, **options):
        user_id = 109  # unni1@toqse.com
        pair_number = 6

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
                    f'No pair with pair_number_after_activation={pair_number} for user id={user_id}. Nothing to fix.'
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

        if total_credited <= 0:
            self.stdout.write(
                self.style.WARNING(
                    f'Pair id={pair.id} had no positive commission credited. '
                    f'Deleting pair and earning only.'
                )
            )

        try:
            with transaction.atomic():
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
                            f'Reversal: pair #{pair_number} created on subsequent day without new weak-leg member '
                            f'(data fix). Pair id={pair.id}.'
                        ),
                        reference_id=pair.id,
                        reference_type='binary_pair',
                    )
                    wallet.refresh_from_db()
                    wallet.total_earned -= total_credited
                    if wallet.total_earned < 0:
                        wallet.total_earned = Decimal('0')
                    wallet.save(update_fields=['total_earned'])
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Reversed commission for pair id={pair.id}: {total_credited}'
                        )
                    )
                BinaryEarning.objects.filter(binary_pair=pair).delete()
                pair_id = pair.id
                pair.delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Deleted pair id={pair_id} and its earning. User {user.email} now has 5 binary pairs.'
                    )
                )
        except ValueError as e:
            self.stdout.write(self.style.ERROR(f'Aborted: {e}'))
