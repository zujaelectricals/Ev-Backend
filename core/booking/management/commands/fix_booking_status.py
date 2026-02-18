from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from core.booking.models import Booking


class Command(BaseCommand):
    """
    Fix booking status for bookings that have paid booking_amount but are still pending.
    
    This command updates bookings where:
    - status = 'pending'
    - total_paid >= booking_amount
    - confirmed_at is None
    
    It will set status to 'active' and set confirmed_at timestamp.
    """

    help = "Fix booking status for bookings that have paid booking_amount but are still pending."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fixed without actually fixing',
        )
        parser.add_argument(
            '--booking-id',
            type=int,
            help='Fix a specific booking ID only',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        booking_id_filter = options.get('booking_id')

        self.stdout.write(self.style.MIGRATE_HEADING("Fixing booking status..."))

        # Find bookings that should be active but are still pending
        queryset = Booking.objects.filter(
            status='pending',
            confirmed_at__isnull=True
        )
        
        if booking_id_filter:
            queryset = queryset.filter(id=booking_id_filter)
        
        bookings = queryset.all()
        total_count = bookings.count()
        
        if total_count == 0:
            self.stdout.write(self.style.WARNING("No pending bookings found that need fixing."))
            return

        self.stdout.write(f"Found {total_count} pending booking(s)")

        fixed_count = 0
        skipped_count = 0

        for booking in bookings:
            # Check if booking_amount has been paid
            if booking.total_paid >= booking.booking_amount:
                if dry_run:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  WOULD FIX: Booking {booking.id} ({booking.booking_number}) - "
                            f"total_paid: Rs.{booking.total_paid:.2f}, "
                            f"booking_amount: Rs.{booking.booking_amount:.2f}"
                        )
                    )
                    fixed_count += 1
                else:
                    with transaction.atomic():
                        booking.status = 'active'
                        booking.confirmed_at = timezone.now()
                        booking.save(update_fields=['status', 'confirmed_at'])
                        
                        # Update user's Active Buyer status (pass booking for bonus processing)
                        try:
                            booking.user.update_active_buyer_status(booking=booking)
                        except Exception as e:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  Warning: Failed to update active buyer status for user {booking.user.id}: {e}"
                                )
                            )
                        
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  FIXED: Booking {booking.id} ({booking.booking_number}) - "
                                f"Status changed from 'pending' to 'active'"
                            )
                        )
                        fixed_count += 1
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"  SKIP: Booking {booking.id} ({booking.booking_number}) - "
                        f"total_paid (Rs.{booking.total_paid:.2f}) < "
                        f"booking_amount (Rs.{booking.booking_amount:.2f})"
                    )
                )
                skipped_count += 1

        # Summary
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Summary:"))
        self.stdout.write(f"  Total checked: {total_count}")
        self.stdout.write(f"  Fixed: {fixed_count}")
        self.stdout.write(f"  Skipped: {skipped_count}")
        
        if dry_run:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("DRY RUN - No changes were made. Run without --dry-run to fix."))

