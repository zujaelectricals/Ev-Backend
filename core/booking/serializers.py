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
    profile_picture_url = serializers.SerializerMethodField()
    
    def get_fullname(self, obj):
        """Get full name from first_name and last_name"""
        return obj.get_full_name() if obj else None
    
    def get_profile_picture_url(self, obj):
        """Get absolute URL for profile picture"""
        if obj and obj.profile_picture:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_picture.url)
            return obj.profile_picture.url
        return None
    
    def to_representation(self, instance):
        """Handle None values"""
        if instance is None:
            return None
        return super().to_representation(instance)


class PaymentUserSerializer(serializers.Serializer):
    """Nested serializer for user details in payment responses"""
    id = serializers.IntegerField()
    fullname = serializers.SerializerMethodField()
    email = serializers.EmailField()
    mobile = serializers.CharField(allow_null=True)
    username = serializers.CharField(allow_null=True)
    profile_picture_url = serializers.SerializerMethodField()
    
    def get_fullname(self, obj):
        """Get full name from first_name and last_name"""
        return obj.get_full_name() if obj else None
    
    def get_profile_picture_url(self, obj):
        """Get absolute URL for profile picture"""
        if obj and obj.profile_picture:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile_picture.url)
            return obj.profile_picture.url
        return None
    
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
    referral_code = serializers.CharField(write_only=True, required=True)
    manual_placement = serializers.BooleanField(write_only=True, required=False, default=False)
    reservation_status = serializers.CharField(source='stock_reservation.status', read_only=True)
    reservation_expires_at = serializers.DateTimeField(source='stock_reservation.expires_at', read_only=True)
    referred_by = ReferredUserSerializer(read_only=True, allow_null=True)
     # Aggregated payment status for this booking (derived from related Payment records)
    payment_status = serializers.SerializerMethodField()
    # Calculate total_paid from actual completed payments to ensure accuracy
    total_paid = serializers.SerializerMethodField()
    remaining_amount = serializers.SerializerMethodField()
    
    class Meta:
        model = Booking
        fields = '__all__'
        read_only_fields = ('user', 'booking_number', 'status', 'created_at', 
                          'updated_at', 'confirmed_at', 'completed_at', 'delivered_at', 
                          'expires_at', 'ip_address', 'referred_by', 'vehicle_model')
    
    def validate_booking_amount(self, value):
        """Validate minimum booking amount"""
        if value < settings.PRE_BOOKING_MIN_AMOUNT:
            raise serializers.ValidationError(
                f"Minimum booking amount is ₹{settings.PRE_BOOKING_MIN_AMOUNT}"
            )
        return value
    
    def validate_referral_code(self, value):
        """Validate referral code (now mandatory)"""
        if not value or not value.strip():
            raise serializers.ValidationError("Referral code is required")
        
        value = value.strip().upper()
        
        # Check if this is the company referral code from settings
        # If it matches, allow it even if user doesn't exist yet (will be created in perform_create)
        from core.settings.models import PlatformSettings
        platform_settings = PlatformSettings.get_settings()
        company_referral_code = platform_settings.company_referral_code.strip().upper() if platform_settings.company_referral_code else None
        
        if company_referral_code and value == company_referral_code:
            # Company referral code is allowed even if user doesn't exist yet
            return value
        
        # For other referral codes, check if user exists
        try:
            referring_user = User.objects.get(referral_code=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("Invalid referral code")
        
        # Prevent self-referral (will be checked in perform_create with user context)
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

    def get_payment_status(self, obj):
        """
        Return a high-level payment status for the booking based on its Payment records.
        Priority:
        - If any payment is 'completed' -> 'completed'
        - Else if any payment is 'pending' -> 'pending'
        - Else if any payment is 'failed' -> 'failed'
        - Else if any payment is 'refunded' -> 'refunded'
        - If there are no payments -> 'no_payment'
        """
        payments_qs = getattr(obj, 'payments', None)
        if payments_qs is None:
            return 'no_payment'

        # Evaluate statuses once to avoid multiple queries
        statuses = list(payments_qs.values_list('status', flat=True))
        if not statuses:
            return 'no_payment'

        if 'completed' in statuses:
            return 'completed'
        if 'pending' in statuses:
            return 'pending'
        if 'failed' in statuses:
            return 'failed'
        if 'refunded' in statuses:
            return 'refunded'

        return 'no_payment'
    
    def get_total_paid(self, obj):
        """
        Calculate total_paid from actual completed payments to ensure accuracy.
        This prevents discrepancies between stored total_paid and actual payment records.
        """
        from decimal import Decimal
        payments_qs = getattr(obj, 'payments', None)
        if payments_qs is None:
            return str(obj.total_paid)  # Fallback to stored value
        
        # Sum all completed payments
        completed_payments_sum = sum(
            Decimal(str(p.amount))
            for p in payments_qs.filter(status='completed')
        )
        
        return str(completed_payments_sum)
    
    def get_remaining_amount(self, obj):
        """
        Calculate remaining_amount based on actual total_paid from completed payments.
        """
        from decimal import Decimal
        total_amount = Decimal(str(obj.total_amount))
        
        # Get actual total_paid from completed payments
        payments_qs = getattr(obj, 'payments', None)
        if payments_qs is None:
            total_paid = Decimal(str(obj.total_paid))  # Fallback to stored value
        else:
            total_paid = sum(
                Decimal(str(p.amount))
                for p in payments_qs.filter(status='completed')
            )
        
        remaining = total_amount - total_paid
        return str(max(remaining, Decimal('0')))  # Ensure non-negative


class RefundDetailSerializer(serializers.Serializer):
    """Nested serializer for refund details"""
    refund_id = serializers.CharField()
    refund_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    refund_status = serializers.CharField()
    refund_created_at = serializers.DateTimeField(allow_null=True)
    refund_notes = serializers.DictField(allow_null=True)
    refund_speed = serializers.CharField(allow_null=True)


class PaymentSerializer(serializers.ModelSerializer):
    booking_number = serializers.CharField(source='booking.booking_number', read_only=True)
    user_details = PaymentUserSerializer(source='user', read_only=True)
    refund_details = serializers.SerializerMethodField()
    
    class Meta:
        model = Payment
        fields = '__all__'
        read_only_fields = ('user', 'payment_date', 'completed_at')
    
    def get_refund_details(self, obj):
        """Get refund information from related Razorpay Payment if available"""
        # Only check for refunds if payment is online and has transaction_id
        if obj.payment_method != 'online' or not obj.transaction_id:
            return None
        
        try:
            from core.payments.models import Payment as RazorpayPayment
            from decimal import Decimal
            
            # Find Razorpay Payment by payment_id (stored in transaction_id for online payments)
            try:
                razorpay_payment = RazorpayPayment.objects.get(payment_id=obj.transaction_id)
            except RazorpayPayment.DoesNotExist:
                return None
            
            # Check if payment has refund data in raw_payload
            if not razorpay_payment.raw_payload:
                return None
            
            # Get original payment amount in rupees
            original_amount_paise = razorpay_payment.amount
            original_amount_rupees = Decimal(str(original_amount_paise / 100))
            
            refunds_data = []
            total_refunded = Decimal('0')
            
            # Check for API-initiated refunds (stored in 'refunds' array)
            refunds = razorpay_payment.raw_payload.get('refunds', [])
            if refunds and isinstance(refunds, list):
                for refund in refunds:
                    if isinstance(refund, dict):
                        refund_amount_paise = refund.get('amount', 0)
                        refund_amount_rupees = Decimal(str(refund_amount_paise / 100)) if refund_amount_paise else Decimal('0')
                        total_refunded += refund_amount_rupees
                        
                        # Calculate balance after this refund
                        balance_after_refund = original_amount_rupees - total_refunded
                        
                        refunds_data.append({
                            'refund_id': refund.get('id', 'N/A'),
                            'refund_amount': f"{refund_amount_rupees:.2f}",
                            'refund_status': refund.get('status', 'N/A'),
                            'refund_created_at': refund.get('created_at'),
                            'refund_notes': refund.get('notes', {}),
                            'refund_speed': refund.get('speed'),
                            'original_amount': f"{original_amount_rupees:.2f}",
                            'balance_amount': f"{balance_after_refund:.2f}",
                        })
            
            # Check for webhook-initiated refunds (stored in 'payload.refund')
            if not refunds_data:
                refund_data = razorpay_payment.raw_payload.get('payload', {}).get('refund', {})
                if refund_data:
                    refund_entity = refund_data.get('entity', refund_data)
                    refund_amount_paise = refund_entity.get('amount', 0)
                    refund_amount_rupees = Decimal(str(refund_amount_paise / 100)) if refund_amount_paise else Decimal('0')
                    total_refunded = refund_amount_rupees
                    
                    # Calculate balance after refund
                    balance_after_refund = original_amount_rupees - total_refunded
                    
                    refunds_data.append({
                        'refund_id': refund_entity.get('id', 'N/A'),
                        'refund_amount': f"{refund_amount_rupees:.2f}",
                        'refund_status': refund_entity.get('status', 'N/A'),
                        'refund_created_at': refund_entity.get('created_at'),
                        'refund_notes': refund_entity.get('notes', {}),
                        'refund_speed': refund_entity.get('speed'),
                        'original_amount': f"{original_amount_rupees:.2f}",
                        'balance_amount': f"{balance_after_refund:.2f}",
                    })
            
            # If multiple refunds, also add total summary
            if len(refunds_data) > 1:
                # Recalculate total refunded for all refunds
                total_refunded = sum(Decimal(r['refund_amount']) for r in refunds_data)
                final_balance = original_amount_rupees - total_refunded
                
                # Add summary to the response
                return {
                    'refunds': refunds_data,
                    'total_refunded': f"{total_refunded:.2f}",
                    'original_amount': f"{original_amount_rupees:.2f}",
                    'balance_amount': f"{final_balance:.2f}",
                }
            elif len(refunds_data) == 1:
                return refunds_data[0]
            else:
                return None
                
        except Exception as e:
            # Log error but don't break the response
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Error fetching refund details for payment {obj.id}: {e}")
            return None
    
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

