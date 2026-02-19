from django.db import models
from django.utils import timezone
from django.conf import settings
from core.users.models import User


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

        self.remaining_amount = self.total_amount - self.total_paid

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
    
    def make_payment(self, amount, payment_id=None):
        """
        Record payment and update booking status.
        
        Args:
            amount: Payment amount to add
            payment_id: Optional Payment ID to prevent double-processing the same payment
        """
        from decimal import Decimal
        
        # Refresh from DB to get latest state
        self.refresh_from_db()
        
        # Calculate actual sum of completed payments (source of truth)
        completed_payments_sum = sum(
            Decimal(str(p.amount)) 
            for p in self.payments.filter(status='completed')
        )
        
        # Import logger for logging
        import logging
        logger = logging.getLogger(__name__)
        
        # CRITICAL: If total_paid doesn't match actual payments, sync it first
        # This prevents issues where total_paid is incorrect due to previous errors
        # BUT: Preserve bonuses (like active buyer bonus) that are added to total_paid
        # Check if user has received active buyer bonus
        from core.wallet.models import WalletTransaction
        has_active_buyer_bonus = WalletTransaction.objects.filter(
            user=self.user,
            transaction_type='ACTIVE_BUYER_BONUS',
            reference_id=self.id,
            reference_type='booking'
        ).exists()
        
        bonus_amount = Decimal('5000.00') if has_active_buyer_bonus else Decimal('0.00')
        expected_total_with_bonus = completed_payments_sum + bonus_amount
        
        # Only sync if total_paid is significantly different AND not due to bonus
        # If total_paid is greater than payments_sum by exactly the bonus amount, preserve it
        total_paid_decimal = Decimal(str(self.total_paid))
        difference = abs(total_paid_decimal - completed_payments_sum)
        
        if difference > Decimal('0.01'):
            # Check if the difference is due to bonus
            if has_active_buyer_bonus and abs(total_paid_decimal - expected_total_with_bonus) <= Decimal('0.01'):
                # total_paid includes bonus, which is correct - don't sync
                logger.debug(
                    f"Booking {self.id} total_paid includes active buyer bonus. "
                    f"total_paid: {self.total_paid}, payments: {completed_payments_sum}, bonus: {bonus_amount}"
                )
            elif total_paid_decimal < completed_payments_sum:
                # total_paid is less than payments - this is an error, sync it
                # But check if the current payment is already included in completed_payments_sum
                # If payment_id is provided and payment exists, check if it's in the sum
                payment_already_included = False
                if payment_id:
                    try:
                        Payment = self.payments.model
                        payment = self.payments.get(id=payment_id, status='completed')
                        # Payment exists - it's already in completed_payments_sum
                        payment_already_included = True
                    except self.payments.model.DoesNotExist:
                        pass
                
                logger.warning(
                    f"Booking {self.id} total_paid is less than actual payments! "
                    f"DB total_paid: {self.total_paid}, Actual payments sum: {completed_payments_sum}. "
                    f"Syncing total_paid to match actual payments. Payment already included: {payment_already_included}"
                )
                self.total_paid = completed_payments_sum
                self.remaining_amount = self.total_amount - self.total_paid
                # Recalculate total_paid_decimal after syncing
                total_paid_decimal = Decimal(str(self.total_paid))
            elif total_paid_decimal > expected_total_with_bonus:
                # total_paid is significantly more than payments + bonus - might be an error
                logger.warning(
                    f"Booking {self.id} total_paid is significantly more than expected! "
                    f"DB total_paid: {self.total_paid}, Expected (payments + bonus): {expected_total_with_bonus}. "
                    f"Syncing total_paid to match expected amount."
                )
                self.total_paid = expected_total_with_bonus
                self.remaining_amount = self.total_amount - self.total_paid
                # Recalculate total_paid_decimal after syncing
                total_paid_decimal = Decimal(str(self.total_paid))
            # If total_paid is between payments_sum and expected_total_with_bonus, preserve it (might be bonus being applied)
        
        # Check if this specific payment was already processed
        # If payment_id is provided, check if that payment was already counted
        # Account for bonuses when checking (total_paid might include bonus)
        # Use current total_paid value (after any syncing)
        total_paid_without_bonus = Decimal(str(self.total_paid)) - bonus_amount
        if payment_id:
            try:
                # Import Payment here to avoid circular import
                Payment = self.payments.model
                payment = self.payments.get(id=payment_id, status='completed')
                # Payment exists and is completed, check if it's already counted
                # If total_paid (minus bonus) matches payments_sum and adding this amount would exceed, it's duplicate
                if abs(total_paid_without_bonus - completed_payments_sum) <= Decimal('0.01'):
                    # total_paid (minus bonus) matches payments_sum, so check if this payment would create a duplicate
                    if abs(total_paid_without_bonus + Decimal(str(amount)) - completed_payments_sum) <= Decimal('0.01'):
                        # This payment amount is already included in the sum
                        logger.info(
                            f"Payment {payment_id} (amount: {amount}) already processed for booking {self.id}. Skipping."
                        )
                        return self
            except self.payments.model.DoesNotExist:
                # Payment doesn't exist or not completed, proceed with processing
                pass
        
        # Calculate expected total_paid after this payment
        expected_total = Decimal(str(self.total_paid)) + Decimal(str(amount))
        
        # Final check: if expected total matches or exceeds actual sum, payment might be duplicate
        # Account for bonuses when checking (total_paid might include bonus)
        # Check if total_paid (minus bonus) matches payments_sum
        if abs(total_paid_without_bonus - completed_payments_sum) <= Decimal('0.01'):
            # Calculate expected total without bonus for comparison
            expected_total_without_bonus = total_paid_without_bonus + Decimal(str(amount))
            if abs(expected_total_without_bonus - completed_payments_sum) <= Decimal('0.01'):
                # Payment already processed, skip
                return self
        
        # Process the payment
        self.total_paid += amount
        self.remaining_amount = self.total_amount - self.total_paid
        
        # Update status based on payment
        # Status becomes 'active' when booking_amount is paid (initial booking fee)
        # This confirms the booking. If booking_amount < ₹5000, we still activate
        # because the user has paid the required booking fee.
        if self.total_paid >= self.booking_amount:
            if self.status == 'pending':
                self.status = 'active'
                self.confirmed_at = timezone.now()

        if self.remaining_amount <= 0:
            self.status = 'completed'
            self.completed_at = timezone.now()
        
        self.save()
        
        # Complete the stock reservation if it exists (when first payment is confirmed)
        # This ensures reservation status is updated to 'completed' when payment is made
        try:
            reservation = self.stock_reservation
            if reservation and reservation.status == 'reserved':
                from core.inventory.utils import complete_reservation
                complete_reservation(reservation)
        except Exception:
            # No reservation exists or error accessing it, skip
            pass
        
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
            except Exception as e:
                # Log but don't fail - booking might not exist or other error
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to update booking for payment {self.id}: {e}")

