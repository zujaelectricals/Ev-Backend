from django.db import models
from django.utils import timezone
from django.conf import settings
from core.users.models import User
from core.wallet.models import Wallet


class Payout(models.Model):
    """
    Payout request model
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payouts')
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='payouts')
    
    # Amount details
    requested_amount = models.DecimalField(max_digits=12, decimal_places=2)
    tds_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Bank details
    bank_name = models.CharField(max_length=200)
    account_number = models.CharField(max_length=50)
    ifsc_code = models.CharField(max_length=11)
    account_holder_name = models.CharField(max_length=200)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # EMI auto-fill
    emi_auto_filled = models.BooleanField(default=False)
    emi_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Additional info
    transaction_id = models.CharField(max_length=200, unique=True, null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    reason = models.TextField(blank=True, help_text="User's reason for payout request")
    
    class Meta:
        db_table = 'payouts'
        verbose_name = 'Payout'
        verbose_name_plural = 'Payouts'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Payout - {self.user.username} (₹{self.net_amount})"
    
    def calculate_tds(self):
        """Calculate TDS based on business rules"""
        from decimal import Decimal
        from core.settings.models import PlatformSettings
        
        # Get payout TDS percentage from Platform Settings
        platform_settings = PlatformSettings.get_settings()
        payout_tds_percentage = Decimal(str(platform_settings.payout_tds_percentage))
        
        # If payout TDS percentage is 0, no TDS is applied
        if payout_tds_percentage == 0:
            self.tds_amount = Decimal('0')
            self.net_amount = Decimal(str(self.requested_amount))
            return self.tds_amount, self.net_amount
        
        # TDS calculation: percentage from settings with ceiling of ₹10,000
        tds_percentage = payout_tds_percentage / Decimal('100')
        tds_calculated = Decimal(str(self.requested_amount)) * tds_percentage
        
        # Apply ceiling
        tds_ceiling = Decimal(str(settings.TDS_CEILING))
        self.tds_amount = min(tds_calculated, tds_ceiling)
        self.net_amount = Decimal(str(self.requested_amount)) - self.tds_amount
        
        return self.tds_amount, self.net_amount


class PayoutTransaction(models.Model):
    """
    Payout transaction record
    """
    payout = models.ForeignKey(Payout, on_delete=models.CASCADE, related_name='transactions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payout_transactions')
    
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=50)  # 'payout', 'tds', 'emi_auto_fill'
    description = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'payout_transactions'
        verbose_name = 'Payout Transaction'
        verbose_name_plural = 'Payout Transactions'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Payout Transaction - {self.user.username} (₹{self.amount})"


class PayoutWebhookLog(models.Model):
    """
    Webhook event log for idempotency and audit trail
    """
    STATUS_CHOICES = [
        ('received', 'Received'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
    ]
    
    event_id = models.CharField(max_length=255, unique=True, db_index=True, help_text="Razorpay event ID")
    event_type = models.CharField(max_length=100, db_index=True, help_text="Event type: payout.processed, payout.failed, fund_account.verified")
    payload = models.JSONField(help_text="Full webhook payload")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='received', db_index=True)
    error_message = models.TextField(blank=True, help_text="Error details if processing failed")
    
    processed_at = models.DateTimeField(null=True, blank=True, help_text="When event was processed")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'payout_webhook_logs'
        verbose_name = 'Payout Webhook Log'
        verbose_name_plural = 'Payout Webhook Logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_id']),
            models.Index(fields=['event_type', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]
    
    def __str__(self):
        return f"Webhook {self.event_type} - {self.event_id} ({self.status})"

