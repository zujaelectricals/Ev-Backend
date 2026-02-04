"""
Management command to fix incorrect TDS deductions from booking balance for direct user commissions.

This command reverses TDS deductions that were incorrectly applied to booking balance
for direct user commissions. According to the business rules:
- Direct user commissions: TDS is calculated and reduces net amount, but NOT deducted from booking balance
- Only extra deduction (binary_extra_deduction_percentage) for pairs 6+ is deducted from booking balance

The command will:
1. Find all direct user commission TDS_DEDUCTION transactions
2. Reverse those TDS deductions from booking balance (decrease total_paid, increase remaining_amount)
3. Mark the TDS_DEDUCTION transactions as reversed (optional)
"""
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from core.wallet.models import WalletTransaction
from core.booking.models import Booking
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fix incorrect TDS deductions from booking balance for direct user commissions'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Run in dry-run mode (no changes will be made)',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Process only TDS deductions for a specific user ID (optional)',
        )
        parser.add_argument(
            '--remove-tds-transactions',
            action='store_true',
            help='Remove the incorrect TDS_DEDUCTION transactions (default: keep them for audit)',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        user_id = options.get('user_id')
        remove_tds = options.get('remove_tds_transactions', False)
        
        # Find all TDS_DEDUCTION transactions for direct user commissions
        # These are identified by reference_type='user' and description containing 'on user commission'
        query = WalletTransaction.objects.filter(
            transaction_type='TDS_DEDUCTION',
            reference_type='user',
            description__icontains='on user commission'
        )
        
        if user_id:
            query = query.filter(user_id=user_id)
        
        tds_transactions = query.select_related('user').order_by('created_at')
        
        if not tds_transactions.exists():
            self.stdout.write(self.style.SUCCESS("No TDS deductions found for direct user commissions."))
            return
        
        self.stdout.write("=" * 80)
        self.stdout.write(self.style.WARNING("FIX INCORRECT TDS DEDUCTIONS FOR DIRECT USER COMMISSIONS"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"\nFound {tds_transactions.count()} TDS deductions to reverse\n")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made\n"))
        
        fixed_count = 0
        skipped_count = 0
        error_count = 0
        
        # Group by user to process all TDS deductions for each user
        from collections import defaultdict
        user_tds_map = defaultdict(list)
        for tx in tds_transactions:
            user_tds_map[tx.user].append(tx)
        
        for user, txs in user_tds_map.items():
            try:
                # Calculate total TDS amount that was incorrectly deducted
                # TDS_DEDUCTION transactions have negative amounts, so we sum them and take absolute value
                total_tds_deducted = abs(sum(tx.amount for tx in txs))
                
                # Find active bookings for this user
                active_bookings = Booking.objects.filter(
                    user=user,
                    status__in=['pending', 'active'],
                    remaining_amount__gt=0
                ).order_by('created_at')
                
                if not active_bookings.exists():
                    # No active booking to reverse from - try to find any booking
                    all_bookings = Booking.objects.filter(
                        user=user
                    ).order_by('created_at')
                    
                    if not all_bookings.exists():
                        self.stdout.write(
                            self.style.WARNING(
                                f"  [SKIP] User {user.email} - "
                                f"No booking found to reverse TDS deduction of Rs {total_tds_deducted}"
                            )
                        )
                        skipped_count += len(txs)
                        continue
                    
                    # Use the oldest booking (even if completed)
                    booking = all_bookings.first()
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [NOTE] User {user.email} - No active booking, using oldest booking {booking.booking_number} "
                            f"(status: {booking.status})"
                        )
                    )
                else:
                    # Use the oldest active booking (same logic as deduction)
                    booking = active_bookings.first()
                
                if dry_run:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  [DRY RUN] Would reverse TDS deductions for User {user.email}: "
                            f"Rs {total_tds_deducted} from booking {booking.booking_number}\n"
                            f"    Current booking state: total_paid={booking.total_paid}, "
                            f"remaining_amount={booking.remaining_amount}\n"
                            f"    After reversal: total_paid={booking.total_paid - total_tds_deducted}, "
                            f"remaining_amount={booking.remaining_amount + total_tds_deducted}\n"
                            f"    TDS transactions to {'remove' if remove_tds else 'keep'}: {len(txs)}"
                        )
                    )
                    fixed_count += len(txs)
                else:
                    with db_transaction.atomic():
                        # Reverse the TDS deduction from booking balance
                        booking.total_paid -= total_tds_deducted
                        booking.remaining_amount = booking.total_amount - booking.total_paid
                        
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
                            for tx in txs:
                                tx.delete()
                            tds_action = "removed"
                        else:
                            # Keep transactions but mark them as reversed in description
                            for tx in txs:
                                tx.description = f"{tx.description} [REVERSED - TDS should not be deducted from booking balance]"
                                tx.save(update_fields=['description'])
                            tds_action = "marked as reversed"
                        
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  [OK] Reversed TDS deductions for User {user.email}: "
                                f"Rs {total_tds_deducted} from booking {booking.booking_number}\n"
                                f"    Booking updated: total_paid={booking.total_paid}, "
                                f"remaining_amount={booking.remaining_amount}\n"
                                f"    TDS transactions: {tds_action} ({len(txs)} transactions)"
                            )
                        )
                        fixed_count += len(txs)
                        
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"  [ERROR] User {user.email if user else 'N/A'}: {str(e)}"
                    )
                )
                error_count += len(txs)
                logger.error(f"Error processing TDS deductions for user {user.id}: {e}", exc_info=True)
        
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write("=" * 80)
        self.stdout.write(f"Fixed (reversed TDS deductions): {fixed_count}")
        self.stdout.write(f"Skipped (no booking found): {skipped_count}")
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
                    "\nSUCCESS: TDS deductions from direct user commissions have been reversed from booking balances."
                )
            )

