from django.db import models
from django.db.models import Sum
from django.utils import timezone
from django.conf import settings
from core.users.models import User
import logging

logger = logging.getLogger(__name__)


class Booking(models.Model):
    """
    EV Booking model
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('active', 'Active Buyer'),
        ('completed', 'Completed'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
    ]

    PAYMENT_OPTION_CHOICES = [
        ('full_payment', 'Full-Payment'),
        ('emi_options', 'EMI-Options')
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookings')
    
    # Booking Details
    booking_number = models.CharField(max_length=50, unique=True)
    vehicle_model = models.ForeignKey('inventory.Vehicle', on_delete=models.PROTECT)
    vehicle_color = models.CharField(max_length=50, null=True, blank=True)
    battery_variant = models.CharField(max_length=50, default='40kWh')
    booking_amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_option = models.CharField(max_length=100, choices=PAYMENT_OPTION_CHOICES, default='full_payment')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    total_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    bonus_applied = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Company bonus debited from remaining balance (not added to total_paid)"
    )
    deductions_applied = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="Non-cash credits (TDS/extra deductions from commission earnings) debited from remaining balance"
    )
    remaining_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Distributor & Program Fields
    referred_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='referred_bookings'
    )
    referrer_was_distributor = models.BooleanField(
        default=False,
        help_text="Whether the referrer was a distributor when this booking was created"
    )
    join_distributor_program = models.BooleanField(default=False)
    
    # Payment & Delivery Fields
    payment_gateway_ref = models.CharField(max_length=150, null=True, blank=True)
    payment_receipt = models.FileField(upload_to='booking_receipts/', null=True, blank=True, help_text="PDF receipt generated after booking payment")
    delivery_city = models.CharField(max_length=100, null=True, blank=True)
    delivery_state = models.CharField(max_length=100, null=True, blank=True)
    delivery_pin = models.CharField(max_length=10, null=True, blank=True)
    
    # Compliance Fields
    terms_accepted = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(null=True, blank=True)
    
    # EMI Details
    emi_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    emi_duration_months = models.IntegerField(null=True, blank=True)
    emi_start_date = models.DateField(null=True, blank=True)
    emi_paid_count = models.IntegerField(default=0)
    emi_total_count = models.IntegerField(default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'bookings'
        verbose_name = 'Booking'
        verbose_name_plural = 'Bookings'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Booking {self.booking_number} - {self.user.username}"
    
    def save(self, *args, **kwargs):
        if not self.booking_number:
            self.booking_number = self.generate_booking_number()

        # remaining_amount = what is still owed after:
        #   - actual customer payments  (total_paid)
        #   - company bonus credit      (bonus_applied)
        #   - non-cash commission credits (deductions_applied)
        self.remaining_amount = self.total_amount - self.total_paid - self.bonus_applied - self.deductions_applied

        if not self.expires_at:
            from datetime import timedelta
            from django.utils import timezone
            self.expires_at = timezone.now() + timedelta(days=30)

        super().save(*args, **kwargs)
    
    def generate_booking_number(self):
        """Generate unique booking number"""
        import random
        import string
        prefix = "EV"
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        return f"{prefix}{suffix}"
    
    def _update_reservation_status_if_needed(self):
        """
        Update stock reservation status to 'completed' if:
        1. Payment has been made (total_paid >= booking_amount), OR
        2. Remaining amount is zero or less
        
        This ensures reservation status reflects payment completion.
        """
        try:
            # For OneToOne relationships, accessing the attribute raises DoesNotExist if it doesn't exist
            # We'll catch ObjectDoesNotExist which is the base class for all DoesNotExist exceptions
            from django.core.exceptions import ObjectDoesNotExist
            try:
                reservation = self.stock_reservation
            except ObjectDoesNotExist:
                # No reservation exists for this booking
                logger.debug(f"No stock reservation found for booking {self.id}")
                return
            
            # Update to 'completed' if:
            # 1. Payment has been made (total_paid >= booking_amount), OR
            # 2. Remaining amount is zero or less
            remaining = self.total_amount - self.total_paid - self.bonus_applied - self.deductions_applied
            should_complete = (
                self.total_paid >= self.booking_amount or  # Initial payment completed
                remaining <= 0  # Full payment completed
            )
            
            if should_complete and reservation.status != 'completed':
                from core.inventory.utils import complete_reservation
                complete_reservation(reservation)
                logger.info(
                    f"Updated reservation status to 'completed' for booking {self.id} "
                    f"(total_paid: {self.total_paid}, remaining: {remaining})"
                )
        except Exception as e:
            # Log errors but don't fail the payment processing
            logger.error(
                f"Error updating reservation status for booking {self.id}: {e}",
                exc_info=True
            )
    
    def make_payment(self, amount, payment_id=None):
        """
        Record payment and update booking status.

        total_paid  = sum of actual customer payments only (no bonus).
        bonus_applied = company bonus that is debited from remaining_balance separately.
        remaining_amount = total_amount - total_paid - bonus_applied  (computed in save()).

        Args:
            amount: Payment amount to add
            payment_id: Optional Payment ID to prevent double-processing the same payment
        """
        from decimal import Decimal

        # Refresh from DB to get latest state
        self.refresh_from_db()

        # Calculate actual sum of completed payments
        _result = self.payments.filter(status='completed').aggregate(total=Sum('amount'))
        completed_payments_sum = Decimal(str(_result['total'] or 0))

        total_paid_decimal = Decimal(str(self.total_paid))
        amount_decimal = Decimal(str(amount))

        # ── Guard 1 ──────────────────────────────────────────────────────────
        # The payment was already saved to the DB (e.g. Payment.save() → DB
        # aggregate) but total_paid hasn't been updated yet.  Detect this by
        # checking:  current_total_paid + this_amount ≈ completed_payments_sum
        # IMPORTANT: this check must run BEFORE we sync total_paid to the DB
        # sum, otherwise the guard can no longer detect the duplicate.
        if abs(total_paid_decimal + amount_decimal - completed_payments_sum) <= Decimal('0.01'):
            logger.info(
                f"Booking {self.id}: payment {amount} already reflected in "
                f"completed_payments_sum ({completed_payments_sum}). "
                f"Syncing total_paid and skipping duplicate add."
            )
            self.total_paid = completed_payments_sum
            if self.total_paid >= self.booking_amount and self.status == 'pending':
                self.status = 'active'
                self.confirmed_at = timezone.now()
            if (self.total_amount - self.total_paid - self.bonus_applied - self.deductions_applied) <= 0 and self.status != 'completed':
                self.status = 'completed'
                self.completed_at = timezone.now()
            self.save()
            # Update reservation status if needed
            self._update_reservation_status_if_needed()
            # Guard 1: payment was already in DB before total_paid was synced.
            # Still trigger active-buyer bonus – the user may have just qualified.
            self.user.update_active_buyer_status(booking=self)
            return self

        # ── Guard 2 ──────────────────────────────────────────────────────────
        # Explicit payment_id check: payment is completed AND already counted
        # (total_paid already matches the DB sum without this payment).
        if payment_id:
            try:
                self.payments.get(id=payment_id, status='completed')
                if abs(total_paid_decimal - completed_payments_sum) <= Decimal('0.01'):
                    logger.info(
                        f"Payment {payment_id} (amount: {amount}) already processed "
                        f"for booking {self.id}. Skipping."
                    )
                    # Update reservation status if needed (even for duplicate calls)
                    self._update_reservation_status_if_needed()
                    # Guard 2: duplicate call – totals are already correct in DB.
                    # Still trigger active-buyer bonus in case it wasn't applied yet.
                    self.user.update_active_buyer_status(booking=self)
                    return self
            except self.payments.model.DoesNotExist:
                pass

        # ── Sync ─────────────────────────────────────────────────────────────
        # If total_paid drifted away from the DB sum for reasons other than the
        # current payment, log a warning and re-anchor before adding.
        if abs(total_paid_decimal - completed_payments_sum) > Decimal('0.01'):
            logger.warning(
                f"Booking {self.id} total_paid mismatch! "
                f"DB total_paid: {self.total_paid}, actual payments: {completed_payments_sum}. "
                f"Re-anchoring before adding new payment."
            )
            self.total_paid = completed_payments_sum
            total_paid_decimal = completed_payments_sum

        # Process the payment – only actual customer payment goes into total_paid
        self.total_paid += amount_decimal

        # Status: 'active' once booking_amount is covered by real payments
        if self.total_paid >= self.booking_amount and self.status == 'pending':
            self.status = 'active'
            self.confirmed_at = timezone.now()

        # Status: 'completed' when nothing remains (payments + bonus + deductions cover total)
        if (self.total_amount - self.total_paid - self.bonus_applied - self.deductions_applied) <= 0:
            self.status = 'completed'
            self.completed_at = timezone.now()

        self.save()
        
        # Update reservation status if payment is completed or remaining amount is zero
        self._update_reservation_status_if_needed()
        
        # Update user's Active Buyer status (pass this booking for bonus processing)
        self.user.update_active_buyer_status(booking=self)
        
        # Trigger Celery task for payment processing
        from core.booking.tasks import payment_completed
        payment_completed.delay(self.id, float(amount))
        
        return self


class Payment(models.Model):
    """
    Payment records for bookings
    """
    PAYMENT_METHOD_CHOICES = [
        ('online', 'Online'),
        ('bank_transfer', 'Bank Transfer'),
        ('cash', 'Cash'),
        ('wallet', 'Wallet'),
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    ]
    
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='payments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payments')
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    transaction_id = models.CharField(max_length=200, unique=True, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    payment_date = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Payment receipt PDF
    receipt = models.FileField(upload_to='payment_receipts/', null=True, blank=True, help_text="PDF receipt generated after payment confirmation")
    
    # Additional details
    notes = models.TextField(blank=True)
    
    class Meta:
        db_table = 'payments'
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'
        ordering = ['-payment_date']
    
    def __str__(self):
        return f"Payment {self.transaction_id} - ₹{self.amount}"
    
    def save(self, *args, **kwargs):
        """Override save to handle status changes"""
        # Track if status is changing to 'completed' to trigger booking update
        status_changing_to_completed = False
        old_status = None
        
        if self.pk:
            try:
                old_instance = Payment.objects.get(pk=self.pk)
                old_status = old_instance.status
                if old_status != 'completed' and self.status == 'completed':
                    status_changing_to_completed = True
                    if not self.completed_at:
                        self.completed_at = timezone.now()
            except Payment.DoesNotExist:
                pass
        elif self.status == 'completed' and not self.completed_at:
            status_changing_to_completed = True
            self.completed_at = timezone.now()
        
        super().save(*args, **kwargs)
        
        # If status changed to 'completed', update booking and complete reservation
        # This handles cases where Payment is created/updated directly (admin, shell, etc.)
        # make_payment() is now idempotent and will check if payment was already processed
        if status_changing_to_completed:
            try:
                booking = self.booking
                booking.make_payment(self.amount, payment_id=self.id)
                # Note: make_payment() now handles reservation completion automatically
                
                # Generate payment receipt if not already generated
                # (Receipts for Razorpay payments are generated in _process_booking_payment)
                if not self.receipt:
                    try:
                        from core.booking.utils import generate_payment_receipt_pdf
                        receipt_file = generate_payment_receipt_pdf(self, razorpay_payment=None)
                        self.receipt = receipt_file
                        # Save again to store the receipt
                        super().save(update_fields=['receipt'])
                        logger.info(f"Generated payment receipt for payment {self.id} (direct payment)")
                        
                        # Send payment receipt email via MSG91 only for the first payment of the booking
                        # Check if this is the first completed payment for this booking
                        # Use Payment.objects (self's class) to avoid circular import
                        completed_payments_count = Payment.objects.filter(
                            booking=self.booking,
                            status='completed'
                        ).exclude(id=self.id).count()
                        
                        # Only send email if this is the first completed payment
                        is_first_payment = completed_payments_count == 0
                        
                        if is_first_payment:
                            try:
                                from core.booking.utils import send_payment_receipt_email_msg91
                                success, error_msg = send_payment_receipt_email_msg91(self)
                                if success:
                                    logger.info(
                                        f"Payment receipt email sent successfully for first payment {self.id} "
                                        f"of booking {self.booking.id}"
                                    )
                                else:
                                    logger.warning(f"Failed to send payment receipt email for payment {self.id}: {error_msg}")
                            except Exception as email_error:
                                logger.error(
                                    f"Error sending payment receipt email for payment {self.id}: {email_error}",
                                    exc_info=True
                                )
                                # Don't fail payment processing if email sending fails
                        else:
                            logger.info(
                                f"Skipping payment receipt email for payment {self.id} - "
                                f"not the first payment for booking {self.booking.id} "
                                f"(completed payments count: {completed_payments_count})"
                            )
                    except Exception as receipt_error:
                        logger.error(
                            f"Failed to generate payment receipt for payment {self.id}: {receipt_error}",
                            exc_info=True
                        )
                        # Don't fail payment processing if receipt generation fails
            except Exception as e:
                # Log but don't fail - booking might not exist or other error
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to update booking for payment {self.id}: {e}")

