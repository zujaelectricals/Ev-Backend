"""
Management command to backfill TDS_DEDUCTION transactions for existing binary pairs.

This command creates TDS_DEDUCTION wallet transactions for binary pairs that were
processed before the code change that added TDS_DEDUCTION tracking for binary pairs.

Only processes pairs that:
1. Have status='processed' (already processed)
2. Have earning_amount > 0 (not blocked)
3. Don't already have a TDS_DEDUCTION transaction for this pair
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from core.binary.models import BinaryPair, BinaryEarning
from core.wallet.models import WalletTransaction
from core.settings.models import PlatformSettings
from core.binary.utils import deduct_from_booking_balance
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Backfill TDS_DEDUCTION transactions for existing binary pairs'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run in dry-run mode (no changes will be made)',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Process only pairs for a specific user ID (optional)',
        )
        parser.add_argument(
            '--pair-id',
            type=int,
            help='Process only a specific pair ID (optional)',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        user_id = options.get('user_id')
        pair_id = options.get('pair_id')
        
        platform_settings = PlatformSettings.get_settings()
        tds_percentage = platform_settings.binary_commission_tds_percentage
        
        # Build query for pairs to process
        query = BinaryPair.objects.filter(
            status='processed',
            earning_amount__gt=0,
            commission_blocked=False
        )
        
        if user_id:
            query = query.filter(user_id=user_id)
        
        if pair_id:
            query = query.filter(id=pair_id)
        
        pairs = query.select_related('user').order_by('created_at')
        
        if not pairs.exists():
            self.stdout.write(self.style.SUCCESS("No pairs found to process."))
            return
        
        self.stdout.write("=" * 80)
        self.stdout.write(self.style.WARNING("BACKFILL BINARY PAIR TDS_DEDUCTION TRANSACTIONS"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"\nFound {pairs.count()} pairs to process\n")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made\n"))
        
        processed_count = 0
        skipped_count = 0
        error_count = 0
        
        for pair in pairs:
            try:
                # Check if TDS_DEDUCTION already exists for this pair
                existing_tds = WalletTransaction.objects.filter(
                    user=pair.user,
                    transaction_type='TDS_DEDUCTION',
                    reference_id=pair.id,
                    reference_type='binary_pair'
                ).exists()
                
                if existing_tds:
                    if dry_run:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  [SKIP] Pair {pair.id} (User: {pair.user.email}) - "
                                f"TDS_DEDUCTION already exists"
                            )
                        )
                    skipped_count += 1
                    continue
                
                # Calculate TDS amount
                # pair_amount = gross commission (₹2000)
                # earning_amount = net amount after TDS and extra deduction
                # TDS = pair_amount - earning_amount - extra_deduction_applied
                # OR we can calculate: TDS = pair_amount * (tds_percentage / 100)
                
                # Use the calculation method to be consistent
                tds_amount = pair.pair_amount * (Decimal(str(tds_percentage)) / Decimal('100'))
                
                # Verify: pair_amount - tds_amount - extra_deduction_applied should equal earning_amount
                expected_net = pair.pair_amount - tds_amount - pair.extra_deduction_applied
                
                # Allow small rounding differences (within 0.01)
                if abs(expected_net - pair.earning_amount) > Decimal('0.01'):
                    self.stdout.write(
                        self.style.ERROR(
                            f"  [ERROR] Pair {pair.id} (User: {pair.user.email}) - "
                            f"Amount mismatch: Expected net Rs {expected_net}, but earning_amount is Rs {pair.earning_amount}"
                        )
                    )
                    error_count += 1
                    continue
                
                pair_number = pair.pair_number_after_activation or "N/A"
                
                if dry_run:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  [DRY RUN] Would create TDS_DEDUCTION for Pair {pair.id} "
                            f"(User: {pair.user.email}, Pair #{pair_number}): "
                            f"Rs {tds_amount} (from Rs {pair.pair_amount} gross)"
                        )
                    )
                    processed_count += 1
                else:
                    # Create TDS_DEDUCTION transaction using the utility function
                    # This will deduct from booking balance and create the transaction with proper reference
                    success = deduct_from_booking_balance(
                        user=pair.user,
                        deduction_amount=tds_amount,
                        deduction_type='TDS_DEDUCTION',
                        description=f"TDS ({tds_percentage}%) on binary pair commission (Pair #{pair_number}) - Backfilled",
                        reference_id=pair.id,
                        reference_type='binary_pair'
                    )
                    
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  [OK] Created TDS_DEDUCTION for Pair {pair.id} "
                            f"(User: {pair.user.email}, Pair #{pair_number}): Rs {tds_amount}"
                            + (" (deducted from booking)" if success else " (no active booking, transaction created)")
                        )
                    )
                    processed_count += 1
                        
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"  [ERROR] Pair {pair.id} (User: {pair.user.email}): {str(e)}"
                    )
                )
                error_count += 1
                logger.error(f"Error processing pair {pair.id}: {e}", exc_info=True)
        
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"Processed: {processed_count}")
        self.stdout.write(f"Skipped (already exists): {skipped_count}")
        self.stdout.write(f"Errors: {error_count}")
        self.stdout.write(f"Total: {pairs.count()}")
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\nThis was a dry run. Run without --dry-run to apply changes."
                )
            )

