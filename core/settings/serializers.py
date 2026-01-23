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
            'direct_user_commission_amount',
            'binary_commission_activation_count',
            'binary_pair_commission_amount',
            'binary_tds_threshold_pairs',
            'binary_commission_tds_percentage',
            'binary_extra_deduction_percentage',
            'binary_daily_pair_limit',
            'binary_tree_default_placement_side',
            'distributor_application_auto_approve',
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
    
    def validate_direct_user_commission_amount(self, value):
        """Validate that commission amount is non-negative"""
        if value < 0:
            raise serializers.ValidationError("direct_user_commission_amount must be non-negative")
        return value
    
    def validate_binary_commission_activation_count(self, value):
        """Validate that activation count is positive"""
        if value < 1:
            raise serializers.ValidationError("binary_commission_activation_count must be at least 1")
        return value
    
    def validate_binary_pair_commission_amount(self, value):
        """Validate that commission amount is non-negative"""
        if value < 0:
            raise serializers.ValidationError("binary_pair_commission_amount must be non-negative")
        return value
    
    def validate_binary_tds_threshold_pairs(self, value):
        """Validate that TDS threshold is non-negative"""
        if value < 0:
            raise serializers.ValidationError("binary_tds_threshold_pairs must be non-negative")
        return value
    
    def validate_binary_commission_tds_percentage(self, value):
        """Validate that TDS percentage is between 0 and 100"""
        if value < 0 or value > 100:
            raise serializers.ValidationError("binary_commission_tds_percentage must be between 0 and 100")
        return value
    
    def validate_binary_extra_deduction_percentage(self, value):
        """Validate that extra deduction percentage is between 0 and 100"""
        if value < 0 or value > 100:
            raise serializers.ValidationError("binary_extra_deduction_percentage must be between 0 and 100")
        return value
    
    def validate_binary_daily_pair_limit(self, value):
        """Validate that daily pair limit is positive"""
        if value < 1:
            raise serializers.ValidationError("binary_daily_pair_limit must be at least 1")
        return value

