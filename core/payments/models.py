from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.conf import settings
from django.utils import timezone


class Payment(models.Model):
    """
    Razorpay Payment model for tracking payment gateway transactions
    """
    STATUS_CHOICES = [
        ('CREATED', 'Created'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('REFUNDED', 'Refunded'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='razorpay_payments'
    )
    
    # Razorpay identifiers
    order_id = models.CharField(max_length=255, unique=True, db_index=True)
    payment_id = models.CharField(max_length=255, null=True, blank=True, unique=True, db_index=True)
    
    # Amount in paise (Razorpay uses paise, not rupees)
    # This is the gross amount (what user pays, including gateway charges)
    amount = models.IntegerField()
    
    # Net amount in paise (amount after deducting gateway charges)
    # This is what gets credited to the booking/payout
    net_amount = models.IntegerField(null=True, blank=True, help_text="Net amount in paise after gateway charges")
    
    # Gateway charges in paise (Razorpay fee + GST)
    gateway_charges = models.IntegerField(null=True, blank=True, help_text="Gateway charges in paise (2.36% of gross amount)")
    
    # Payment status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='CREATED', db_index=True)
    
    # Store raw webhook/API responses for debugging and audit
    raw_payload = models.JSONField(null=True, blank=True)
    
    # Generic foreign key for flexible entity linking (booking, payout, etc.)
    content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'razorpay_payments'
        verbose_name = 'Razorpay Payment'
        verbose_name_plural = 'Razorpay Payments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order_id']),
            models.Index(fields=['payment_id']),
            models.Index(fields=['status']),
            models.Index(fields=['user', 'status']),
        ]
    
    def __str__(self):
        return f"Payment {self.order_id} - {self.get_status_display()} - ₹{self.amount / 100:.2f}"
    
    @property
    def amount_in_rupees(self):
        """Convert gross amount from paise to rupees"""
        return self.amount / 100
    
    @property
    def net_amount_in_rupees(self):
        """Convert net amount from paise to rupees"""
        if self.net_amount is not None:
            return self.net_amount / 100
        return self.amount_in_rupees  # Fallback to gross if net not set
    
    @property
    def gateway_charges_in_rupees(self):
        """Convert gateway charges from paise to rupees"""
        if self.gateway_charges is not None:
            return self.gateway_charges / 100
        return 0


class WebhookEvent(models.Model):
    """
    Track processed webhook events for idempotency
    """
    event_id = models.CharField(max_length=255, unique=True, db_index=True, help_text="Razorpay event ID")
    event_type = models.CharField(max_length=100, db_index=True, help_text="Event type (e.g., payment.captured)")
    payload = models.JSONField(help_text="Full webhook payload")
    processed = models.BooleanField(default=False, db_index=True, help_text="Whether event was successfully processed")
    processed_at = models.DateTimeField(null=True, blank=True, help_text="When event was processed")
    error_message = models.TextField(null=True, blank=True, help_text="Error message if processing failed")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'webhook_events'
        verbose_name = 'Webhook Event'
        verbose_name_plural = 'Webhook Events'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_id']),
            models.Index(fields=['event_type', 'processed']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Webhook {self.event_id} - {self.event_type} - {'Processed' if self.processed else 'Pending'}"

