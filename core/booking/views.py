from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from django.conf import settings
from django.utils import timezone
from django.db.models import Q
from django.db import transaction
from decimal import Decimal
import logging
from core.users.models import User
from core.settings.models import PlatformSettings
from core.inventory.utils import create_reservation
from .models import Booking, Payment
from .serializers import BookingSerializer, PaymentSerializer

logger = logging.getLogger(__name__)


def ensure_company_referral_user(company_referral_code):
    """
    Ensure a superadmin user exists with the company referral code.
    Returns the user with the company referral code.
    """
    # First, try to find an existing user with this referral code
    try:
        company_user = User.objects.get(referral_code=company_referral_code)
        # If found, ensure it's a superadmin
        if not company_user.is_superuser:
            company_user.is_superuser = True
            company_user.is_staff = True
            company_user.role = 'admin'
            company_user.save(update_fields=['is_superuser', 'is_staff', 'role'])
        return company_user
    except User.DoesNotExist:
        # Create a new superadmin user with the company referral code
        # Use a default username/email for the company user
        username = f"company_{company_referral_code.lower()}"
        email = f"company@{company_referral_code.lower()}.local"
        
        # Check if username or email already exists, adjust if needed
        base_username = username
        base_email = email
        counter = 1
        while User.objects.filter(username=username).exists() or User.objects.filter(email=email).exists():
            username = f"{base_username}{counter}"
            email = f"company{counter}@{company_referral_code.lower()}.local"
            counter += 1
        
        company_user = User.objects.create(
            username=username,
            email=email,
            first_name='Company',
            last_name='Admin',
            role='admin',
            is_staff=True,
            is_superuser=True,
            referral_code=company_referral_code
        )
        return company_user


class BookingPagination(PageNumberPagination):
    """Custom pagination for booking list with page_size support"""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'


class BookingViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Booking management
    """
    queryset = Booking.objects.select_related('user', 'vehicle_model', 'referred_by').all()
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = BookingPagination
    
    def get_queryset(self):
        user = self.request.user
        queryset = Booking.objects.select_related('user', 'vehicle_model', 'referred_by')
        if user.is_superuser or user.role == 'admin':
            queryset = queryset.all()
        else:
            queryset = queryset.filter(user=user)
        
        # Filter by status parameter
        status_param = self.request.query_params.get('status', None)
        if status_param:
            # Strip whitespace for consistent filtering
            status_param = status_param.strip()
            queryset = queryset.filter(status=status_param)
        
        # Search query (searches across multiple fields)
        search = self.request.query_params.get('search', None)
        if search:
            search_queries = (
                Q(booking_number__icontains=search) |
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(user__username__icontains=search) |
                Q(user__email__icontains=search) |
                Q(vehicle_model__name__icontains=search) |
                Q(vehicle_model__model_code__icontains=search) |
                Q(delivery_city__icontains=search) |
                Q(delivery_state__icontains=search) |
                Q(delivery_pin__icontains=search)
            )
            queryset = queryset.filter(search_queries)
        
        return queryset
    
    def perform_create(self, serializer):
        # Capture IP address
        ip_address = self.request.META.get('REMOTE_ADDR')
        if not ip_address:
            # Try to get from forwarded headers (for reverse proxy setups)
            ip_address = self.request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
        
        # Handle referral code
        referral_code = serializer.validated_data.pop('referral_code', None)
        manual_placement = serializer.validated_data.pop('manual_placement', False)
        referring_user = None
        
        # Check if this is the first booking in the system
        is_first_booking = not Booking.objects.exists()
        
        # Get company referral code from settings
        platform_settings = PlatformSettings.get_settings()
        company_referral_code = platform_settings.company_referral_code.strip().upper() if platform_settings.company_referral_code else None
        
        # Normalize the provided referral code
        if referral_code:
            referral_code = referral_code.strip().upper()
        
        # Check if provided referral code matches company referral code
        is_company_referral_code = company_referral_code and referral_code == company_referral_code
        
        if is_first_booking:
            # For the first booking, always use company referral code from settings
            # (ignore what user provided)
            if company_referral_code:
                # Ensure company user exists with this referral code
                referring_user = ensure_company_referral_user(company_referral_code)
                referral_code = company_referral_code
            else:
                raise serializers.ValidationError({'referral_code': 'Company referral code not configured in settings'})
        elif is_company_referral_code:
            # User is using company referral code for subsequent booking
            # Ensure company user exists with this referral code
            referring_user = ensure_company_referral_user(company_referral_code)
        else:
            # For other referral codes, validate that user exists
            if referral_code:
                try:
                    referring_user = User.objects.get(referral_code=referral_code)
                    # Prevent self-referral
                    if referring_user == self.request.user:
                        raise serializers.ValidationError({'referral_code': 'You cannot use your own referral code'})
                except User.DoesNotExist:
                    raise serializers.ValidationError({'referral_code': 'Invalid referral code'})
            else:
                # This shouldn't happen since referral_code is now mandatory, but handle it just in case
                raise serializers.ValidationError({'referral_code': 'Referral code is required'})
        
        # Remove vehicle_model_code from validated_data as it's already converted to vehicle_model
        serializer.validated_data.pop('vehicle_model_code', None)
        
        # Save booking with referred_by if referral code is valid
        # Store whether referrer was a distributor at booking creation time
        referrer_was_distributor = referring_user.is_distributor if referring_user else False
        
        booking = serializer.save(
            user=self.request.user, 
            ip_address=ip_address,
            referred_by=referring_user,
            referrer_was_distributor=referrer_was_distributor
        )
        
        # Set user.referred_by if not already set (first-time referral)
        if referring_user and not self.request.user.referred_by:
            self.request.user.referred_by = referring_user
            self.request.user.save(update_fields=['referred_by'])
        
        # Note: Binary tree placement is NOT automatic during booking creation
        # Users must be placed manually via /api/binary/nodes/place_user/ 
        # or automatically via /api/binary/nodes/auto_place_pending/
        
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
        
        amount = request.data.get('amount', None)
        payment_method = request.data.get('payment_method', 'cash')
        transaction_id = request.data.get('transaction_id', '')
        notes = request.data.get('notes', '')
        
        # Try to use an existing pending payment for this booking before creating a new one
        pending_payment = Payment.objects.filter(booking=booking, status='pending').order_by('-payment_date').first()

        # If no amount provided, default to pending payment's amount
        if amount is None and pending_payment:
            amount = pending_payment.amount
        else:
            amount = Decimal(str(amount or 0))
        
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
        
        # Check if transaction_id already exists (if provided)
        if transaction_id:
            if pending_payment:
                existing_payment = Payment.objects.filter(
                    transaction_id=transaction_id
                ).exclude(pk=pending_payment.pk).first()
            else:
                existing_payment = Payment.objects.filter(
                    transaction_id=transaction_id
                ).first()

            if existing_payment:
                return Response(
                    {
                        'error': f'Payment with transaction_id "{transaction_id}" already exists',
                        'existing_payment_id': existing_payment.id,
                        'existing_booking_id': existing_payment.booking.id
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Approve existing pending payment if available, else create a new completed payment
        if pending_payment:
            payment = pending_payment
            payment.amount = amount  # allow admin to correct/confirm amount
            payment.payment_method = payment_method
            payment.transaction_id = transaction_id or None
            payment.status = 'completed'
            payment.notes = notes
            payment.completed_at = timezone.now()
            payment.save(update_fields=['amount', 'payment_method', 'transaction_id', 'status', 'notes', 'completed_at'])
        else:
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
        # Pass payment_id so Guard 2 in make_payment() detects that Payment.save()
        # above already processed this payment and skips the duplicate add.
        booking.make_payment(amount, payment_id=payment.id)
        
        # Handle special case: if reservation was released (expired), re-reserve it
        # make_payment() already handles 'reserved' -> 'completed' transition
        from core.inventory.utils import complete_reservation
        try:
            reservation = booking.stock_reservation
            if reservation and reservation.status == 'released':
                # Reservation was released (likely expired), but payment is now complete
                # Re-reserve the stock and mark as completed
                vehicle_stock = reservation.vehicle_stock
                if vehicle_stock.available_quantity >= reservation.quantity:
                    # Re-reserve the stock
                    vehicle_stock.reserve(quantity=reservation.quantity)
                    # Mark reservation as completed
                    reservation.status = 'completed'
                    reservation.save(update_fields=['status', 'updated_at'])
                else:
                    # Stock not available, but mark as completed anyway (booking is confirmed)
                    reservation.status = 'completed'
                    reservation.save(update_fields=['status', 'updated_at'])
        except Exception as e:
            # No reservation exists or error accessing it, skip
            import logging
            logger = logging.getLogger(__name__)
            logger.debug(f"No reservation to complete for booking {booking.id}: {e}")
        
        # Note: booking.make_payment already triggers the payment_completed Celery task,
        # so we don't need to trigger it again here to avoid duplicate processing.
        
        serializer = PaymentSerializer(payment)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['patch', 'post'], url_path='update_status', url_name='update-status')
    def update_status(self, request, pk=None):
        """Update booking status (Admin/Staff only)"""
        if not (request.user.is_superuser or request.user.role in ['admin', 'staff']):
            return Response(
                {'error': 'Permission denied. Only admin or staff can update booking status.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        booking = self.get_object()
        new_status = request.data.get('status')
        
        if not new_status:
            return Response(
                {'error': 'status field is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if new_status not in dict(Booking.STATUS_CHOICES):
            return Response(
                {'error': f'Invalid status. Valid choices: {[choice[0] for choice in Booking.STATUS_CHOICES]}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        old_status = booking.status
        
        # Validate status transitions
        valid_transitions = {
            'pending': ['active', 'cancelled', 'expired'],
            'active': ['completed', 'cancelled'],
            'completed': ['delivered', 'cancelled'],
            'delivered': [],  # Cannot change from delivered
            'cancelled': [],  # Cannot change from cancelled
            'expired': [],  # Cannot change from expired
        }
        
        if new_status != old_status and new_status not in valid_transitions.get(old_status, []):
            return Response(
                {'error': f'Cannot change status from {old_status} to {new_status}. Valid transitions from {old_status}: {valid_transitions.get(old_status, [])}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update status
        booking.status = new_status
        
        # Set delivered_at timestamp when status changes to 'delivered'
        if new_status == 'delivered' and old_status != 'delivered':
            booking.delivered_at = timezone.now()
        
        booking.save(update_fields=['status', 'delivered_at'])
        
        serializer = BookingSerializer(booking)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel a booking and release reservation
        
        Refund Logic:
        - Only (total_paid - activation_amount) is refunded
        - activation_amount is withheld and stored in ActivationPoints for future redemption (after 1 year)
        - If total_paid <= activation_amount, no refund is processed, but activation_amount is still stored
        """
        from decimal import Decimal
        from datetime import timedelta
        from core.settings.models import PlatformSettings
        from core.wallet.models import ActivationPoints
        from core.wallet.utils import add_wallet_balance
        
        booking = self.get_object()
        
        # Check permission - user can cancel their own booking, admin/staff can cancel any
        if booking.user != request.user and not (request.user.is_superuser or request.user.role in ['admin', 'staff']):
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if booking can be cancelled
        if booking.status in ['cancelled', 'delivered']:
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
        
        # Get activation_amount from settings
        platform_settings = PlatformSettings.get_settings()
        activation_amount = platform_settings.activation_amount
        
        # Calculate refund amount
        total_paid = Decimal(str(booking.total_paid))
        activation_amount_decimal = Decimal(str(activation_amount))
        refund_amount = total_paid - activation_amount_decimal
        
        # Update booking status
        booking.status = 'cancelled'
        booking.save(update_fields=['status'])
        
        # Store activation_amount in ActivationPoints for future redemption
        if total_paid > 0 and activation_amount_decimal > 0:
            redeemable_after = timezone.now() + timedelta(days=365)
            ActivationPoints.objects.create(
                user=booking.user,
                booking=booking,
                amount=min(activation_amount_decimal, total_paid),  # Don't store more than what was paid
                status='pending',
                redeemable_after=redeemable_after
            )
        
        # Process refund if refund_amount > 0
        if refund_amount > 0:
            import logging
            logger = logging.getLogger(__name__)
            
            # Try Razorpay refund first (if payments were made via Razorpay)
            razorpay_refund_success = False
            razorpay_refund_total = Decimal('0')
            
            try:
                from django.contrib.contenttypes.models import ContentType
                from core.payments.models import Payment as RazorpayPayment
                from core.payments.utils.razorpay_client import get_razorpay_client
                from core.booking.models import Payment as BookingPayment
                
                # Find all Razorpay Payment records linked to this booking
                booking_content_type = ContentType.objects.get_for_model(booking.__class__)
                razorpay_payments = RazorpayPayment.objects.filter(
                    content_type=booking_content_type,
                    object_id=booking.id,
                    status='SUCCESS'
                ).exclude(
                    status='REFUNDED'
                ).order_by('-created_at')  # Latest first
                
                if razorpay_payments.exists():
                    client = get_razorpay_client()
                    remaining_refund = refund_amount
                    
                    # Refund from latest payment first
                    for razorpay_payment in razorpay_payments:
                        if remaining_refund <= 0:
                            break
                        
                        # Calculate how much to refund from this payment
                        payment_amount_rupees = Decimal(str(razorpay_payment.amount / 100))
                        refund_from_this_payment = min(remaining_refund, payment_amount_rupees)
                        refund_amount_paise = int(float(refund_from_this_payment) * 100)
                        
                        # Skip if amount is 0 or negative
                        if refund_amount_paise <= 0:
                            continue
                        
                        try:
                            # Create Razorpay refund
                            refund_data = {
                                'payment_id': razorpay_payment.payment_id,
                                'amount': refund_amount_paise,
                                'notes': {
                                    'refund_reason': 'Booking cancellation',
                                    'original_order_id': razorpay_payment.order_id,
                                    'booking_number': booking.booking_number,
                                }
                            }
                            
                            razorpay_refund = client.payment.refund(razorpay_payment.payment_id, refund_data)
                            refund_id = razorpay_refund['id']
                            
                            # Update Razorpay Payment status
                            with transaction.atomic():
                                razorpay_payment = RazorpayPayment.objects.select_for_update().get(
                                    payment_id=razorpay_payment.payment_id
                                )
                                
                                # Double-check status
                                if razorpay_payment.status != 'REFUNDED':
                                    # If full refund, mark as REFUNDED; otherwise keep as SUCCESS
                                    if refund_from_this_payment >= payment_amount_rupees:
                                        razorpay_payment.status = 'REFUNDED'
                                    
                                    # Store refund details in raw_payload
                                    if razorpay_payment.raw_payload:
                                        if 'refunds' not in razorpay_payment.raw_payload:
                                            razorpay_payment.raw_payload['refunds'] = []
                                        razorpay_payment.raw_payload['refunds'].append(razorpay_refund)
                                    else:
                                        razorpay_payment.raw_payload = {'refunds': [razorpay_refund]}
                                    
                                    razorpay_payment.save()
                            
                            # Update corresponding booking Payment status if exists
                            try:
                                booking_payment = BookingPayment.objects.filter(
                                    booking=booking,
                                    transaction_id=razorpay_payment.payment_id
                                ).first()
                                
                                if booking_payment and booking_payment.status != 'refunded':
                                    # If full refund, mark as refunded; otherwise keep as completed
                                    if refund_from_this_payment >= payment_amount_rupees:
                                        booking_payment.status = 'refunded'
                                        booking_payment.save(update_fields=['status'])
                            except Exception as e:
                                logger.warning(f"Could not update booking payment status: {e}")
                            
                            razorpay_refund_total += refund_from_this_payment
                            remaining_refund -= refund_from_this_payment
                            
                            logger.info(
                                f"Created Razorpay refund {refund_id} for payment {razorpay_payment.payment_id}, "
                                f"amount={refund_amount_paise} paise (₹{refund_from_this_payment}) for booking {booking.booking_number}"
                            )
                            
                        except Exception as refund_error:
                            logger.error(
                                f"Error creating Razorpay refund for payment {razorpay_payment.payment_id}: {refund_error}",
                                exc_info=True
                            )
                            # Continue to next payment or fallback to wallet
                    
                    # Check if we successfully refunded the full amount via Razorpay
                    if razorpay_refund_total >= refund_amount:
                        razorpay_refund_success = True
                        logger.info(
                            f"Successfully refunded ₹{razorpay_refund_total} via Razorpay for booking {booking.booking_number} "
                            f"(requested: ₹{refund_amount})"
                        )
                    elif razorpay_refund_total > 0:
                        # Partial Razorpay refund - refund remaining to wallet
                        remaining_wallet_refund = refund_amount - razorpay_refund_total
                        logger.info(
                            f"Partially refunded ₹{razorpay_refund_total} via Razorpay, "
                            f"refunding remaining ₹{remaining_wallet_refund} to wallet for booking {booking.booking_number}"
                        )
                        try:
                            add_wallet_balance(
                                user=booking.user,
                                amount=float(remaining_wallet_refund),
                                transaction_type='REFUND',
                                description=f"Partial refund for cancelled booking {booking.booking_number} (₹{razorpay_refund_total} refunded via Razorpay, ₹{remaining_wallet_refund} refunded to wallet)",
                                reference_id=booking.id,
                                reference_type='booking'
                            )
                        except Exception as e:
                            logger.error(
                                f"Error processing partial wallet refund for booking {booking.id}: {e}",
                                exc_info=True
                            )
                    
            except Exception as e:
                logger.warning(
                    f"Error processing Razorpay refunds for booking {booking.id}: {e}. "
                    f"Falling back to wallet refund.",
                    exc_info=True
                )
            
            # Fallback to wallet refund if Razorpay refund didn't cover the full amount
            if not razorpay_refund_success:
                try:
                    # Calculate remaining refund amount (if partial Razorpay refund was made)
                    remaining_refund = refund_amount - razorpay_refund_total
                    if remaining_refund > 0:
                        add_wallet_balance(
                            user=booking.user,
                            amount=float(remaining_refund),
                            transaction_type='REFUND',
                            description=f"Refund for cancelled booking {booking.booking_number} (₹{total_paid} paid - ₹{min(activation_amount_decimal, total_paid)} activation_amount = ₹{refund_amount} refunded)",
                            reference_id=booking.id,
                            reference_type='booking'
                        )
                        logger.info(
                            f"Refunded ₹{remaining_refund} to wallet for booking {booking.booking_number} "
                            f"(Razorpay refund: ₹{razorpay_refund_total})"
                        )
                except Exception as e:
                    logger.error(
                        f"Error processing wallet refund for booking {booking.id}: {e}",
                        exc_info=True
                    )
                    # Continue even if refund fails - booking is already cancelled
        
        serializer = BookingSerializer(booking)
        response_data = serializer.data
        response_data['refund_amount'] = float(refund_amount) if refund_amount > 0 else 0
        response_data['activation_amount_withheld'] = float(min(activation_amount_decimal, total_paid)) if total_paid > 0 and activation_amount_decimal > 0 else 0
        
        return Response(response_data, status=status.HTTP_200_OK)


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
        # Use select_related for foreign keys and prefetch_related for reverse lookups
        queryset = Payment.objects.select_related('user', 'booking')
        if user.is_superuser or user.role in ['admin', 'staff']:
            return queryset.all()
        return queryset.filter(user=user)
    
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
            # Pass payment_id so Guard 2 in make_payment() can detect that
            # Payment.save() already processed this payment (via status_changing_to_completed)
            # and skip the duplicate add.
            booking.make_payment(payment.amount, payment_id=payment.id)
            # Note: make_payment() now handles reservation completion automatically
            
            # Trigger Celery task for payment processing (direct user commission, etc.)
            from core.booking.tasks import payment_completed
            payment_completed.delay(booking.id, float(payment.amount))
    
    def perform_update(self, serializer):
        """Update payment - only admin/staff can update payments"""
        user = self.request.user
        if not (user.is_superuser or user.role in ['admin', 'staff']):
            raise PermissionDenied('Only admin or staff can update payments')
        
        old_status = self.get_object().status
        # serializer.save() will trigger Payment.save() which automatically calls make_payment() 
        # if status changed to 'completed', so we don't need to call it again here
        payment = serializer.save()
        
        # If status changed to 'completed', set completed_at if not already set
        # (Payment.save() already called make_payment() and triggered the Celery task)
        if old_status != 'completed' and payment.status == 'completed':
            if not payment.completed_at:
                payment.completed_at = timezone.now()
                payment.save(update_fields=['completed_at'])
        # If status changed to 'failed', optionally release reservation
        elif old_status != 'failed' and payment.status == 'failed':
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
        
        # Check if transaction_id already exists (if being updated)
        if transaction_id:
            existing_payment = Payment.objects.filter(transaction_id=transaction_id).exclude(pk=payment.pk).first()
            if existing_payment:
                return Response(
                    {
                        'error': f'Payment with transaction_id "{transaction_id}" already exists',
                        'existing_payment_id': existing_payment.id,
                        'existing_booking_id': existing_payment.booking.id
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            payment.transaction_id = transaction_id
        if notes is not None:
            payment.notes = notes
        payment.status = new_status
        
        # Set completed_at if status is completed
        if new_status == 'completed':
            payment.completed_at = timezone.now()
        
        # Save payment - Payment.save() will automatically call make_payment() if status changed to 'completed'
        # This prevents double-processing since Payment.save() already handles the booking update
        payment.save()
        
        # After save, check if we need to send booking confirmation email
        # (make_payment() is already called by Payment.save(), and it triggers the Celery task)
        if old_status != 'completed' and new_status == 'completed':
            booking = payment.booking
            booking_status_before = booking.status
            
            # Refresh booking to get updated status after make_payment() was called by Payment.save()
            booking.refresh_from_db()
            
            # Send booking confirmation email if booking just became active and receipt exists
            # Note: make_payment() already triggered the Celery task for payment processing
            if booking_status_before != 'active' and booking.status == 'active' and booking.payment_receipt:
                try:
                    from core.booking.tasks import send_booking_confirmation_email_task
                    send_booking_confirmation_email_task.delay(booking.id)
                    logger.info(
                        f"Triggered booking confirmation email task for booking {booking.id} "
                        f"via PaymentViewSet.update_status"
                    )
                except Exception as email_error:
                    logger.error(
                        f"Failed to trigger booking confirmation email for booking {booking.id}: {email_error}",
                        exc_info=True
                    )
                    # Don't fail the payment update if email trigger fails
        
        serializer = PaymentSerializer(payment)
        return Response(serializer.data, status=status.HTTP_200_OK)

