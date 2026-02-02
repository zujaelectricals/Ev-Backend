from django.core.management.base import BaseCommand
from django.db import transaction
from core.payments.models import Payment as RazorpayPayment
from core.payments.views import _process_booking_payment


class Command(BaseCommand):
    """
    Process existing successful Razorpay payments that haven't been processed yet.
    
    This command retroactively creates booking Payment records and updates booking
    status for Razorpay payments that were verified but didn't trigger the booking
    payment processing (due to the bug that was fixed).
    """

    help = "Process existing successful Razorpay payments that haven't been processed yet."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without actually processing',
        )
        parser.add_argument(
            '--order-id',
            type=str,
            help='Process a specific order_id only',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        order_id_filter = options.get('order_id')

        self.stdout.write(self.style.MIGRATE_HEADING("Processing Razorpay payments..."))

        # Find all successful Razorpay payments
        queryset = RazorpayPayment.objects.filter(status='SUCCESS')
        
        if order_id_filter:
            queryset = queryset.filter(order_id=order_id_filter)
        
        payments = queryset.select_related('content_type', 'user').all()
        total_count = payments.count()
        
        if total_count == 0:
            self.stdout.write(self.style.WARNING("No successful Razorpay payments found."))
            return

        self.stdout.write(f"Found {total_count} successful Razorpay payment(s)")

        processed_count = 0
        skipped_count = 0
        error_count = 0

        for razorpay_payment in payments:
            try:
                if dry_run:
                    # Check if booking payment already exists
                    from core.booking.models import Booking, Payment as BookingPayment
                    
                    if razorpay_payment.content_type is None or razorpay_payment.object_id is None:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  SKIP: {razorpay_payment.order_id} - No content_object"
                            )
                        )
                        skipped_count += 1
                        continue
                    
                    try:
                        booking = razorpay_payment.content_object
                        if not isinstance(booking, Booking):
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  SKIP: {razorpay_payment.order_id} - Not a booking payment"
                                )
                            )
                            skipped_count += 1
                            continue
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(
                                f"  ERROR: {razorpay_payment.order_id} - Could not get content_object: {e}"
                            )
                        )
                        error_count += 1
                        continue
                    
                    # Check if already processed
                    existing = BookingPayment.objects.filter(
                        booking=booking,
                        transaction_id=razorpay_payment.payment_id or razorpay_payment.order_id
                    ).first()
                    
                    if existing:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  SKIP: {razorpay_payment.order_id} - Already processed (Booking Payment ID: {existing.id})"
                            )
                        )
                        skipped_count += 1
                    else:
                        amount_rupees = razorpay_payment.amount / 100
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  WOULD PROCESS: {razorpay_payment.order_id} - "
                                f"Booking {booking.id} ({booking.booking_number}) - "
                                f"Amount: Rs.{amount_rupees:.2f}"
                            )
                        )
                        processed_count += 1
                else:
                    # Actually process the payment
                    booking_payment, booking = _process_booking_payment(razorpay_payment)
                    
                    if booking_payment and booking:
                        amount_rupees = razorpay_payment.amount / 100
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  PROCESSED: {razorpay_payment.order_id} - "
                                f"Booking {booking.id} ({booking.booking_number}) - "
                                f"Amount: Rs.{amount_rupees:.2f} - "
                                f"Booking Payment ID: {booking_payment.id}"
                            )
                        )
                        processed_count += 1
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  SKIP: {razorpay_payment.order_id} - Not a booking payment or already processed"
                            )
                        )
                        skipped_count += 1

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"  ERROR processing {razorpay_payment.order_id}: {e}"
                    )
                )
                error_count += 1

        # Summary
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Summary:"))
        self.stdout.write(f"  Total found: {total_count}")
        self.stdout.write(f"  Processed: {processed_count}")
        self.stdout.write(f"  Skipped: {skipped_count}")
        self.stdout.write(f"  Errors: {error_count}")
        
        if dry_run:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("DRY RUN - No changes were made. Run without --dry-run to process."))

