from rest_framework import serializers
from django.conf import settings
from core.users.models import User
from core.inventory.models import Vehicle
from .models import Booking, Payment


class VehicleDetailSerializer(serializers.Serializer):
    """Nested serializer for Vehicle details in read operations"""
    id = serializers.IntegerField()
    name = serializers.CharField()
    model_code = serializers.CharField()
    vehicle_color = serializers.ListField(child=serializers.CharField())
    battery_variant = serializers.ListField(child=serializers.CharField())  # Now an array
    price = serializers.DecimalField(max_digits=10, decimal_places=2)


class BookingSerializer(serializers.ModelSerializer):
    user_email = serializers.CharField(source='user.email', read_only=True)
    user_mobile = serializers.CharField(source='user.mobile', read_only=True)
    vehicle_details = VehicleDetailSerializer(source='vehicle_model', read_only=True)
    vehicle_model_code = serializers.CharField(write_only=True, required=False)
    model_code = serializers.CharField(source='vehicle_model.model_code', read_only=True)
    referral_code = serializers.CharField(write_only=True, required=False, allow_blank=True)
    
    class Meta:
        model = Booking
        fields = '__all__'
        read_only_fields = ('user', 'booking_number', 'status', 'created_at', 
                          'updated_at', 'confirmed_at', 'completed_at', 'total_paid', 
                          'remaining_amount', 'expires_at', 'ip_address', 'referred_by', 'vehicle_model')
    
    def validate_booking_amount(self, value):
        """Validate minimum booking amount"""
        if value < settings.PRE_BOOKING_MIN_AMOUNT:
            raise serializers.ValidationError(
                f"Minimum booking amount is ₹{settings.PRE_BOOKING_MIN_AMOUNT}"
            )
        return value
    
    def validate_referral_code(self, value):
        """Validate referral code if provided"""
        if value:
            value = value.strip().upper()
            # Check if referral code exists
            try:
                referring_user = User.objects.get(referral_code=value)
            except User.DoesNotExist:
                raise serializers.ValidationError("Invalid referral code")
            
            # Prevent self-referral (will be checked in perform_create with user context)
            return value
        return value
    
    def validate_vehicle_model_code(self, value):
        """Validate vehicle_model_code and find the vehicle"""
        if not value:
            raise serializers.ValidationError("Vehicle model code is required")
        
        value = value.strip()
        try:
            vehicle = Vehicle.objects.get(model_code=value)
            # Store vehicle in instance variable for use in validate method
            self._vehicle = vehicle
            return value
        except Vehicle.DoesNotExist:
            raise serializers.ValidationError(f"Vehicle with model_code '{value}' not found")
    
    def validate(self, data):
        """Validate total_amount matches vehicle_model price"""
        # Get vehicle from vehicle_model_code if provided
        vehicle_model = None
        vehicle_model_code = data.get('vehicle_model_code')
        
        if vehicle_model_code:
            # Get vehicle from instance variable (set in validate_vehicle_model_code)
            vehicle_model = getattr(self, '_vehicle', None)
            if vehicle_model:
                data['vehicle_model'] = vehicle_model
        elif self.instance:
            vehicle_model = self.instance.vehicle_model
        else:
            # Try to get from existing data if updating
            vehicle_model = data.get('vehicle_model')
        
        total_amount = data.get('total_amount')
        
        # For create: vehicle_model_code and total_amount must be provided
        if self.instance is None:
            if vehicle_model is None:
                raise serializers.ValidationError({
                    'vehicle_model_code': 'Vehicle model code is required'
                })
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
            
            if vehicle_model and total_amount and vehicle_model.price != total_amount:
                raise serializers.ValidationError({
                    'total_amount': f'Total amount must match vehicle price (₹{vehicle_model.price})'
                })
        
        return data


class PaymentSerializer(serializers.ModelSerializer):
    booking_number = serializers.CharField(source='booking.booking_number', read_only=True)
    
    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ('user', 'payment_date', 'completed_at')
    
    def validate_status(self, value):
        """Validate payment status transitions"""
        if self.instance:
            current_status = self.instance.status
            # Allow transitions: pending -> completed, completed -> refunded, any -> failed
            valid_transitions = {
                'pending': ['completed', 'failed'],
                'completed': ['refunded', 'failed'],
                'failed': ['pending', 'completed'],
                'refunded': []  # Cannot change from refunded
            }
            if value != current_status and value not in valid_transitions.get(current_status, []):
                raise serializers.ValidationError(
                    f"Cannot change status from {current_status} to {value}"
                )
        return value
    
    def validate(self, data):
        """Additional validation for payment"""
        # If status is being set to completed, ensure amount is valid
        status = data.get('status', self.instance.status if self.instance else 'pending')
        booking = data.get('booking', self.instance.booking if self.instance else None)
        amount = data.get('amount', self.instance.amount if self.instance else None)
        
        if status == 'completed' and booking and amount:
            if amount > booking.remaining_amount:
                raise serializers.ValidationError({
                    'amount': 'Amount exceeds remaining booking amount'
                })
        
        return data

