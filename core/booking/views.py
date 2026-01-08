from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.conf import settings
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
        
        booking = serializer.save(user=self.request.user, ip_address=ip_address)
    
    @action(detail=True, methods=['post'])
    def make_payment(self, request, pk=None):
        """Make a payment for booking"""
        booking = self.get_object()
        
        if booking.user != request.user:
            return Response(
                {'error': 'Permission denied'}, 
                status=status.HTTP_403_FORBIDDEN
            )
        
        amount = float(request.data.get('amount', 0))
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
        
        # Create payment record
        payment = Payment.objects.create(
            booking=booking,
            user=request.user,
            amount=amount,
            payment_method=payment_method,
            status='completed'
        )
        
        # Update booking
        booking.make_payment(amount)
        
        serializer = PaymentSerializer(payment)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PaymentViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for Payment viewing
    """
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == 'admin':
            return Payment.objects.all()
        return Payment.objects.filter(user=user)

