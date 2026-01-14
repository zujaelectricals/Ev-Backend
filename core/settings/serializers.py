from rest_framework import serializers
from .models import PlatformSettings


class PlatformSettingsSerializer(serializers.ModelSerializer):
    updated_by_username = serializers.CharField(source='updated_by.username', read_only=True)
    updated_by_email = serializers.CharField(source='updated_by.email', read_only=True, allow_null=True)
    
    class Meta:
        model = PlatformSettings
        fields = [
            'id',
            'booking_reservation_timeout_minutes',
            'updated_at',
            'updated_by',
            'updated_by_username',
            'updated_by_email',
        ]
        read_only_fields = ['id', 'updated_at', 'updated_by']
    
    def validate_booking_reservation_timeout_minutes(self, value):
        """
        Validate that timeout is either None (never expires) or a positive integer.
        """
        if value is not None and value < 1:
            raise serializers.ValidationError(
                "booking_reservation_timeout_minutes must be at least 1 minute or null (never expires)"
            )
        return value

