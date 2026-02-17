from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from core.booking.models import Booking, Payment as BookingPayment
from core.booking.utils import generate_booking_receipt_pdf
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Generate payment receipts for existing bookings that are active/completed
    but don't have receipts yet.
    
    This command finds bookings where:
    - status = 'active' or 'completed'
    - total_paid >= booking_amount (booking has been paid)
    - payment_receipt is None (receipt not generated)
    
    It will generate and save PDF receipts for these bookings.
    """

    help = "Generate payment receipts for existing bookings that don't have receipts yet."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be generated without actually generating receipts',
        )
        parser.add_argument(
            '--booking-id',
            type=int,
            help='Generate receipt for a specific booking ID only',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Regenerate receipts even if they already exist',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        booking_id_filter = options.get('booking_id')
        force = options.get('force', False)

        self.stdout.write(self.style.MIGRATE_HEADING("Generating missing payment receipts..."))

        # Find bookings that are active/completed, have been paid, but don't have receipts
        queryset = Booking.objects.filter(
            status__in=['active', 'completed'],
        ).select_related('user', 'vehicle_model')
        
        if not force:
            queryset = queryset.filter(payment_receipt__isnull=True)
        
        # Only bookings where booking_amount has been paid
        # We check total_paid >= booking_amount to ensure booking is confirmed
        from django.db.models import F
        queryset = queryset.filter(
            total_paid__gte=F('booking_amount')
        )
        
        if booking_id_filter:
            queryset = queryset.filter(id=booking_id_filter)
        
        bookings = queryset.all()
        total_count = bookings.count()
        
        if total_count == 0:
            self.stdout.write(self.style.WARNING("No bookings found that need receipts."))
            return

        self.stdout.write(f"Found {total_count} booking(s) that need receipts")

        generated_count = 0
        skipped_count = 0
        error_count = 0

        for booking in bookings:
            try:
                # Skip if receipt exists and not forcing
                if booking.payment_receipt and not force:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Skipping booking {booking.id} ({booking.booking_number}): "
                            f"Receipt already exists"
                        )
                    )
                    skipped_count += 1
                    continue
                
                # Find the first completed payment for this booking (booking payment)
                # This is the payment that made the booking active
                booking_payment = BookingPayment.objects.filter(
                    booking=booking,
                    status='completed'
                ).order_by('payment_date').first()
                
                if not booking_payment:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Skipping booking {booking.id} ({booking.booking_number}): "
                            f"No completed payment found"
                        )
                    )
                    skipped_count += 1
                    continue
                
                if dry_run:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  [DRY RUN] Would generate receipt for booking {booking.id} "
                            f"({booking.booking_number}) - Payment: {booking_payment.id}"
                        )
                    )
                    generated_count += 1
                    continue
                
                # Generate receipt
                with transaction.atomic():
                    try:
                        receipt_file = generate_booking_receipt_pdf(booking, booking_payment)
                        booking.payment_receipt = receipt_file
                        booking.save(update_fields=['payment_receipt'])
                        
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  [OK] Generated receipt for booking {booking.id} "
                                f"({booking.booking_number})"
                            )
                        )
                        generated_count += 1
                    except Exception as e:
                        logger.error(
                            f"Failed to generate receipt for booking {booking.id}: {e}",
                            exc_info=True
                        )
                        self.stdout.write(
                            self.style.ERROR(
                                f"  [ERROR] Failed to generate receipt for booking {booking.id} "
                                f"({booking.booking_number}): {str(e)}"
                            )
                        )
                        error_count += 1
                        
            except Exception as e:
                logger.error(
                    f"Error processing booking {booking.id}: {e}",
                    exc_info=True
                )
                self.stdout.write(
                    self.style.ERROR(
                        f"  [ERROR] Error processing booking {booking.id}: {str(e)}"
                    )
                )
                error_count += 1

        # Summary
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Summary:"))
        self.stdout.write(f"  Total bookings checked: {total_count}")
        self.stdout.write(f"  Receipts generated: {generated_count}")
        self.stdout.write(f"  Skipped: {skipped_count}")
        self.stdout.write(f"  Errors: {error_count}")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("\nThis was a dry run. No receipts were actually generated."))
            self.stdout.write("Run without --dry-run to generate receipts.")

