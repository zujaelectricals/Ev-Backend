"""
Management command to fix missing direct user commission payments.

This command identifies cases where:
1. TDS_DEDUCTION transaction exists for a direct user commission
2. But DIRECT_USER_COMMISSION transaction does NOT exist
3. The commission should have been paid (user was eligible at the time)

The command will:
1. Find all TDS_DEDUCTION transactions for direct user commissions
2. Check if corresponding DIRECT_USER_COMMISSION exists
3. Verify the user was eligible for commission at the time
4. Pay the missing commission retroactively (₹800 net after TDS)
"""
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from core.wallet.models import WalletTransaction
from core.binary.models import BinaryNode
from core.users.models import User
from core.binary.utils import has_activation_payment, get_active_descendants_count
from core.wallet.utils import add_wallet_balance
from core.settings.models import PlatformSettings
from decimal import Decimal
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fix missing direct user commission payments'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run in dry-run mode (no changes will be made)',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Process only commissions for a specific user ID (optional)',
        )
        parser.add_argument(
            '--tds-transaction-id',
            type=int,
            help='Process only a specific TDS transaction ID (optional)',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        user_id = options.get('user_id')
        tds_tx_id = options.get('tds_transaction_id')
        
        platform_settings = PlatformSettings.get_settings()
        activation_count = platform_settings.binary_commission_activation_count
        commission_amount = platform_settings.direct_user_commission_amount
        tds_percentage = platform_settings.binary_commission_tds_percentage
        
        # Find all TDS_DEDUCTION transactions for direct user commissions
        # These are identified by reference_type='user' and description containing 'on user commission'
        # Include reversed ones too - we'll check if commission was paid
        query = WalletTransaction.objects.filter(
            transaction_type='TDS_DEDUCTION',
            reference_type='user',
            description__icontains='on user commission'
        )
        
        if user_id:
            query = query.filter(user_id=user_id)
        
        if tds_tx_id:
            query = query.filter(id=tds_tx_id)
        
        tds_transactions = query.select_related('user').order_by('created_at')
        
        if not tds_transactions.exists():
            self.stdout.write(self.style.SUCCESS("No TDS deductions found for direct user commissions."))
            return
        
        self.stdout.write("=" * 80)
        self.stdout.write(self.style.WARNING("FIX MISSING DIRECT USER COMMISSION PAYMENTS"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"\nFound {tds_transactions.count()} TDS deductions to check\n")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made\n"))
        
        fixed_count = 0
        skipped_count = 0
        error_count = 0
        
        for tds_tx in tds_transactions:
            try:
                ancestor_user = tds_tx.user
                new_user_id = tds_tx.reference_id
                
                if not new_user_id:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [SKIP] TDS Transaction {tds_tx.id} - No reference_id (user ID)"
                        )
                    )
                    skipped_count += 1
                    continue
                
                try:
                    new_user = User.objects.get(id=new_user_id)
                except User.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [SKIP] TDS Transaction {tds_tx.id} - Referenced user {new_user_id} not found"
                        )
                    )
                    skipped_count += 1
                    continue
                
                # Check if commission was already paid
                commission_already_paid = WalletTransaction.objects.filter(
                    user=ancestor_user,
                    transaction_type='DIRECT_USER_COMMISSION',
                    reference_id=new_user_id,
                    reference_type='user'
                ).exists()
                
                if commission_already_paid:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  [SKIP] TDS Transaction {tds_tx.id} - Commission already paid for {new_user.email} to {ancestor_user.email}"
                        )
                    )
                    skipped_count += 1
                    continue
                
                # Verify eligibility: Check if ancestor should have received commission
                # Get ancestor's binary node
                try:
                    ancestor_node = BinaryNode.objects.get(user=ancestor_user)
                except BinaryNode.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [SKIP] TDS Transaction {tds_tx.id} - Ancestor {ancestor_user.email} has no binary node"
                        )
                    )
                    skipped_count += 1
                    continue
                
                # Get new user's binary node
                try:
                    new_user_node = BinaryNode.objects.get(user=new_user)
                except BinaryNode.DoesNotExist:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [SKIP] TDS Transaction {tds_tx.id} - New user {new_user.email} has no binary node"
                        )
                    )
                    skipped_count += 1
                    continue
                
                # Check if new_user is in ancestor's tree
                from core.binary.utils import get_all_ancestors
                new_user_ancestors = get_all_ancestors(new_user_node)
                if ancestor_node not in new_user_ancestors:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [SKIP] TDS Transaction {tds_tx.id} - {ancestor_user.email} is not an ancestor of {new_user.email}"
                        )
                    )
                    skipped_count += 1
                    continue
                
                # Check if new user has activation payment (required for commission)
                if not has_activation_payment(new_user):
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [SKIP] TDS Transaction {tds_tx.id} - New user {new_user.email} does not have activation payment"
                        )
                    )
                    skipped_count += 1
                    continue
                
                # Check if ancestor was eligible at the time
                # We need to simulate the state at the time TDS was deducted
                # For safety, check current state and verify binary commission was not activated at that time
                tds_created_at = tds_tx.created_at
                
                # Check if binary commission was already activated at the time of TDS deduction
                # If activation_timestamp exists and is before TDS creation, commission should not be paid
                if ancestor_node.binary_commission_activated and ancestor_node.activation_timestamp:
                    if ancestor_node.activation_timestamp < tds_created_at:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  [SKIP] TDS Transaction {tds_tx.id} - Binary commission was already activated "
                                f"({ancestor_node.activation_timestamp}) before TDS deduction ({tds_created_at})"
                            )
                        )
                        skipped_count += 1
                        continue
                
                # Calculate what the commission should be
                tds_amount = abs(tds_tx.amount)  # TDS transactions have negative amounts
                expected_commission_gross = tds_amount / (tds_percentage / Decimal('100'))
                expected_commission_net = expected_commission_gross - tds_amount
                
                # Verify the TDS amount matches expected calculation
                expected_tds = expected_commission_gross * (tds_percentage / Decimal('100'))
                if abs(expected_tds - tds_amount) > Decimal('0.01'):  # Allow small rounding differences
                    self.stdout.write(
                        self.style.ERROR(
                            f"  [ERROR] TDS Transaction {tds_tx.id} - TDS amount mismatch: "
                            f"Expected Rs {expected_tds}, but TDS is Rs {tds_amount}"
                        )
                    )
                    error_count += 1
                    continue
                
                if dry_run:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  [DRY RUN] Would pay missing commission:\n"
                            f"    TDS Transaction: {tds_tx.id}\n"
                            f"    Ancestor: {ancestor_user.email} (ID: {ancestor_user.id})\n"
                            f"    New User: {new_user.email} (ID: {new_user.id})\n"
                            f"    Gross Commission: Rs {expected_commission_gross}\n"
                            f"    TDS: Rs {tds_amount}\n"
                            f"    Net Commission: Rs {expected_commission_net}\n"
                            f"    TDS Created: {tds_created_at}"
                        )
                    )
                    fixed_count += 1
                else:
                    with db_transaction.atomic():
                        # Double-check commission wasn't paid between dry-run and actual run
                        commission_already_paid_check = WalletTransaction.objects.filter(
                            user=ancestor_user,
                            transaction_type='DIRECT_USER_COMMISSION',
                            reference_id=new_user_id,
                            reference_type='user'
                        ).exists()
                        
                        if commission_already_paid_check:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  [SKIP] TDS Transaction {tds_tx.id} - Commission was paid by another process"
                                )
                            )
                            skipped_count += 1
                            continue
                        
                        # Pay the missing commission
                        try:
                            add_wallet_balance(
                                user=ancestor_user,
                                amount=float(expected_commission_net),
                                transaction_type='DIRECT_USER_COMMISSION',
                                description=f"User commission for {new_user.username} (Rs {expected_commission_gross} - Rs {tds_amount} TDS = Rs {expected_commission_net}) [RETROACTIVE FIX]",
                                reference_id=new_user_id,
                                reference_type='user'
                            )
                            
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"  [OK] Paid missing commission:\n"
                                    f"    TDS Transaction: {tds_tx.id}\n"
                                    f"    Ancestor: {ancestor_user.email}\n"
                                    f"    New User: {new_user.email}\n"
                                    f"    Net Commission: Rs {expected_commission_net} (Gross: Rs {expected_commission_gross}, TDS: Rs {tds_amount})"
                                )
                            )
                            fixed_count += 1
                            
                        except Exception as e:
                            self.stdout.write(
                                self.style.ERROR(
                                    f"  [ERROR] TDS Transaction {tds_tx.id} - Failed to pay commission: {str(e)}"
                                )
                            )
                            error_count += 1
                            logger.error(f"Error paying commission for TDS transaction {tds_tx.id}: {e}", exc_info=True)
                        
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"  [ERROR] TDS Transaction {tds_tx.id if 'tds_tx' in locals() else 'Unknown'}: {str(e)}"
                    )
                )
                error_count += 1
                logger.error(f"Error processing TDS transaction {tds_tx.id if 'tds_tx' in locals() else 'Unknown'}: {e}", exc_info=True)
        
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"Fixed (paid missing commissions): {fixed_count}")
        self.stdout.write(f"Skipped (already paid or not eligible): {skipped_count}")
        self.stdout.write(f"Errors: {error_count}")
        self.stdout.write(f"Total TDS transactions checked: {tds_transactions.count()}")
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\nThis was a dry run. Run without --dry-run to apply changes."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nSUCCESS: Missing direct user commissions have been paid."
                )
            )

