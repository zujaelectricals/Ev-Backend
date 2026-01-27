from django.db import models
from django.utils import timezone
from django.conf import settings
from core.users.models import User


class Wallet(models.Model):
    """
    Single main wallet for each user
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_earned = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_withdrawn = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'wallets'
        verbose_name = 'Wallet'
        verbose_name_plural = 'Wallets'
    
    def __str__(self):
        return f"Wallet - {self.user.username} (₹{self.balance})"


class WalletTransaction(models.Model):
    """
    Wallet transaction ledger
    """
    TRANSACTION_TYPE_CHOICES = [
        ('REFERRAL_BONUS', 'Referral Bonus'),
        ('BINARY_PAIR', 'Binary Pair'),
        ('BINARY_PAIR_COMMISSION', 'Binary Pair Commission'),
        ('DIRECT_USER_COMMISSION', 'Direct User Commission'),
        ('BINARY_INITIAL_BONUS', 'Binary Initial Bonus'),
        ('TDS_DEDUCTION', 'TDS Deduction'),
        ('EXTRA_DEDUCTION', 'Extra Deduction'),
        ('EMI_DEDUCTION', 'EMI Deduction'),
        ('RESERVE_DEDUCTION', 'Reserve Deduction'),
        ('PAYOUT', 'Payout'),
        ('DEPOSIT', 'Deposit'),
        ('REFUND', 'Refund'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wallet_transactions')
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    
    transaction_type = models.CharField(max_length=25, choices=TRANSACTION_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_before = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    
    description = models.TextField(blank=True)
    reference_id = models.IntegerField(null=True, blank=True)  # Can reference booking, binary pair, etc.
    reference_type = models.CharField(max_length=50, blank=True)  # 'booking', 'binary_pair', etc.
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'wallet_transactions'
        verbose_name = 'Wallet Transaction'
        verbose_name_plural = 'Wallet Transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'transaction_type', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.transaction_type} - ₹{self.amount} ({self.user.username})"


class ActivationPoints(models.Model):
    """
    Track activation_amount withheld from cancelled bookings for future point redemption
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('redeemed', 'Redeemed'),
        ('expired', 'Expired'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activation_points')
    booking = models.ForeignKey(
        'booking.Booking',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activation_points',
        help_text="Booking from which activation_amount was withheld"
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="The activation_amount withheld from cancelled booking"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        help_text="Status of activation points"
    )
    redeemable_after = models.DateTimeField(
        help_text="Date and time when points can be redeemed (1 year from cancellation)"
    )
    redeemed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Date and time when points were redeemed"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'activation_points'
        verbose_name = 'Activation Points'
        verbose_name_plural = 'Activation Points'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status', 'redeemable_after']),
        ]
    
    def __str__(self):
        return f"Activation Points - ₹{self.amount} for {self.user.username} (Status: {self.status})"
    
    def is_redeemable(self):
        """Check if points are redeemable (status is pending and redeemable_after date has passed)"""
        from django.utils import timezone
        return (
            self.status == 'pending' and
            timezone.now() >= self.redeemable_after
        )

