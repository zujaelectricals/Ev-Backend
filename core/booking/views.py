from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
from core.users.models import User
from core.inventory.utils import create_reservation
from .models import Booking, Payment
from .serializers import BookingSerializer, PaymentSerializer


class BookingViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Booking management
    """
    queryset = Booking.objects.all()
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return Booking.objects.all()
        return Booking.objects.filter(user=user)
    
    def perform_create(self, serializer):
        # Capture IP address
        ip_address = self.request.META.get('REMOTE_ADDR')
        if not ip_address:
            # Try to get from forwarded headers (for reverse proxy setups)
            ip_address = self.request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
        
        # Handle referral code
        referral_code = serializer.validated_data.pop('referral_code', None)
        referring_user = None
        
        if referral_code:
            referral_code = referral_code.strip().upper()
            try:
                referring_user = User.objects.get(referral_code=referral_code)
                # Prevent self-referral
                if referring_user == self.request.user:
                    raise serializers.ValidationError({'referral_code': 'You cannot use your own referral code'})
            except User.DoesNotExist:
                raise serializers.ValidationError({'referral_code': 'Invalid referral code'})
        
        # Remove vehicle_model_code from validated_data as it's already converted to vehicle_model
        serializer.validated_data.pop('vehicle_model_code', None)
        
        # Save booking with referred_by if referral code is valid
        booking = serializer.save(
            user=self.request.user, 
            ip_address=ip_address,
            referred_by=referring_user
        )
        
        # Set user.referred_by if not already set (first-time referral)
        if referring_user and not self.request.user.referred_by:
            self.request.user.referred_by = referring_user
            self.request.user.save(update_fields=['referred_by'])
        
        # Create stock reservation for the booking
        try:
            create_reservation(booking=booking, vehicle=booking.vehicle_model, quantity=1)
        except ValueError as e:
            # If insufficient stock, raise validation error
            raise serializers.ValidationError({'vehicle_model': str(e)})
    
    @action(detail=True, methods=['post'])
    def make_payment(self, request, pk=None):
        """Make a payment for booking"""
        booking = self.get_object()
        
        if booking.user != request.user:
            return Response(
                {'error': 'Permission denied'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        amount = Decimal(str(request.data.get('amount', 0)))
        payment_method = request.data.get('payment_method', 'online')
        
        if amount <= 0:
            return Response(
                {'error': 'Invalid amount'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if amount > booking.remaining_amount:
            return Response(
                {'error': 'Amount exceeds remaining amount'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create payment record with status='pending' (not automatically completed)
        payment = Payment.objects.create(
            booking=booking,
            user=request.user,
            amount=amount,
            payment_method=payment_method,
            status='pending'  # Changed from 'completed' - requires admin approval or gateway confirmation
        )
        
        # Don't update booking automatically - only when payment status becomes 'completed'
        
        serializer = PaymentSerializer(payment)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['post'])
    def accept_payment(self, request, pk=None):
        """Accept payment on behalf of user (Admin/Staff only)"""
        # Check permission
        if not (request.user.is_superuser or request.user.role in ['admin', 'staff']):
            return Response(
                {'error': 'Permission denied. Only admin or staff can accept payments.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        booking = self.get_object()
        
        # Validate booking status
        if booking.status in ['cancelled', 'expired']:
            return Response(
                {'error': f'Cannot accept payment for {booking.status} booking'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        amount = Decimal(str(request.data.get('amount', 0)))
        payment_method = request.data.get('payment_method', 'cash')
        transaction_id = request.data.get('transaction_id', '')
        notes = request.data.get('notes', '')
        
        if amount <= 0:
            return Response(
                {'error': 'Invalid amount'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if amount > booking.remaining_amount:
            return Response(
                {'error': 'Amount exceeds remaining amount'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create payment record with status='completed'
        payment = Payment.objects.create(
            booking=booking,
            user=booking.user,
            amount=amount,
            payment_method=payment_method,
            transaction_id=transaction_id or None,
            status='completed',
            notes=notes,
            completed_at=timezone.now()
        )
        
        # Update booking (only when admin/staff accepts payment)
        booking.make_payment(amount)
        
        # Complete the stock reservation if it exists
        from core.inventory.utils import complete_reservation
        try:
            reservation = booking.stock_reservation
            if reservation and reservation.status == 'reserved':
                complete_reservation(reservation)
        except:
            pass  # No reservation exists, skip
        
        # Trigger Celery task for payment processing (referral bonus, etc.)
        from core.booking.tasks import payment_completed
        payment_completed.delay(booking.id, float(amount))
        
        serializer = PaymentSerializer(payment)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PaymentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Payment management
    - Regular users: Read-only access to their own payments
    - Admin/Staff: Full CRUD access to all payments
    """
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role in ['admin', 'staff']:
            return Payment.objects.all()
        return Payment.objects.filter(user=user)
    
    def get_serializer_class(self):
        """Return serializer class based on action"""
        return PaymentSerializer
    
    def perform_create(self, serializer):
        """Create payment - only admin/staff can create payments"""
        user = self.request.user
        if not (user.is_superuser or user.role in ['admin', 'staff']):
            raise PermissionDenied('Only admin or staff can create payments')
        
        booking = serializer.validated_data.get('booking')
        if not booking:
            raise serializers.ValidationError({'booking': 'Booking is required'})
        
        # Set user from booking if not provided
        if 'user' not in serializer.validated_data:
            serializer.save(user=booking.user)
        else:
            serializer.save()
        
        # If status is 'completed', trigger payment processing
        payment = serializer.instance
        if payment.status == 'completed':
            payment.completed_at = timezone.now()
            payment.save(update_fields=['completed_at'])
            booking = payment.booking
            booking.make_payment(payment.amount)
            
            # Complete the stock reservation if it exists
            from core.inventory.utils import complete_reservation
            try:
                reservation = booking.stock_reservation
                if reservation and reservation.status == 'reserved':
                    complete_reservation(reservation)
            except:
                pass  # No reservation exists, skip
            
            # Trigger Celery task for payment processing (referral bonus, etc.)
            from core.booking.tasks import payment_completed
            payment_completed.delay(booking.id, float(payment.amount))
    
    def perform_update(self, serializer):
        """Update payment - only admin/staff can update payments"""
        user = self.request.user
        if not (user.is_superuser or user.role in ['admin', 'staff']):
            raise PermissionDenied('Only admin or staff can update payments')
        
        old_status = self.get_object().status
        payment = serializer.save()
        
        # If status changed to 'completed', trigger payment processing
        if old_status != 'completed' and payment.status == 'completed':
            payment.completed_at = timezone.now()
            payment.save(update_fields=['completed_at'])
            booking = payment.booking
            booking.make_payment(payment.amount)
            
            # Complete the stock reservation if it exists
            from core.inventory.utils import complete_reservation
            try:
                reservation = booking.stock_reservation
                if reservation and reservation.status == 'reserved':
                    complete_reservation(reservation)
            except:
                pass  # No reservation exists, skip
            
            # Trigger Celery task for payment processing (referral bonus, etc.)
            from core.booking.tasks import payment_completed
            payment_completed.delay(booking.id, float(payment.amount))
        # If status changed to 'failed', optionally release reservation
        elif new_status == 'failed':
            booking = payment.booking
            from core.inventory.utils import release_reservation
            try:
                reservation = booking.stock_reservation
                if reservation and reservation.status == 'reserved':
                    # Optionally release reservation on payment failure
                    # Uncomment the line below if you want automatic release on failure
                    # release_reservation(reservation)
                    pass
            except:
                pass  # No reservation exists, skip
        # If status changed from 'completed' to something else, handle refund/reversal
        elif old_status == 'completed' and payment.status != 'completed':
            # Note: Refund logic can be added here if needed
            pass
    
    @action(detail=True, methods=['patch'])
    def update_status(self, request, pk=None):
        """Update payment status (Admin/Staff only)"""
        if not (request.user.is_superuser or request.user.role in ['admin', 'staff']):
            return Response(
                {'error': 'Permission denied. Only admin or staff can update payment status.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        payment = self.get_object()
        new_status = request.data.get('status')
        transaction_id = request.data.get('transaction_id')
        notes = request.data.get('notes')
        
        if not new_status:
            return Response(
                {'error': 'status field is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if new_status not in dict(Payment.STATUS_CHOICES):
            return Response(
                {'error': f'Invalid status. Valid choices: {[choice[0] for choice in Payment.STATUS_CHOICES]}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        old_status = payment.status
        
        # Update payment
        if transaction_id:
            payment.transaction_id = transaction_id
        if notes is not None:
            payment.notes = notes
        payment.status = new_status
        
        # Set completed_at if status is completed
        if new_status == 'completed':
            payment.completed_at = timezone.now()
        
        payment.save()
        
        # Trigger booking payment update if status changed to completed
        if old_status != 'completed' and new_status == 'completed':
            booking = payment.booking
            booking.make_payment(payment.amount)
            
            # Complete the stock reservation if it exists
            from core.inventory.utils import complete_reservation
            try:
                reservation = booking.stock_reservation
                if reservation and reservation.status == 'reserved':
                    complete_reservation(reservation)
            except:
                pass  # No reservation exists, skip
            
            # Trigger Celery task for payment processing (referral bonus, etc.)
            from core.booking.tasks import payment_completed
            payment_completed.delay(booking.id, float(payment.amount))
        
        serializer = PaymentSerializer(payment)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    def perform_destroy(self, instance):
        """Handle booking deletion - release reservation if exists"""
        from core.inventory.utils import release_reservation
        try:
            reservation = instance.stock_reservation
            if reservation and reservation.status == 'reserved':
                release_reservation(reservation)
        except:
            pass  # No reservation exists, skip
        
        instance.delete()
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel a booking and release reservation"""
        booking = self.get_object()
        
        # Check permission - user can cancel their own booking, admin/staff can cancel any
        if booking.user != request.user and not (request.user.is_superuser or request.user.role in ['admin', 'staff']):
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if booking can be cancelled
        if booking.status in ['cancelled', 'completed']:
            return Response(
                {'error': f'Cannot cancel booking with status: {booking.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Release reservation if exists
        from core.inventory.utils import release_reservation
        try:
            reservation = booking.stock_reservation
            if reservation and reservation.status == 'reserved':
                release_reservation(reservation)
        except:
            pass  # No reservation exists, skip
        
        # Update booking status
        booking.status = 'cancelled'
        booking.save(update_fields=['status'])
        
        serializer = BookingSerializer(booking)
        return Response(serializer.data, status=status.HTTP_200_OK)

