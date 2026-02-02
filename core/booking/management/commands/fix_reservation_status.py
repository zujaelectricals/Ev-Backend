from django.core.management.base import BaseCommand
from django.db import transaction
from core.booking.models import Booking
from core.inventory.utils import complete_reservation


class Command(BaseCommand):
    """
    Fix reservation status for bookings that have active status and completed payments
    but still have reserved reservations.
    
    This command updates reservations where:
    - booking.status = 'active' (or 'completed')
    - booking has completed payments
    - stock_reservation.status = 'reserved'
    
    It will set reservation status to 'completed'.
    """

    help = "Fix reservation status for bookings with completed payments but reserved reservations."

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

        self.stdout.write(self.style.MIGRATE_HEADING("Fixing reservation status..."))

        # Find bookings that are active/completed but have reserved reservations
        queryset = Booking.objects.filter(
            status__in=['active', 'completed'],
        ).select_related('stock_reservation')
        
        if booking_id_filter:
            queryset = queryset.filter(id=booking_id_filter)
        
        bookings = queryset.all()
        total_count = bookings.count()
        
        if total_count == 0:
            self.stdout.write(self.style.WARNING("No bookings found."))
            return

        self.stdout.write(f"Checking {total_count} booking(s)")

        fixed_count = 0
        skipped_count = 0
        no_reservation_count = 0

        for booking in bookings:
            try:
                reservation = booking.stock_reservation
            except Exception:
                # No reservation exists
                no_reservation_count += 1
                continue
            
            if not reservation:
                no_reservation_count += 1
                continue
            
            # Check if booking has completed payments
            from core.booking.models import Payment as BookingPayment
            completed_payments = BookingPayment.objects.filter(
                booking=booking,
                status='completed'
            ).exists()
            
            has_payment = completed_payments or booking.total_paid >= booking.booking_amount
            
            if not has_payment:
                self.stdout.write(
                    self.style.WARNING(
                        f"  SKIP: Booking {booking.id} ({booking.booking_number}) - "
                        f"No completed payments yet (total_paid: Rs.{booking.total_paid:.2f})"
                    )
                )
                skipped_count += 1
                continue
            
            # Check reservation status
            if reservation.status == 'reserved':
                # Reservation is still reserved, just mark as completed
                if dry_run:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  WOULD FIX: Booking {booking.id} ({booking.booking_number}) - "
                            f"Reservation status: 'reserved' -> 'completed'"
                        )
                    )
                    fixed_count += 1
                else:
                    with transaction.atomic():
                        complete_reservation(reservation)
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  FIXED: Booking {booking.id} ({booking.booking_number}) - "
                                f"Reservation status changed from 'reserved' to 'completed'"
                            )
                        )
                        fixed_count += 1
            elif reservation.status == 'released':
                # Reservation was released (likely expired), but payment is now complete
                # Re-reserve the stock and mark as completed
                if dry_run:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  WOULD FIX: Booking {booking.id} ({booking.booking_number}) - "
                            f"Reservation status: 'released' -> 'completed' (will re-reserve stock)"
                        )
                    )
                    fixed_count += 1
                else:
                    with transaction.atomic():
                        # Re-reserve the stock
                        vehicle_stock = reservation.vehicle_stock
                        if vehicle_stock.available_quantity >= reservation.quantity:
                            # Reserve the stock again
                            vehicle_stock.reserve(quantity=reservation.quantity)
                            # Mark reservation as completed
                            reservation.status = 'completed'
                            reservation.save(update_fields=['status', 'updated_at'])
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"  FIXED: Booking {booking.id} ({booking.booking_number}) - "
                                    f"Reservation status changed from 'released' to 'completed' (stock re-reserved)"
                                )
                            )
                            fixed_count += 1
                        else:
                            # Stock not available, but mark as completed anyway (booking is confirmed)
                            reservation.status = 'completed'
                            reservation.save(update_fields=['status', 'updated_at'])
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  FIXED (no stock): Booking {booking.id} ({booking.booking_number}) - "
                                    f"Reservation marked as 'completed' but stock not available to re-reserve "
                                    f"(available: {vehicle_stock.available_quantity}, needed: {reservation.quantity})"
                                )
                            )
                            fixed_count += 1
            elif reservation.status == 'completed':
                # Already completed, skip
                skipped_count += 1
            else:
                # Unknown status, skip
                self.stdout.write(
                    self.style.WARNING(
                        f"  SKIP: Booking {booking.id} ({booking.booking_number}) - "
                        f"Reservation status is '{reservation.status}' (unknown)"
                    )
                )
                skipped_count += 1

        # Summary
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Summary:"))
        self.stdout.write(f"  Total checked: {total_count}")
        self.stdout.write(f"  Fixed: {fixed_count}")
        self.stdout.write(f"  Skipped: {skipped_count}")
        self.stdout.write(f"  No reservation: {no_reservation_count}")
        
        if dry_run:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("DRY RUN - No changes were made. Run without --dry-run to fix."))

