from rest_framework import serializers
from django.conf import settings
from .models import Booking, Payment


class BookingSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_mobile = serializers.CharField(source='user.mobile', read_only=True)
    
    class Meta:
        model = Booking
        fields = '__all__'
        read_only_fields = ('user', 'booking_number', 'status', 'created_at', 
                          'updated_at', 'confirmed_at', 'completed_at', 'total_paid', 
                          'remaining_amount')
    
    def validate_booking_amount(self, value):
        """Validate minimum booking amount"""
        if value < settings.PRE_BOOKING_MIN_AMOUNT:
            raise serializers.ValidationError(
                f"Minimum booking amount is ₹{settings.PRE_BOOKING_MIN_AMOUNT}"
            )
        return value


class PaymentSerializer(serializers.ModelSerializer):
    booking_number = serializers.CharField(source='booking.booking_number', read_only=True)
    
    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ('user', 'status', 'payment_date', 'completed_at')

