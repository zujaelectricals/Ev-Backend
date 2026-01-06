from django.db import models
from django.utils import timezone
from django.conf import settings
from core.users.models import User


class BinaryNode(models.Model):
    """
    Binary tree node representing user's position in left/right tree
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='binary_node')
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    
    # Tree position
    side = models.CharField(max_length=5, choices=[('left', 'Left'), ('right', 'Right')], null=True, blank=True)
    level = models.IntegerField(default=0)
    position = models.IntegerField(default=0)  # Position within level
    
    # Counts
    left_count = models.IntegerField(default=0)  # Total referrals on left
    right_count = models.IntegerField(default=0)  # Total referrals on right
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'binary_nodes'
        verbose_name = 'Binary Node'
        verbose_name_plural = 'Binary Nodes'
    
    def __str__(self):
        return f"Binary Node - {self.user.username} ({self.side})"
    
    def update_counts(self):
        """Update left and right counts"""
        self.left_count = BinaryNode.objects.filter(parent=self, side='left').count()
        self.right_count = BinaryNode.objects.filter(parent=self, side='right').count()
        self.save(update_fields=['left_count', 'right_count'])


class BinaryPair(models.Model):
    """
    Binary pair matching record
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('matched', 'Matched'),
        ('processed', 'Processed'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='binary_pairs')
    
    # Pair details
    left_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='left_pairs', null=True, blank=True)
    right_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='right_pairs', null=True, blank=True)
    
    pair_amount = models.DecimalField(max_digits=10, decimal_places=2)
    earning_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    matched_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    
    # Month tracking for max pairs limit
    pair_month = models.IntegerField()  # 1-12
    pair_year = models.IntegerField()
    
    class Meta:
        db_table = 'binary_pairs'
        verbose_name = 'Binary Pair'
        verbose_name_plural = 'Binary Pairs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'pair_month', 'pair_year']),
        ]
    
    def __str__(self):
        return f"Binary Pair - {self.user.username} ({self.pair_month}/{self.pair_year})"
    
    def save(self, *args, **kwargs):
        if not self.pair_month or not self.pair_year:
            now = timezone.now()
            self.pair_month = now.month
            self.pair_year = now.year
        super().save(*args, **kwargs)


class BinaryEarning(models.Model):
    """
    Binary earnings record
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='binary_earnings')
    binary_pair = models.ForeignKey(BinaryPair, on_delete=models.CASCADE, related_name='earnings')
    
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    pair_number = models.IntegerField()  # Which pair this is (1st, 2nd, etc.)
    
    # EMI deduction details
    emi_deducted = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=10, decimal_places=2)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'binary_earnings'
        verbose_name = 'Binary Earning'
        verbose_name_plural = 'Binary Earnings'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Binary Earning - {self.user.username} (₹{self.net_amount})"

