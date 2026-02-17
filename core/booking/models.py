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
    
    def make_payment(self, amount):
        """Record payment and update booking status"""
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
        
        # Update user's Active Buyer status
        self.user.update_active_buyer_status()
        
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
        # Set completed_at when status changes to 'completed'
        if self.pk:
            try:
                old_instance = Payment.objects.get(pk=self.pk)
                if old_instance.status != 'completed' and self.status == 'completed':
                    if not self.completed_at:
                        self.completed_at = timezone.now()
            except Payment.DoesNotExist:
                pass
        elif self.status == 'completed' and not self.completed_at:
            self.completed_at = timezone.now()
        
        super().save(*args, **kwargs)

