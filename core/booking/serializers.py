from rest_framework import serializers
from django.conf import settings
from .models import Booking, Payment


class VehicleDetailSerializer(serializers.Serializer):
    """Nested serializer for Vehicle details in read operations"""
    id = serializers.IntegerField()
    name = serializers.CharField()
    model_code = serializers.CharField()
    vehicle_color = serializers.ListField(child=serializers.CharField())
    battery_variant = serializers.CharField()
    price = serializers.DecimalField(max_digits=10, decimal_places=2)


class BookingSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_mobile = serializers.CharField(source='user.mobile', read_only=True)
    vehicle_details = VehicleDetailSerializer(source='vehicle_model', read_only=True)
    
    class Meta:
        model = Booking
        fields = '__all__'
        read_only_fields = ('user', 'booking_number', 'status', 'created_at', 
                          'updated_at', 'confirmed_at', 'completed_at', 'total_paid', 
                          'remaining_amount', 'expires_at', 'ip_address')
    
    def validate_booking_amount(self, value):
        """Validate minimum booking amount"""
        if value < settings.PRE_BOOKING_MIN_AMOUNT:
            raise serializers.ValidationError(
                f"Minimum booking amount is ₹{settings.PRE_BOOKING_MIN_AMOUNT}"
            )
        return value
    
    def validate(self, data):
        """Validate total_amount matches vehicle_model price"""
        vehicle_model = data.get('vehicle_model')
        total_amount = data.get('total_amount')
        
        # For create: both vehicle_model and total_amount must be provided
        # For update: if either is provided, validate the relationship
        if self.instance is None:
            # Creating new booking - both are required
            if vehicle_model is None:
                raise serializers.ValidationError({'vehicle_model': 'Vehicle model is required'})
            if total_amount is None:
                raise serializers.ValidationError({'total_amount': 'Total amount is required'})
            if vehicle_model.price != total_amount:
                raise serializers.ValidationError({
                    'total_amount': f'Total amount must match vehicle price (₹{vehicle_model.price})'
                })
        else:
            # Updating existing booking
            vehicle_model = vehicle_model if vehicle_model is not None else self.instance.vehicle_model
            total_amount = total_amount if total_amount is not None else self.instance.total_amount
            
            if vehicle_model.price != total_amount:
                raise serializers.ValidationError({
                    'total_amount': f'Total amount must match vehicle price (₹{vehicle_model.price})'
                })
        
        return data


class PaymentSerializer(serializers.ModelSerializer):
    booking_number = serializers.CharField(source='booking.booking_number', read_only=True)
    
    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ('user', 'status', 'payment_date', 'completed_at')

