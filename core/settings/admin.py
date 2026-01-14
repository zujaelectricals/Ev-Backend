from django.contrib import admin
from .models import PlatformSettings


@admin.register(PlatformSettings)
class PlatformSettingsAdmin(admin.ModelAdmin):
    """
    Admin interface for Platform Settings.
    """
    list_display = ('id', 'booking_reservation_timeout_minutes', 'updated_at', 'updated_by')
    readonly_fields = ('id', 'updated_at', 'updated_by')
    
    fieldsets = (
        ('Booking Settings', {
            'fields': ('booking_reservation_timeout_minutes',)
        }),
        ('Metadata', {
            'fields': ('id', 'updated_at', 'updated_by'),
        }),
    )
    
    def has_add_permission(self, request):
        """
        Prevent adding new instances - only one should exist.
        """
        return False
    
    def has_delete_permission(self, request, obj=None):
        """
        Prevent deletion - settings instance cannot be deleted.
        """
        return False
    
    def save_model(self, request, obj, form, change):
        """
        Set updated_by to current user when saving.
        """
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)

