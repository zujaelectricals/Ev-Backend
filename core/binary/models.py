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
    
    # Binary Commission Tracking
    binary_commission_activated = models.BooleanField(default=False)  # Track if binary commission is activated
    direct_children_count = models.IntegerField(default=0)  # Count of direct children (left + right)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'binary_nodes'
        verbose_name = 'Binary Node'
        verbose_name_plural = 'Binary Nodes'
        constraints = [
            models.UniqueConstraint(
                fields=['parent', 'side'],
                condition=models.Q(parent__isnull=False),
                name='unique_parent_side'
            )
        ]
    
    def __str__(self):
        return f"Binary Node - {self.user.username} ({self.side})"
    
    def update_counts(self):
        """Update left and right counts - counts ALL descendants recursively, not just direct children"""
        self.left_count = self.get_all_descendants_count('left')
        self.right_count = self.get_all_descendants_count('right')
        self.save(update_fields=['left_count', 'right_count'])
    
    def get_all_descendants_count(self, side):
        """
        Recursively count ALL descendants on specified side (entire subtree)
        
        Args:
            side: 'left' or 'right'
        
        Returns:
            int: Total count of all descendants on the specified side
        """
        count = 0
        # Get direct children on this side
        direct_children = BinaryNode.objects.filter(parent=self, side=side)
        count += direct_children.count()
        
        # Recursively count descendants of each direct child
        for child in direct_children:
            count += child.get_all_descendants_count('left')
            count += child.get_all_descendants_count('right')
        
        return count


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
    
    # Pair tracking after activation
    pair_number_after_activation = models.IntegerField(
        null=True,
        blank=True,
        help_text="Pair number after binary commission activation (null if before activation)"
    )
    
    # Daily limit tracking
    pair_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date when pair was created (for daily limit tracking)"
    )
    
    # Carry-forward tracking
    is_carry_forward_pair = models.BooleanField(
        default=False,
        help_text="Whether this pair used carried-forward members from previous day"
    )
    carry_forward = models.ForeignKey(
        'BinaryCarryForward',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pairs',
        help_text="Reference to carry-forward record if this pair used carried-forward members"
    )
    
    # Extra deduction for 6th+ pairs
    extra_deduction_applied = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Amount of extra deduction applied for 6th+ pairs (additional 20%)"
    )
    
    # Commission blocking for non-Active Buyer distributors
    commission_blocked = models.BooleanField(
        default=False,
        help_text="Whether commission was blocked due to Active Buyer requirement (6th+ pair for non-Active Buyer distributors)"
    )
    blocked_reason = models.TextField(
        blank=True,
        help_text="Reason for blocking commission (e.g., 'Not Active Buyer, 6th+ pair')"
    )
    
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


class BinaryCarryForward(models.Model):
    """
    Track carried-forward members from long leg after daily pair limit
    SHORT leg is ignored, LONG leg members are carried forward
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='binary_carry_forwards')
    
    # Carry-forward details
    carried_forward_date = models.DateField(help_text="Date when members were carried forward")
    side = models.CharField(max_length=5, choices=[('left', 'Left'), ('right', 'Right')], help_text="Side with long leg (more remaining members)")
    
    # Member tracking
    initial_member_count = models.IntegerField(help_text="Total members carried forward from long leg")
    matched_count = models.IntegerField(default=0, help_text="How many carried-forward members have been matched")
    
    # Status
    is_active = models.BooleanField(default=True, help_text="Whether this carry-forward is still active")
    matched_at = models.DateTimeField(null=True, blank=True, help_text="When last match occurred")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'binary_carry_forwards'
        verbose_name = 'Binary Carry Forward'
        verbose_name_plural = 'Binary Carry Forwards'
        ordering = ['-carried_forward_date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'is_active', 'carried_forward_date']),
        ]
    
    def __str__(self):
        return f"Carry Forward - {self.user.username} ({self.side}) - {self.initial_member_count} members"
    
    @property
    def remaining_count(self):
        """Calculate remaining unmatched members"""
        return self.initial_member_count - self.matched_count


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

