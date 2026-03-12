"""
Management command to fix missing direct user commission payments.

Commission is paid to the user whose referral code was used (code owner), not the tree parent.
This command finds users who have activation payment and are in the tree, whose code owner
has not yet been paid, and pays the code owner if eligible.

Options:
  --dry-run: Report what would be paid without making changes.
  --user-id: Process only the given user ID (the paying user / new_user).
"""
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from core.wallet.models import WalletTransaction
from core.binary.models import BinaryNode
from core.users.models import User
from core.binary.utils import (
    has_activation_payment,
    get_active_descendants_count,
    get_referrer_for_user,
    is_node_in_tree,
)
from core.wallet.utils import add_wallet_balance
from core.settings.models import PlatformSettings
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fix missing direct user commission payments (code owner policy)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run in dry-run mode (no changes will be made)',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Process only commissions for a specific paying user ID (new_user)',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        user_id = options.get('user_id')

        platform_settings = PlatformSettings.get_settings()
        activation_count = platform_settings.binary_commission_activation_count
        commission_amount = platform_settings.direct_user_commission_amount
        tds_percentage = platform_settings.binary_commission_tds_percentage
        company_referral_code = (platform_settings.company_referral_code or '').strip().upper()

        # Users who have a binary node (are in the tree)
        node_user_ids = list(BinaryNode.objects.values_list('user_id', flat=True).distinct())
        if not node_user_ids:
            self.stdout.write(self.style.SUCCESS("No users in binary tree."))
            return

        candidates = User.objects.filter(id__in=node_user_ids)
        if user_id:
            candidates = candidates.filter(id=user_id)
        if not candidates.exists():
            self.stdout.write(self.style.SUCCESS("No candidate users found."))
            return

        # Restrict to users who have activation payment
        new_users = [u for u in candidates if has_activation_payment(u)]
        if not new_users:
            self.stdout.write(self.style.SUCCESS("No users with activation payment found."))
            return

        self.stdout.write("=" * 80)
        self.stdout.write(self.style.WARNING("FIX MISSING DIRECT USER COMMISSION (CODE OWNER)"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"\nChecking {len(new_users)} user(s) with activation payment\n")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made\n"))

        fixed_count = 0
        skipped_count = 0
        error_count = 0

        for new_user in new_users:
            try:
                code_owner = get_referrer_for_user(new_user)
                if not code_owner:
                    skipped_count += 1
                    continue

                try:
                    new_user_node = BinaryNode.objects.get(user=new_user)
                    owner_node = BinaryNode.objects.get(user=code_owner)
                except BinaryNode.DoesNotExist:
                    skipped_count += 1
                    continue

                if not is_node_in_tree(new_user_node, code_owner):
                    skipped_count += 1
                    continue

                commission_already_paid = WalletTransaction.objects.filter(
                    user=code_owner,
                    transaction_type='DIRECT_USER_COMMISSION',
                    reference_id=new_user.id,
                    reference_type='user'
                ).exists()
                if commission_already_paid:
                    skipped_count += 1
                    continue

                # Company referral code check
                if company_referral_code and code_owner.referral_code:
                    if (code_owner.referral_code or '').strip().upper() == company_referral_code:
                        skipped_count += 1
                        continue

                if owner_node.binary_commission_activated:
                    skipped_count += 1
                    continue

                active_descendants = get_active_descendants_count(owner_node)
                if has_activation_payment(new_user):
                    count_before = active_descendants - 1
                else:
                    count_before = active_descendants
                if count_before >= activation_count:
                    skipped_count += 1
                    continue

                tds_amount = commission_amount * (tds_percentage / Decimal('100'))
                net_amount = commission_amount - tds_amount

                if dry_run:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  [DRY RUN] Would pay: code_owner={code_owner.email}, new_user={new_user.email}, "
                            f"net=Rs {net_amount}"
                        )
                    )
                    fixed_count += 1
                else:
                    with db_transaction.atomic():
                        again = WalletTransaction.objects.filter(
                            user=code_owner,
                            transaction_type='DIRECT_USER_COMMISSION',
                            reference_id=new_user.id,
                            reference_type='user'
                        ).exists()
                        if again:
                            skipped_count += 1
                            continue
                        try:
                            add_wallet_balance(
                                user=code_owner,
                                amount=float(net_amount),
                                transaction_type='DIRECT_USER_COMMISSION',
                                description=(
                                    f"User commission for {new_user.username} "
                                    f"(Rs {commission_amount} - Rs {tds_amount} TDS = Rs {net_amount}) [RETROACTIVE FIX]"
                                ),
                                reference_id=new_user.id,
                                reference_type='user'
                            )
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"  [OK] Paid code_owner={code_owner.email} for new_user={new_user.email}, net=Rs {net_amount}"
                                )
                            )
                            fixed_count += 1
                        except Exception as e:
                            self.stdout.write(
                                self.style.ERROR(
                                    f"  [ERROR] Failed to pay commission for new_user {new_user.id}: {str(e)}"
                                )
                            )
                            error_count += 1
                            logger.error(f"Error paying commission for new_user {new_user.id}: {e}", exc_info=True)

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"  [ERROR] Processing new_user {getattr(new_user, 'id', '?')}: {str(e)}"
                    )
                )
                error_count += 1
                logger.error(f"Error in fix_missing_direct_commissions: {e}", exc_info=True)

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"Fixed (paid missing commissions to code owner): {fixed_count}")
        self.stdout.write(f"Skipped: {skipped_count}")
        self.stdout.write(f"Errors: {error_count}")
        self.stdout.write(f"Users checked: {len(new_users)}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\nThis was a dry run. Run without --dry-run to apply changes."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nSUCCESS: Missing direct user commissions have been paid to code owners."
                )
            )
