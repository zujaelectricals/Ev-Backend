from django.db import models
from django.utils import timezone
from core.users.models import User


class PlatformSettings(models.Model):
    """
    Singleton model for platform-wide settings.
    Only one instance should exist in the database.
    """
    booking_reservation_timeout_minutes = models.IntegerField(
        null=True,
        blank=True,
        help_text="Booking reservation timeout in minutes. Set to null for never expires. Default: 1440 (24 hours)"
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_settings',
        help_text="User who last updated these settings"
    )
    
    class Meta:
        db_table = 'platform_settings'
        verbose_name = 'Platform Settings'
        verbose_name_plural = 'Platform Settings'
    
    def __str__(self):
        timeout = f"{self.booking_reservation_timeout_minutes} minutes" if self.booking_reservation_timeout_minutes else "Never expires"
        return f"Platform Settings (Timeout: {timeout})"
    
    @classmethod
    def get_settings(cls):
        """
        Get or create the singleton settings instance.
        Returns the single PlatformSettings instance.
        """
        settings, created = cls.objects.get_or_create(
            pk=1,
            defaults={
                'booking_reservation_timeout_minutes': 1440,  # 24 hours in minutes
            }
        )
        return settings
    
    def save(self, *args, **kwargs):
        """
        Override save to ensure only one instance exists.
        Always save with pk=1 to maintain singleton pattern.
        """
        self.pk = 1
        super().save(*args, **kwargs)
    
    def delete(self, *args, **kwargs):
        """
        Prevent deletion of the settings instance.
        """
        raise Exception("Cannot delete PlatformSettings. It is a singleton.")

