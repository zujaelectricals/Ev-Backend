from django.db import models
from django.utils import timezone
from django.conf import settings
from core.users.models import User


class OTP(models.Model):
    """
    OTP model for email/mobile verification
    """
    OTP_TYPE_CHOICES = [
        ('email', 'Email'),
        ('mobile', 'Mobile'),
    ]
    
    identifier = models.CharField(max_length=255)  # email or mobile
    otp_type = models.CharField(max_length=10, choices=OTP_TYPE_CHOICES)
    otp_code = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'otps'
        verbose_name = 'OTP'
        verbose_name_plural = 'OTPs'
        indexes = [
            models.Index(fields=['identifier', 'otp_type', 'is_used']),
        ]
    
    def __str__(self):
        return f"{self.otp_type} OTP for {self.identifier}"
    
    def is_valid(self):
        """Check if OTP is still valid"""
        return not self.is_used and timezone.now() < self.expires_at
    
    def mark_as_used(self):
        """Mark OTP as used"""
        self.is_used = True
        self.save(update_fields=['is_used'])

