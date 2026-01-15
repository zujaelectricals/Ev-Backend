from rest_framework import serializers
from django.conf import settings
from core.users.models import User
from core.inventory.models import Vehicle
from .models import Booking, Payment


class ReferredUserSerializer(serializers.Serializer):
    """Nested serializer for referred user details"""
    id = serializers.IntegerField()
    fullname = serializers.SerializerMethodField()
    email = serializers.EmailField()
    
    def get_fullname(self, obj):
        """Get full name from first_name and last_name"""
        return obj.get_full_name() if obj else None
    
    def to_representation(self, instance):
        """Handle None values"""
        if instance is None:
            return None
        return super().to_representation(instance)


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
    user_mobile = serializers.SerializerMethodField()
    vehicle_details = VehicleDetailSerializer(source='vehicle_model', read_only=True)
    vehicle_model_code = serializers.CharField(write_only=True, required=False)
    model_code = serializers.CharField(source='vehicle_model.model_code', read_only=True)
    referral_code = serializers.CharField(write_only=True, required=False, allow_blank=True)
    manual_placement = serializers.BooleanField(write_only=True, required=False, default=False)
    reservation_status = serializers.CharField(source='stock_reservation.status', read_only=True)
    reservation_expires_at = serializers.DateTimeField(source='stock_reservation.expires_at', read_only=True)
    referred_by = ReferredUserSerializer(read_only=True, allow_null=True)
    
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
        """Validate total_amount matches vehicle_model price and model_code matches color/battery"""
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
        vehicle_color = data.get('vehicle_color')
        battery_variant = data.get('battery_variant')
        
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
            
            # Validate model_code matches vehicle_color and battery_variant
            if vehicle_model_code and vehicle_color and battery_variant:
                # Parse model_code: format is EV-{COLOR_CODE}-{BATTERY_CODE}-{RANDOM}
                parts = vehicle_model_code.split('-')
                if len(parts) >= 3:
                    model_color_code = parts[1] if len(parts) > 1 else None
                    model_battery_code = parts[2] if len(parts) > 2 else None
                    
                    # Convert provided battery_variant to code
                    provided_battery_code = Vehicle._get_battery_code(battery_variant)
                    
                    # Validate battery code matches (battery is less likely to change, so we keep this check)
                    if model_battery_code and provided_battery_code != model_battery_code:
                        raise serializers.ValidationError({
                            'battery_variant': f'Battery variant does not match model code. Model code indicates battery code: {model_battery_code}, but provided battery converts to: {provided_battery_code}'
                        })
                    
                    # Validate that color and battery_variant are in vehicle's available options
                    # Note: We don't validate color against model_code because model_code is read-only
                    # and doesn't update when vehicle_color changes. The important check is that the
                    # color is in the vehicle's available colors array (checked below).
                    vehicle_colors = vehicle_model.vehicle_color if isinstance(vehicle_model.vehicle_color, list) else []
                    vehicle_batteries = vehicle_model.battery_variant if isinstance(vehicle_model.battery_variant, list) else []
                    
                    # Normalize colors for comparison (case-insensitive)
                    vehicle_colors_lower = [c.lower().strip() for c in vehicle_colors]
                    if vehicle_color.lower().strip() not in vehicle_colors_lower:
                        raise serializers.ValidationError({
                            'vehicle_color': f'Vehicle color "{vehicle_color}" is not available for this vehicle. Available colors: {vehicle_colors}'
                        })
                    
                    # Normalize batteries for comparison (case-insensitive)
                    vehicle_batteries_normalized = [str(b).strip().lower() for b in vehicle_batteries]
                    if str(battery_variant).strip().lower() not in vehicle_batteries_normalized:
                        raise serializers.ValidationError({
                            'battery_variant': f'Battery variant "{battery_variant}" is not available for this vehicle. Available variants: {vehicle_batteries}'
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
    
    def get_user_mobile(self, obj):
        """Get user mobile number, ensuring it's properly accessed"""
        # Get mobile from the booking's user object (loaded via select_related)
        if hasattr(obj, 'user') and obj.user:
            mobile = getattr(obj.user, 'mobile', None)
            # If mobile is None, try to extract from username (for users who logged in via mobile OTP)
            if not mobile and hasattr(obj.user, 'username'):
                username = obj.user.username
                # Check if username looks like a mobile number (all digits, 10-15 chars)
                if username and username.isdigit() and 10 <= len(username) <= 15:
                    return username
            return mobile
        
        # Fallback to request user if available (for create operations)
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            mobile = getattr(request.user, 'mobile', None)
            # If mobile is None, try to extract from username
            if not mobile and hasattr(request.user, 'username'):
                username = request.user.username
                if username and username.isdigit() and 10 <= len(username) <= 15:
                    return username
            return mobile
        
        return None


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
        
        # Check for duplicate transaction_id (if provided)
        transaction_id = data.get('transaction_id')
        if transaction_id:
            # On create: check if transaction_id exists
            if not self.instance:
                existing_payment = Payment.objects.filter(transaction_id=transaction_id).first()
                if existing_payment:
                    raise serializers.ValidationError({
                        'transaction_id': f'Payment with transaction_id "{transaction_id}" already exists'
                    })
            # On update: check if transaction_id exists for a different payment
            else:
                existing_payment = Payment.objects.filter(transaction_id=transaction_id).exclude(pk=self.instance.pk).first()
                if existing_payment:
                    raise serializers.ValidationError({
                        'transaction_id': f'Payment with transaction_id "{transaction_id}" already exists'
                    })
        
        return data

