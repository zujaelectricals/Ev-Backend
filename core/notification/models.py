from django.db import models
from django.utils import timezone
from core.users.models import User


class Notification(models.Model):
    """
    Notification model
    """
    TYPE_CHOICES = [
        ('booking', 'Booking'),
        ('payment', 'Payment'),
        ('wallet', 'Wallet'),
        ('binary', 'Binary'),
        ('payout', 'Payout'),
        ('kyc', 'KYC'),
        ('system', 'System'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    
    # Reference to related object
    reference_id = models.IntegerField(null=True, blank=True)
    reference_type = models.CharField(max_length=50, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'notifications'
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.user.username}"
    
    def mark_as_read(self):
        """Mark notification as read"""
        self.is_read = True
        self.read_at = timezone.now()
        self.save(update_fields=['is_read', 'read_at'])

