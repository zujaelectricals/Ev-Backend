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
        
        # TDS calculation: 5% with ceiling of ₹10,000
        tds_percentage = Decimal(str(settings.TDS_PERCENTAGE)) / Decimal('100')
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

