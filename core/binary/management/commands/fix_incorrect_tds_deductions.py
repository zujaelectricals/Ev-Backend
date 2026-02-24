"""
Management command to fix incorrect TDS deductions from booking balance for binary pairs 1-5.

This command reverses TDS deductions that were incorrectly applied to booking balance
for pairs 1-5. According to the business rules:
- Pairs 1-5: TDS is calculated and reduces net amount, but NOT deducted from booking balance
- Pairs 6+: TDS is deducted from booking balance (correct behavior)

The command will:
1. Find all binary pairs 1-5 that have TDS_DEDUCTION transactions
2. Reverse those TDS deductions from booking balance (decrease total_paid, increase remaining_amount)
3. Mark the TDS_DEDUCTION transactions as reversed (optional)
"""
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from core.binary.models import BinaryPair
from core.wallet.models import WalletTransaction
from core.booking.models import Booking
from core.settings.models import PlatformSettings
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fix incorrect TDS deductions from booking balance for binary pairs 1-5'

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
        parser.add_argument(
            '--remove-tds-transactions',
            action='store_true',
            help='Remove the incorrect TDS_DEDUCTION transactions (default: keep them for audit)',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        user_id = options.get('user_id')
        pair_id = options.get('pair_id')
        remove_tds = options.get('remove_tds_transactions', False)
        
        platform_settings = PlatformSettings.get_settings()
        tds_threshold = platform_settings.binary_tds_threshold_pairs  # Usually 5
        
        # Build query for pairs to process
        # Find pairs 1-5 (pair_number_after_activation <= tds_threshold)
        query = BinaryPair.objects.filter(
            pair_number_after_activation__isnull=False,
            pair_number_after_activation__lte=tds_threshold,
            status__in=['matched', 'processed']
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
        self.stdout.write(self.style.WARNING("FIX INCORRECT TDS DEDUCTIONS FOR PAIRS 1-5"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"\nFound {pairs.count()} pairs to check (pairs 1-{tds_threshold})\n")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made\n"))
        
        fixed_count = 0
        skipped_count = 0
        error_count = 0
        
        for pair in pairs:
            try:
                # Find TDS_DEDUCTION transactions for this pair
                tds_transactions = WalletTransaction.objects.filter(
                    user=pair.user,
                    transaction_type='TDS_DEDUCTION',
                    reference_id=pair.id,
                    reference_type='binary_pair'
                )
                
                if not tds_transactions.exists():
                    # No TDS deduction found for this pair - correct behavior
                    skipped_count += 1
                    continue
                
                # Calculate total TDS amount that was incorrectly deducted
                # TDS_DEDUCTION transactions have negative amounts, so we sum them and take absolute value
                total_tds_deducted = abs(sum(tx.amount for tx in tds_transactions))
                
                # Find active bookings for this user
                active_bookings = Booking.objects.filter(
                    user=pair.user,
                    status__in=['pending', 'active'],
                    remaining_amount__gt=0
                ).order_by('created_at')
                
                if not active_bookings.exists():
                    # No active booking to reverse from - try to find any booking
                    all_bookings = Booking.objects.filter(
                        user=pair.user
                    ).order_by('created_at')
                    
                    if not all_bookings.exists():
                        self.stdout.write(
                            self.style.WARNING(
                                f"  [SKIP] Pair {pair.id} (User: {pair.user.email}, Pair #{pair.pair_number_after_activation}) - "
                                f"No booking found to reverse TDS deduction of Rs {total_tds_deducted}"
                            )
                        )
                        skipped_count += 1
                        continue
                    
                    # Use the oldest booking (even if completed)
                    booking = all_bookings.first()
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [NOTE] Pair {pair.id} - No active booking, using oldest booking {booking.booking_number} "
                            f"(status: {booking.status})"
                        )
                    )
                else:
                    # Use the oldest active booking (same logic as deduction)
                    booking = active_bookings.first()
                
                pair_number = pair.pair_number_after_activation
                
                if dry_run:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  [DRY RUN] Would reverse TDS deduction for Pair {pair.id} "
                            f"(User: {pair.user.email}, Pair #{pair_number}): "
                            f"Rs {total_tds_deducted} from booking {booking.booking_number}\n"
                            f"    Current booking state: total_paid={booking.total_paid}, "
                            f"remaining_amount={booking.remaining_amount}\n"
                            f"    After reversal: total_paid={booking.total_paid - total_tds_deducted}, "
                            f"remaining_amount={booking.remaining_amount + total_tds_deducted}\n"
                            f"    TDS transactions to {'remove' if remove_tds else 'keep'}: {tds_transactions.count()}"
                        )
                    )
                    fixed_count += 1
                else:
                    with db_transaction.atomic():
                        # Reverse the TDS deduction from booking balance.
                        # TDS deductions are stored in deductions_applied (not total_paid).
                        booking.deductions_applied = max(
                            Decimal('0'),
                            Decimal(str(booking.deductions_applied)) - Decimal(str(total_tds_deducted))
                        )
                        booking.remaining_amount = (
                            booking.total_amount - booking.total_paid
                            - booking.bonus_applied - booking.deductions_applied
                        )

                        # Update booking status if needed
                        if booking.remaining_amount <= 0:
                            booking.status = 'completed'
                            if not booking.completed_at:
                                from django.utils import timezone
                                booking.completed_at = timezone.now()
                        
                        booking.save()
                        
                        # Handle TDS transactions
                        if remove_tds:
                            # Remove the incorrect TDS_DEDUCTION transactions
                            tds_transactions.delete()
                            tds_action = "removed"
                        else:
                            # Keep transactions but mark them as reversed in description
                            for tx in tds_transactions:
                                tx.description = f"{tx.description} [REVERSED - Incorrectly deducted for pair 1-5]"
                                tx.save(update_fields=['description'])
                            tds_action = "marked as reversed"
                        
                        # Create a reversal transaction for audit trail (optional - for tracking)
                        # Note: We don't need to create a wallet transaction since we're just reversing booking balance
                        # The booking balance change is already done above
                        
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  [OK] Reversed TDS deduction for Pair {pair.id} "
                                f"(User: {pair.user.email}, Pair #{pair_number}): "
                                f"Rs {total_tds_deducted} from booking {booking.booking_number}\n"
                                f"    Booking updated: total_paid={booking.total_paid}, "
                                f"remaining_amount={booking.remaining_amount}\n"
                                f"    TDS transactions: {tds_action}"
                            )
                        )
                        fixed_count += 1
                        
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"  [ERROR] Pair {pair.id} (User: {pair.user.email if pair.user else 'N/A'}): {str(e)}"
                    )
                )
                error_count += 1
                logger.error(f"Error processing pair {pair.id}: {e}", exc_info=True)
        
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"Fixed (reversed TDS deductions): {fixed_count}")
        self.stdout.write(f"Skipped (no TDS deduction found or no active booking): {skipped_count}")
        self.stdout.write(f"Errors: {error_count}")
        self.stdout.write(f"Total pairs checked: {pairs.count()}")
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\nThis was a dry run. Run without --dry-run to apply changes."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "\nSUCCESS: TDS deductions have been reversed from booking balances."
                )
            )

