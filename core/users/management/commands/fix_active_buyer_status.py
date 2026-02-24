from django.core.management.base import BaseCommand
from django.db import transaction
from core.users.models import User
from core.booking.models import Booking
from core.settings.models import PlatformSettings
from django.db.models import Sum


class Command(BaseCommand):
    """
    Recalculate and fix Active Buyer status for all users.
    
    This command:
    - Recalculates total_paid for each user from their active/completed bookings
    - Compares against activation_amount setting
    - Updates is_active_buyer flag accordingly
    - Shows users who were incorrectly marked as active buyers
    - Shows users who should be active buyers but aren't
    """

    help = "Recalculate and fix Active Buyer status for all users based on actual payments."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fixed without actually fixing',
        )
        parser.add_argument(
            '--user-id',
            type=int,
            help='Fix a specific user ID only',
        )
        parser.add_argument(
            '--email',
            type=str,
            help='Fix a specific user by email',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        user_id_filter = options.get('user_id')
        email_filter = options.get('email')

        self.stdout.write(self.style.MIGRATE_HEADING("Recalculating Active Buyer status..."))

        # Get activation_amount from settings
        platform_settings = PlatformSettings.get_settings()
        activation_amount = platform_settings.activation_amount
        self.stdout.write(f"Activation Amount: Rs.{activation_amount:.2f}")
        self.stdout.write("")

        # Get all users
        queryset = User.objects.all()
        
        if user_id_filter:
            queryset = queryset.filter(id=user_id_filter)
        elif email_filter:
            queryset = queryset.filter(email=email_filter)
        
        users = queryset.all()
        total_count = users.count()

        if total_count == 0:
            self.stdout.write(self.style.WARNING("No users found."))
            return

        self.stdout.write(f"Checking {total_count} user(s)")
        self.stdout.write("")

        fixed_count = 0
        incorrect_active_count = 0
        missing_active_count = 0
        correct_count = 0

        for user in users:
            # Calculate from actual completed Payment records (not bookings.total_paid).
            # bookings.total_paid no longer includes the company bonus; using Payment records
            # is the authoritative source and is consistent with update_active_buyer_status().
            from core.booking.models import Payment as BookingPayment
            total_paid = BookingPayment.objects.filter(
                booking__user=user,
                booking__status__in=['active', 'completed'],
                status='completed'
            ).aggregate(total=Sum('amount'))['total'] or 0

            # Determine correct status
            should_be_active = total_paid >= activation_amount
            currently_active = user.is_active_buyer

            # Check if status is correct
            if should_be_active == currently_active:
                correct_count += 1
                if not dry_run:
                    continue  # Skip if already correct
            else:
                if should_be_active and not currently_active:
                    missing_active_count += 1
                    status_msg = self.style.WARNING(
                        f"  MISSING: User {user.id} ({user.email or user.username}) - "
                        f"Should be Active Buyer (total_paid: Rs.{total_paid:.2f} >= Rs.{activation_amount:.2f})"
                    )
                else:
                    incorrect_active_count += 1
                    status_msg = self.style.ERROR(
                        f"  INCORRECT: User {user.id} ({user.email or user.username}) - "
                        f"Should NOT be Active Buyer (total_paid: Rs.{total_paid:.2f} < Rs.{activation_amount:.2f})"
                    )
                
                self.stdout.write(status_msg)
                
                if not dry_run:
                    with transaction.atomic():
                        # Update status
                        user.is_active_buyer = should_be_active
                        user.save(update_fields=['is_active_buyer'])
                        
                        # If user just became active buyer, process bonus
                        if should_be_active:
                            try:
                                # Find the latest booking that contributed to active buyer status
                                booking = Booking.objects.filter(
                                    user=user,
                                    status__in=['active', 'completed']
                                ).order_by('-updated_at', '-created_at').first()
                                
                                if booking:
                                    from core.booking.utils import process_active_buyer_bonus
                                    bonus_applied = process_active_buyer_bonus(user, booking)
                                    if bonus_applied:
                                        self.stdout.write(
                                            self.style.SUCCESS(
                                                f"    ✓ Active buyer bonus applied to booking {booking.booking_number}"
                                            )
                                        )
                            except Exception as e:
                                self.stdout.write(
                                    self.style.WARNING(
                                        f"    ⚠ Warning: Failed to process bonus: {e}"
                                    )
                                )
                        
                        fixed_count += 1

        # Summary
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Summary:"))
        self.stdout.write(f"  Total users checked: {total_count}")
        self.stdout.write(f"  Correct status: {correct_count}")
        self.stdout.write(f"  Missing Active Buyer status: {missing_active_count}")
        self.stdout.write(f"  Incorrect Active Buyer status: {incorrect_active_count}")
        if not dry_run:
            self.stdout.write(f"  Fixed: {fixed_count}")
        
        if dry_run:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("DRY RUN - No changes were made. Run without --dry-run to fix."))
        else:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("Active Buyer statuses have been recalculated and fixed."))

