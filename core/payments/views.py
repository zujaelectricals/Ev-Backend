from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings
import json
import logging
import hashlib
import time

from .models import Payment
from .serializers import (
    CreateOrderRequestSerializer,
    CreateOrderResponseSerializer,
    VerifyPaymentRequestSerializer,
    VerifyPaymentResponseSerializer,
    CreatePayoutRequestSerializer,
    CreatePayoutResponseSerializer,
    CreateRefundRequestSerializer,
    CreateRefundResponseSerializer,
)
from .utils.razorpay_client import get_razorpay_client
from .utils.signature import verify_payment_signature, verify_webhook_signature

logger = logging.getLogger(__name__)


def _process_booking_payment(razorpay_payment):
    """
    Process a successful Razorpay payment for a booking.
    Creates a booking Payment record and updates the booking status.
    
    This function is idempotent and thread-safe using database-level locking
    to prevent race conditions when both verify_payment and webhook are called.
    
    Args:
        razorpay_payment: core.payments.models.Payment instance with status='SUCCESS'
    
    Returns:
        tuple: (booking_payment, booking) or (None, None) if not a booking payment
    """
    from core.booking.models import Booking, Payment as BookingPayment
    from django.db import IntegrityError
    from decimal import Decimal
    
    # Check if this payment is for a booking
    if razorpay_payment.content_type is None or razorpay_payment.object_id is None:
        return None, None
    
    try:
        booking = razorpay_payment.content_object
        if not isinstance(booking, Booking):
            return None, None
    except Exception:
        return None, None
    
    # Use transaction with select_for_update to prevent race conditions
    # This ensures only one process can update the booking at a time
    with transaction.atomic():
        # Lock the booking row to prevent concurrent updates
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        
        # Convert amount from paise to rupees (Decimal)
        amount_rupees = Decimal(str(razorpay_payment.amount / 100))
        
        # Use payment_id as transaction_id if available, otherwise use order_id
        transaction_id = razorpay_payment.payment_id or razorpay_payment.order_id
        
        # Check if booking payment already exists for this Razorpay payment
        # Check by payment_id if available, otherwise by order_id in notes
        existing_payment = None
        if razorpay_payment.payment_id:
            existing_payment = BookingPayment.objects.filter(
                booking=booking,
                transaction_id=razorpay_payment.payment_id
            ).first()
        
        if not existing_payment:
            # Also check by order_id in notes (for cases where payment_id wasn't set yet)
            existing_payment = BookingPayment.objects.filter(
                booking=booking,
                notes__icontains=f'Order: {razorpay_payment.order_id}'
            ).first()
        
        if existing_payment:
            # Payment already processed - return existing payment without updating booking
            logger.info(
                f"Booking payment already exists for Razorpay payment {razorpay_payment.order_id} "
                f"(BookingPayment ID: {existing_payment.id})"
            )
            return existing_payment, booking
        
        # Try to create booking Payment record
        # Use get_or_create with IntegrityError handling as additional safety
        # Note: If transaction_id is None, get_or_create won't work correctly with unique constraint
        # So we use create with IntegrityError handling instead
        booking_payment = None
        created = False
        
        try:
            if transaction_id:
                # Use get_or_create when transaction_id is available
                booking_payment, created = BookingPayment.objects.get_or_create(
                    transaction_id=transaction_id,
                    defaults={
                        'booking': booking,
                        'user': booking.user,
                        'amount': amount_rupees,
                        'payment_method': 'online',
                        'status': 'completed',
                        'notes': f'Razorpay payment - Order: {razorpay_payment.order_id}',
                    }
                )
                
                # If payment already exists (race condition caught by get_or_create)
                if not created:
                    logger.warning(
                        f"Booking payment with transaction_id {transaction_id} already exists "
                        f"(BookingPayment ID: {booking_payment.id}). This indicates a race condition was caught."
                    )
                    return booking_payment, booking
            else:
                # If transaction_id is None, create directly (multiple NULLs allowed in unique constraint)
                booking_payment = BookingPayment.objects.create(
                    booking=booking,
                    user=booking.user,
                    amount=amount_rupees,
                    payment_method='online',
                    transaction_id=None,
                    status='completed',
                    notes=f'Razorpay payment - Order: {razorpay_payment.order_id}',
                )
                created = True
                
        except IntegrityError as e:
            # Handle case where transaction_id is None and unique constraint fails
            # or if there's a race condition between check and create
            if 'transaction_id' in str(e) or 'unique' in str(e).lower():
                logger.warning(
                    f"IntegrityError creating BookingPayment for order {razorpay_payment.order_id}: {e}. "
                    f"Attempting to retrieve existing payment."
                )
                # Try to find the existing payment that was just created by another process
                if razorpay_payment.payment_id:
                    existing_payment = BookingPayment.objects.filter(
                        booking=booking,
                        transaction_id=razorpay_payment.payment_id
                    ).first()
                if not existing_payment:
                    existing_payment = BookingPayment.objects.filter(
                        booking=booking,
                        notes__icontains=f'Order: {razorpay_payment.order_id}'
                    ).first()
                
                if existing_payment:
                    logger.info(
                        f"Found existing BookingPayment {existing_payment.id} after IntegrityError. "
                        f"Returning without updating booking."
                    )
                    return existing_payment, booking
                else:
                    # Re-raise if we can't find the existing payment
                    logger.error(
                        f"IntegrityError but could not find existing BookingPayment for "
                        f"order {razorpay_payment.order_id}. Re-raising exception."
                    )
                    raise
            else:
                # Re-raise if it's a different IntegrityError
                raise
        
        # At this point, booking_payment was successfully created (created=True)
        # Now update booking payment status and totals (inside transaction with lock)
        # Note: make_payment() triggers a Celery task which may fail if Redis/RabbitMQ is not available
        # We handle this gracefully by catching the exception
        if not booking_payment:
            logger.error(
                f"booking_payment is None after creation attempt for order {razorpay_payment.order_id}. "
                f"This should not happen."
            )
            raise ValueError("booking_payment was not created")
        
        try:
            booking.make_payment(amount_rupees)
        except Exception as e:
            # If Celery task fails, we still want to update the booking
            # So we manually update the booking totals and status
            logger.warning(
                f"Celery task failed for booking {booking.id}, updating booking manually: {e}"
            )
            booking.total_paid += amount_rupees
            booking.remaining_amount = booking.total_amount - booking.total_paid
            
            # Update status based on payment
            # Status becomes 'active' when booking_amount is paid (initial booking fee)
            if booking.total_paid >= booking.booking_amount:
                if booking.status == 'pending':
                    booking.status = 'active'
                    if not booking.confirmed_at:
                        from django.utils import timezone
                        booking.confirmed_at = timezone.now()
            
            if booking.remaining_amount <= 0:
                booking.status = 'completed'
                if not booking.completed_at:
                    from django.utils import timezone
                    booking.completed_at = timezone.now()
            
            booking.save()
            
            # Update user's Active Buyer status
            try:
                booking.user.update_active_buyer_status()
            except Exception as e2:
                logger.warning(f"Failed to update active buyer status: {e2}")
            
            # Complete the stock reservation if it exists (in fallback path too)
            from core.inventory.utils import complete_reservation
            try:
                reservation = booking.stock_reservation
                if reservation and reservation.status == 'reserved':
                    complete_reservation(reservation)
                    logger.info(
                        f"Completed stock reservation for booking {booking.id} "
                        f"(fallback path) from Razorpay payment {razorpay_payment.order_id}"
                    )
            except Exception as e3:
                logger.debug(f"No reservation to complete for booking {booking.id} (fallback): {e3}")
        
        # Update booking's payment_gateway_ref
        if not booking.payment_gateway_ref:
            booking.payment_gateway_ref = razorpay_payment.order_id
            booking.save(update_fields=['payment_gateway_ref'])
        
        # Complete the stock reservation if it exists
        from core.inventory.utils import complete_reservation
        try:
            reservation = booking.stock_reservation
            if reservation and reservation.status == 'reserved':
                complete_reservation(reservation)
                logger.info(
                    f"Completed stock reservation for booking {booking.id} "
                    f"from Razorpay payment {razorpay_payment.order_id}"
                )
        except Exception as e:
            # No reservation exists or error accessing it, skip
            logger.debug(f"No reservation to complete for booking {booking.id}: {e}")
        
        logger.info(
            f"Created booking payment {booking_payment.id} for booking {booking.id} "
            f"from Razorpay payment {razorpay_payment.order_id}"
        )
    
    # Return the booking_payment and booking (transaction is committed at this point)
    return booking_payment, booking


def _calculate_amount_from_entity(entity_type, entity_id, requested_amount=None):
    """
    Calculate payable amount from database entity.
    
    Args:
        entity_type (str): Type of entity ('booking', 'payout', etc.)
        entity_id (int): ID of the entity
        requested_amount (float, optional): Specific amount requested by user (in rupees)
    
    Returns:
        tuple: (amount_in_rupees, entity_object, content_type)
    
    Raises:
        ValidationError: If entity not found or invalid
    """
    if entity_type == 'booking':
        from core.booking.models import Booking
        try:
            booking = Booking.objects.get(id=entity_id)
            
            # If user provided a specific amount, validate and use it
            if requested_amount is not None:
                requested_amount_float = float(requested_amount)
                # Validate that requested amount doesn't exceed remaining amount
                if booking.total_paid == 0:
                    max_amount = float(booking.booking_amount)
                else:
                    max_amount = float(booking.remaining_amount)
                
                if requested_amount_float > max_amount:
                    raise ValidationError({
                        'amount': f'Amount cannot exceed remaining amount (₹{max_amount:.2f})'
                    })
                if requested_amount_float <= 0:
                    raise ValidationError({'amount': 'Amount must be greater than 0'})
                
                amount = requested_amount_float
            else:
                # If no payment has been made yet, use booking_amount (initial booking fee)
                # Otherwise, use remaining_amount (outstanding balance)
                if booking.total_paid == 0:
                    amount = float(booking.booking_amount)
                else:
                    amount = float(booking.remaining_amount)
            
            content_type = ContentType.objects.get_for_model(Booking)
            return amount, booking, content_type
        except Booking.DoesNotExist:
            raise ValidationError({'entity_id': f'Booking with id {entity_id} not found'})
    
    elif entity_type == 'payout':
        from core.payout.models import Payout
        try:
            payout = Payout.objects.get(id=entity_id)
            # For payouts, use requested amount if provided, otherwise use full net_amount
            if requested_amount is not None:
                requested_amount_float = float(requested_amount)
                max_amount = float(payout.net_amount)
                if requested_amount_float > max_amount:
                    raise ValidationError({
                        'amount': f'Amount cannot exceed payout amount (₹{max_amount:.2f})'
                    })
                if requested_amount_float <= 0:
                    raise ValidationError({'amount': 'Amount must be greater than 0'})
                amount = requested_amount_float
            else:
                amount = float(payout.net_amount)
            content_type = ContentType.objects.get_for_model(Payout)
            return amount, payout, content_type
        except Payout.DoesNotExist:
            raise ValidationError({'entity_id': f'Payout with id {entity_id} not found'})
    
    else:
        raise ValidationError({'entity_type': f'Unsupported entity type: {entity_type}'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_order(request):
    """
    Create Razorpay order for payment.
    
    POST /api/payments/create-order/
    """
    serializer = CreateOrderRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    entity_type = serializer.validated_data['entity_type']
    entity_id = serializer.validated_data['entity_id']
    requested_amount = serializer.validated_data.get('amount')
    
    try:
        # Calculate amount from database (not trusting frontend)
        # If requested_amount is provided, validate it against the entity's limits
        amount_rupees, entity_obj, content_type = _calculate_amount_from_entity(
            entity_type, entity_id, requested_amount=requested_amount
        )
        
        if amount_rupees <= 0:
            raise ValidationError({'error': 'Amount must be greater than 0'})
        
        # Convert to paise (Razorpay uses paise)
        amount_paise = int(amount_rupees * 100)
        
        # Create Razorpay order
        client = get_razorpay_client()
        order_data = {
            'amount': amount_paise,
            'currency': 'INR',
            'receipt': f'{entity_type}_{entity_id}',
            'notes': {
                'entity_type': entity_type,
                'entity_id': str(entity_id),
                'user_id': str(request.user.id),
            }
        }
        
        razorpay_order = client.order.create(data=order_data)
        order_id = razorpay_order['id']
        
        # Save Payment with CREATED status
        with transaction.atomic():
            payment = Payment.objects.create(
                user=request.user,
                order_id=order_id,
                amount=amount_paise,
                status='CREATED',
                content_type=content_type,
                object_id=entity_id,
                raw_payload=razorpay_order,
            )
        
        logger.info(
            f"Created Razorpay order {order_id} for user {request.user.id}, "
            f"entity_type={entity_type}, entity_id={entity_id}, amount={amount_paise} paise"
        )
        
        # Return response
        response_serializer = CreateOrderResponseSerializer({
            'order_id': order_id,
            'key_id': settings.RAZORPAY_KEY_ID,
            'amount': amount_paise,
        })
        
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
    
    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error creating Razorpay order: {e}", exc_info=True)
        # Return more detailed error in development, generic in production
        error_message = str(e) if settings.DEBUG else 'Failed to create payment order. Please try again.'
        return Response(
            {'error': error_message},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_payment(request):
    """
    Verify Razorpay payment signature and update payment status.
    
    POST /api/payments/verify/
    """
    serializer = VerifyPaymentRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    order_id = serializer.validated_data['razorpay_order_id']
    payment_id = serializer.validated_data['razorpay_payment_id']
    signature = serializer.validated_data['razorpay_signature']
    
    try:
        # Find Payment by order_id
        try:
            payment = Payment.objects.get(order_id=order_id)
        except Payment.DoesNotExist:
            return Response(
                {'error': 'Payment order not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if already processed (idempotency)
        if payment.status in ['SUCCESS', 'FAILED']:
            logger.info(f"Payment {order_id} already processed with status {payment.status}")
            response_serializer = VerifyPaymentResponseSerializer({
                'order_id': payment.order_id,
                'payment_id': payment.payment_id or '',
                'status': payment.status,
                'amount': payment.amount,
                'message': f'Payment already {payment.status.lower()}',
            })
            return Response(response_serializer.data)
        
        # Verify signature
        is_valid = verify_payment_signature(order_id, payment_id, signature)
        
        # Update payment status atomically
        with transaction.atomic():
            payment = Payment.objects.select_for_update().get(order_id=order_id)
            
            # Double-check status (prevent race condition)
            if payment.status in ['SUCCESS', 'FAILED']:
                response_serializer = VerifyPaymentResponseSerializer({
                    'order_id': payment.order_id,
                    'payment_id': payment.payment_id or '',
                    'status': payment.status,
                    'amount': payment.amount,
                    'message': f'Payment already {payment.status.lower()}',
                })
                return Response(response_serializer.data)
            
            if is_valid:
                payment.status = 'SUCCESS'
                payment.payment_id = payment_id
                payment.save()
                logger.info(f"Payment verified successfully: order_id={order_id}, payment_id={payment_id}")
                
                # Process booking payment if this is a booking payment
                try:
                    _process_booking_payment(payment)
                except Exception as e:
                    logger.error(
                        f"Error processing booking payment for Razorpay payment {order_id}: {e}",
                        exc_info=True
                    )
                    # Don't fail the verification if booking payment processing fails
                    # The payment is already verified, booking can be updated manually if needed
            else:
                payment.status = 'FAILED'
                payment.save()
                logger.warning(f"Payment verification failed: order_id={order_id}")
        
        response_serializer = VerifyPaymentResponseSerializer({
            'order_id': payment.order_id,
            'payment_id': payment.payment_id or '',
            'status': payment.status,
            'amount': payment.amount,
            'message': 'Payment verified successfully' if is_valid else 'Payment verification failed',
        })
        
        return Response(response_serializer.data)
    
    except Exception as e:
        logger.error(f"Error verifying payment: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to verify payment. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@csrf_exempt
def webhook(request):
    """
    Handle Razorpay webhook events.
    
    POST /api/payments/webhook/
    CSRF exempt for webhook endpoint
    """
    if request.method != 'POST':
        error_response = {'error': 'Method not allowed'}
        logger.warning(f"📤 Webhook response (405): {error_response}")
        return JsonResponse(error_response, status=405)
    
    try:
        # Read raw body (required for signature verification)
        body = request.body
        
        # Extract signature from header
        header_signature = request.META.get('HTTP_X_RAZORPAY_SIGNATURE', '')
        
        if not header_signature:
            logger.warning("Webhook request missing X-Razorpay-Signature header")
            error_response = {'error': 'Missing signature'}
            logger.warning(f"📤 Webhook response (400): {error_response}")
            return JsonResponse(error_response, status=400)
        
        # Verify webhook signature
        is_valid = verify_webhook_signature(body, header_signature)
        
        if not is_valid:
            logger.warning("Invalid webhook signature")
            error_response = {'error': 'Invalid signature'}
            logger.warning(f"📤 Webhook response (400): {error_response}")
            return JsonResponse(error_response, status=400)
        
        # Parse JSON body
        try:
            payload = json.loads(body.decode('utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in webhook body: {e}")
            error_response = {'error': 'Invalid JSON'}
            logger.error(f"📤 Webhook response (400): {error_response}")
            return JsonResponse(error_response, status=400)
        
        event_type = payload.get('event')
        # Try multiple locations for event_id (Razorpay may use different structures)
        # Standard Razorpay webhook has 'id' at top level, but check multiple locations
        event_id = payload.get('id') or payload.get('event_id')
        
        # Check in payload if it's a dict
        if not event_id:
            payload_data = payload.get('payload', {})
            if isinstance(payload_data, dict):
                event_id = payload_data.get('id')
        
        # Check in entity if it's a dict
        if not event_id:
            entity_data = payload.get('entity', {})
            if isinstance(entity_data, dict):
                event_id = entity_data.get('id')
        
        # If still no event_id, try to generate one from available data for tracking
        if not event_id:
            # Try to create a unique identifier from available data
            payment_id = payload.get('payload', {}).get('payment', {}).get('entity', {}).get('id') or \
                        payload.get('payload', {}).get('payment', {}).get('id')
            order_id = payload.get('payload', {}).get('payment', {}).get('entity', {}).get('order_id') or \
                      payload.get('payload', {}).get('order', {}).get('id')
            
            # Generate a fallback event_id for tracking
            if payment_id or order_id:
                # Create a hash-based ID from payload content + timestamp
                payload_str = json.dumps(payload, sort_keys=True)
                event_id = f"evt_{hashlib.md5((payload_str + str(time.time())).encode()).hexdigest()[:16]}"
                logger.warning(
                    f"⚠️ Webhook payload missing event 'id' field. Generated fallback event_id: {event_id}. "
                    f"event_type={event_type}, payment_id={payment_id}, order_id={order_id}"
                )
            else:
                # Last resort: use timestamp-based ID
                payload_str = json.dumps(payload, sort_keys=True)
                event_id = f"evt_{int(time.time())}_{hashlib.md5(payload_str.encode()).hexdigest()[:8]}"
                logger.warning(
                    f"⚠️ Webhook payload missing event 'id' field and no payment/order identifiers. "
                    f"Generated fallback event_id: {event_id}. event_type={event_type}"
                )
        
        # Extract event_data - handle nested 'entity' structure
        raw_event_data = payload.get('payload', {}).get('payment', {}) or payload.get('payload', {}).get('order', {}) or payload.get('payload', {})
        # If event_data has 'entity' key, use that, otherwise use event_data directly
        if isinstance(raw_event_data, dict) and 'entity' in raw_event_data:
            event_data = raw_event_data.get('entity', raw_event_data)
        else:
            event_data = raw_event_data
        
        # Log full payload + event_id
        logger.info(
            f"📥 Webhook received: event_type={event_type}, event_id={event_id}, "
            f"payload={json.dumps(payload, indent=2)}"
        )
        
        # Track webhook processing status
        webhook_processed = False
        webhook_error = None
        
        # Handle different event types with idempotency check
        with transaction.atomic():
            from .models import WebhookEvent
            
            # Check if this event_id has already been processed (idempotency)
            try:
                existing_event = WebhookEvent.objects.select_for_update().get(event_id=event_id)
                if existing_event.processed:
                    logger.info(
                        f"✅ Webhook event {event_id} already processed at {existing_event.processed_at}. "
                        f"Skipping duplicate processing (idempotent)."
                    )
                    webhook_processed = True
                    # Return success response without processing again
                    response_data = {
                        'status': 'success',
                        'event': event_type,
                        'event_id': event_id,
                        'processed': True,
                        'message': 'Event already processed (idempotent)',
                        'error': None
                    }
                    logger.info(f"📤 Webhook response sent (idempotent): {response_data}")
                    return JsonResponse(response_data, status=200)
                else:
                    # Event exists but not processed - update it
                    webhook_event = existing_event
                    logger.warning(
                        f"⚠️ Webhook event {event_id} exists but was not marked as processed. "
                        f"Will attempt to process again."
                    )
            except WebhookEvent.DoesNotExist:
                # Create new webhook event record
                webhook_event = WebhookEvent.objects.create(
                    event_id=event_id,
                    event_type=event_type,
                    payload=payload,
                    processed=False
                )
                logger.info(f"📝 Created new webhook event record: {event_id}")
            
            # Initialize payment variable to avoid UnboundLocalError
            payment = None
            
            if event_type == 'payment.captured':
                payment_id = event_data.get('id')
                order_id = event_data.get('order_id')
                
                # Skip if both order_id and payment_id are missing
                if not order_id and not payment_id:
                    logger.warning(
                        f"⚠️ payment.captured webhook received with missing order_id and payment_id. "
                        f"Event data: {event_data}, Event ID: {event_id}"
                    )
                    webhook_error = "Both order_id and payment_id are missing"
                else:
                    # First, try to find Payment by payment_id (if already set)
                    # This prevents duplicates when the same payment_id is assigned to multiple orders
                    if payment_id:
                        existing_payments = Payment.objects.filter(payment_id=payment_id).select_for_update()
                        if existing_payments.exists():
                            payment = existing_payments.first()
                            if existing_payments.count() > 1:
                                logger.warning(
                                    f"Multiple Payment records found with payment_id={payment_id}. "
                                    f"Using the first one for webhook update."
                                )
                            # If found by payment_id but order_id doesn't match, log warning
                            if order_id and payment.order_id != order_id:
                                logger.warning(
                                    f"Payment found by payment_id={payment_id} has different order_id. "
                                    f"Expected: {order_id}, Found: {payment.order_id}"
                                )
                    
                    # If not found by payment_id, try by order_id
                    if not payment and order_id:
                        try:
                            payment = Payment.objects.select_for_update().get(order_id=order_id)
                        except Payment.DoesNotExist:
                            logger.warning(
                                f"Payment not found for webhook: order_id={order_id}, payment_id={payment_id}, "
                                f"event_id={event_id}"
                            )
                            payment = None
                            webhook_error = f"Payment not found for order_id={order_id}, payment_id={payment_id}"
                    elif not payment and not order_id:
                        logger.warning(
                            f"⚠️ Cannot process payment.captured webhook: order_id is missing. "
                            f"payment_id={payment_id}, event_id={event_id}"
                        )
                        webhook_error = "order_id is missing from webhook payload"
                
                if payment:
                    # Check if payment_id is already set and different
                    if payment.payment_id and payment.payment_id != payment_id:
                        logger.warning(
                            f"Payment {payment.order_id} already has payment_id={payment.payment_id}, "
                            f"but webhook has payment_id={payment_id}. Not updating payment_id."
                        )
                    elif not payment.payment_id:
                        # Only set payment_id if it's not already set
                        payment.payment_id = payment_id
                    
                    if payment.status != 'SUCCESS':
                        payment.status = 'SUCCESS'
                        payment.raw_payload = payload
                        payment.save()
                        webhook_processed = True
                        logger.info(f"✅ Updated payment to SUCCESS via webhook: order_id={order_id}, payment_id={payment_id}")
                        
                        # Process booking payment if this is a booking payment
                        try:
                            _process_booking_payment(payment)
                        except Exception as e:
                            logger.error(
                                f"Error processing booking payment for webhook payment {order_id}: {e}",
                                exc_info=True
                            )
                            # Don't mark as failed if booking payment processing fails - payment was still updated
                    else:
                        # Payment already has SUCCESS status
                        webhook_processed = True
                        logger.info(f"✅ Payment already has SUCCESS status: order_id={order_id}, payment_id={payment_id}")
            
            elif event_type == 'payment.failed':
                payment_id = event_data.get('id')
                order_id = event_data.get('order_id')
                
                # Skip if both order_id and payment_id are missing
                if not order_id and not payment_id:
                    logger.warning(
                        f"⚠️ payment.failed webhook received with missing order_id and payment_id. "
                        f"Event data: {event_data}, Event ID: {event_id}"
                    )
                    webhook_error = "Both order_id and payment_id are missing"
                    payment = None
                else:
                    # First, try to find Payment by payment_id (if already set)
                    payment = None
                    if payment_id:
                        existing_payments = Payment.objects.filter(payment_id=payment_id).select_for_update()
                        if existing_payments.exists():
                            payment = existing_payments.first()
                            if existing_payments.count() > 1:
                                logger.warning(
                                    f"Multiple Payment records found with payment_id={payment_id}. "
                                    f"Using the first one for webhook update."
                                )
                    
                    # If not found by payment_id, try by order_id
                    if not payment and order_id:
                        try:
                            payment = Payment.objects.select_for_update().get(order_id=order_id)
                        except Payment.DoesNotExist:
                            logger.warning(
                                f"Payment not found for webhook: order_id={order_id}, payment_id={payment_id}, "
                                f"event_id={event_id}"
                            )
                            payment = None
                            webhook_error = f"Payment not found for order_id={order_id}, payment_id={payment_id}"
                    elif not payment and not order_id:
                        logger.warning(
                            f"⚠️ Cannot process payment.failed webhook: order_id is missing. "
                            f"payment_id={payment_id}, event_id={event_id}"
                        )
                        webhook_error = "order_id is missing from webhook payload"
                
                if payment:
                    # Check if payment_id is already set and different
                    if payment.payment_id and payment.payment_id != payment_id:
                        logger.warning(
                            f"Payment {payment.order_id} already has payment_id={payment.payment_id}, "
                            f"but webhook has payment_id={payment_id}. Not updating payment_id."
                        )
                    elif not payment.payment_id:
                        # Only set payment_id if it's not already set
                        payment.payment_id = payment_id
                    
                    if payment.status != 'FAILED':
                        payment.status = 'FAILED'
                        payment.raw_payload = payload
                        payment.save()
                        webhook_processed = True
                        logger.info(f"✅ Updated payment to FAILED via webhook: order_id={order_id}, payment_id={payment_id}")
                    else:
                        # Payment already has FAILED status
                        webhook_processed = True
                        logger.info(f"✅ Payment already has FAILED status: order_id={order_id}, payment_id={payment_id}")
            
            elif event_type == 'order.paid':
                order_id = event_data.get('id')
                payment_data = payload.get('payload', {}).get('payment', {})
                payment_id = payment_data.get('id') if payment_data else None
                
                # First, try to find Payment by payment_id (if available)
                payment = None
                if payment_id:
                    existing_payments = Payment.objects.filter(payment_id=payment_id).select_for_update()
                    if existing_payments.exists():
                        payment = existing_payments.first()
                        if existing_payments.count() > 1:
                            logger.warning(
                                f"Multiple Payment records found with payment_id={payment_id}. "
                                f"Using the first one for webhook update."
                            )
                
                # If not found by payment_id, try by order_id
                if not payment:
                    try:
                        payment = Payment.objects.select_for_update().get(order_id=order_id)
                    except Payment.DoesNotExist:
                        logger.warning(f"Payment not found for webhook: order_id={order_id}, payment_id={payment_id}")
                        payment = None
                
                if payment:
                    # Try to get payment_id from payload if available
                    if payment_id:
                        # Check if payment_id is already set and different
                        if payment.payment_id and payment.payment_id != payment_id:
                            logger.warning(
                                f"Payment {payment.order_id} already has payment_id={payment.payment_id}, "
                                f"but webhook has payment_id={payment_id}. Not updating payment_id."
                            )
                        elif not payment.payment_id:
                            # Only set payment_id if it's not already set
                            payment.payment_id = payment_id
                    
                    if payment.status != 'SUCCESS':
                        payment.status = 'SUCCESS'
                        payment.raw_payload = payload
                        payment.save()
                        webhook_processed = True
                        logger.info(f"✅ Updated payment to SUCCESS via order.paid webhook: order_id={order_id}, payment_id={payment_id}")
                        
                        # Process booking payment if this is a booking payment
                        try:
                            _process_booking_payment(payment)
                        except Exception as e:
                            logger.error(
                                f"Error processing booking payment for webhook payment {order_id}: {e}",
                                exc_info=True
                            )
                            # Don't mark as failed if booking payment processing fails - payment was still updated
                    else:
                        # Payment already has SUCCESS status
                        webhook_processed = True
                        logger.info(f"✅ Payment already has SUCCESS status: order_id={order_id}, payment_id={payment_id}")
            
            elif event_type == 'refund.processed':
                # For refund.processed events, payment_id is in the refund entity, not in event_data
                # Try multiple locations where payment_id might be
                refund_data = payload.get('payload', {}).get('refund', {})
                payment_id = None
                refund_id = None
                webhook_processed = False
                webhook_error = None
                
                # Extract refund_id for tracking
                if refund_data:
                    if isinstance(refund_data, dict):
                        if 'entity' in refund_data and isinstance(refund_data['entity'], dict):
                            refund_id = refund_data['entity'].get('id')
                            payment_id = refund_data['entity'].get('payment_id')
                        if not refund_id:
                            refund_id = refund_data.get('id')
                        if not payment_id:
                            payment_id = refund_data.get('payment_id')
                
                # Fallback: try to get from payment entity if available
                if not payment_id:
                    payment_entity = payload.get('payload', {}).get('payment', {})
                    if payment_entity:
                        if isinstance(payment_entity, dict):
                            if 'entity' in payment_entity and isinstance(payment_entity['entity'], dict):
                                payment_id = payment_entity['entity'].get('id')
                            if not payment_id:
                                payment_id = payment_entity.get('id')
                
                # Only process if we have a valid payment_id
                if payment_id:
                    try:
                        payment = Payment.objects.select_for_update().get(payment_id=payment_id)
                        if payment.status != 'REFUNDED':
                            payment.status = 'REFUNDED'
                            payment.raw_payload = payload
                            payment.save()
                            webhook_processed = True
                            logger.info(
                                f"✅ Refund webhook processed successfully: "
                                f"payment_id={payment_id}, refund_id={refund_id}, "
                                f"order_id={payment.order_id}, event_id={payload.get('id', 'N/A')}"
                            )
                        else:
                            webhook_processed = True
                            logger.info(
                                f"✅ Refund webhook received (already processed): "
                                f"payment_id={payment_id}, refund_id={refund_id}, "
                                f"order_id={payment.order_id}, event_id={payload.get('id', 'N/A')}"
                            )
                    except Payment.DoesNotExist:
                        webhook_error = f"Payment not found for payment_id={payment_id}"
                        logger.warning(
                            f"❌ {webhook_error}. "
                            f"refund_id={refund_id}, event_id={payload.get('id', 'N/A')}"
                        )
                    except Payment.MultipleObjectsReturned:
                        # Handle duplicate payment_ids - update the latest payment
                        logger.warning(
                            f"⚠️ Multiple Payment records found for payment_id={payment_id}. "
                            f"Updating the latest payment to REFUNDED."
                        )
                        payment = Payment.objects.filter(payment_id=payment_id).select_for_update().latest('created_at')
                        if payment.status != 'REFUNDED':
                            payment.status = 'REFUNDED'
                            payment.raw_payload = payload
                            payment.save()
                            webhook_processed = True
                            logger.info(
                                f"✅ Refund webhook processed (duplicate handled): "
                                f"payment_id={payment_id}, refund_id={refund_id}, "
                                f"order_id={payment.order_id}, event_id={payload.get('id', 'N/A')}"
                            )
                        else:
                            webhook_processed = True
                            logger.info(
                                f"✅ Refund webhook received (duplicate, already processed): "
                                f"payment_id={payment_id}, refund_id={refund_id}, "
                                f"order_id={payment.order_id}, event_id={payload.get('id', 'N/A')}"
                            )
                else:
                    webhook_error = "payment_id is missing from webhook payload"
                    logger.error(
                        f"❌ Cannot process refund.processed webhook: {webhook_error}. "
                        f"Refund data: {refund_data}, event_id={payload.get('id', 'N/A')}"
                    )
            
            else:
                logger.warning(f"Unknown webhook event type: {event_type}")
                # Store unknown events for debugging
                Payment.objects.create(
                    raw_payload=payload,
                    status='CREATED',
                    order_id=f"webhook_{event_type}_{payload.get('payload', {}).get('payment', {}).get('id', 'unknown')}",
                    amount=0,
                )
            
            # Mark webhook event as processed (inside transaction)
            webhook_event.processed = webhook_processed
            webhook_event.error_message = webhook_error if webhook_error else None
            if webhook_processed:
                from django.utils import timezone
                webhook_event.processed_at = timezone.now()
            webhook_event.save()
            logger.info(
                f"💾 Webhook event {event_id} marked as processed={webhook_processed} "
                f"(error: {webhook_error if webhook_error else 'None'})"
            )
        
        # Always return 200 OK to prevent Razorpay from retrying
        # Include processing status in response for debugging
        response_data = {
            'status': 'success',
            'event': event_type,
            'event_id': event_id,
            'processed': webhook_processed,
            'error': webhook_error if webhook_error else None
        }
        
        # Log the response being sent
        logger.info(
            f"📤 Webhook response sent: event={event_type}, event_id={event_id}, "
            f"processed={webhook_processed}, error={webhook_error if webhook_error else 'None'}, "
            f"response_data={response_data}"
        )
        
        return JsonResponse(response_data, status=200)
    
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        # Still return 200 to prevent retries
        error_response = {'status': 'error', 'message': str(e)}
        logger.info(f"📤 Webhook error response sent: {error_response}")
        return JsonResponse(error_response, status=200)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_payout(request):
    """
    Create Razorpay payout/transfer for existing Payout model.
    
    POST /api/payments/create-payout/
    Admin/Staff only
    """
    # Check if user is admin or staff
    if not (request.user.is_superuser or request.user.role in ['admin', 'staff']):
        raise PermissionDenied("Only admin or staff can create payouts")
    
    serializer = CreatePayoutRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    payout_id = serializer.validated_data['payout_id']
    
    try:
        from core.payout.models import Payout
        
        # Get Payout object
        try:
            payout = Payout.objects.get(id=payout_id)
        except Payout.DoesNotExist:
            return Response(
                {'error': f'Payout with id {payout_id} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Verify payout status is 'processing'
        if payout.status != 'processing':
            raise ValidationError({
                'error': f'Payout status must be "processing" to create Razorpay transfer. Current status: {payout.status}'
            })
        
        # Extract bank details
        account_number = payout.account_number
        ifsc_code = payout.ifsc_code
        account_holder_name = payout.account_holder_name
        bank_name = payout.bank_name
        
        # Convert net_amount to paise
        amount_paise = int(float(payout.net_amount) * 100)
        
        # Create Razorpay payout/transfer
        client = get_razorpay_client()
        
        # Use Razorpay's fund account and payout API
        # First, create a fund account (or use existing)
        fund_account_data = {
            'account_type': 'bank_account',
            'bank_account': {
                'name': account_holder_name,
                'ifsc': ifsc_code,
                'account_number': account_number,
            }
        }
        
        try:
            # Create fund account
            fund_account = client.fund_account.create(fund_account_data)
            fund_account_id = fund_account['id']
            
            # Create payout
            payout_data = {
                'account_number': settings.RAZORPAY_ACCOUNT_NUMBER if hasattr(settings, 'RAZORPAY_ACCOUNT_NUMBER') else None,
                'fund_account': {
                    'id': fund_account_id,
                    'account_type': 'bank_account',
                },
                'amount': amount_paise,
                'currency': 'INR',
                'mode': 'NEFT',  # or 'RTGS', 'IMPS' based on amount
                'purpose': 'payout',
                'queue_if_low_balance': True,
                'reference_id': f'payout_{payout_id}',
                'narration': f'Payout for user {payout.user.username}',
            }
            
            razorpay_payout = client.payout.create(payout_data)
            razorpay_payout_id = razorpay_payout['id']
            
            # Update Payout model
            with transaction.atomic():
                payout.transaction_id = razorpay_payout_id
                # Status will be updated by webhook or manual check
                payout.save()
            
            logger.info(
                f"Created Razorpay payout {razorpay_payout_id} for Payout {payout_id}, "
                f"amount={amount_paise} paise"
            )
            
            response_serializer = CreatePayoutResponseSerializer({
                'payout_id': payout.id,
                'transaction_id': razorpay_payout_id,
                'status': payout.status,
                'message': 'Payout created successfully',
            })
            
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        
        except Exception as razorpay_error:
            logger.error(f"Razorpay API error creating payout: {razorpay_error}", exc_info=True)
            # Check if it's a fund account already exists error
            if 'already exists' in str(razorpay_error).lower():
                # Try to use existing fund account or create payout directly
                # For simplicity, we'll return the error
                return Response(
                    {'error': f'Failed to create payout: {str(razorpay_error)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            raise
    
    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error creating Razorpay payout: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to create payout. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_refund(request):
    """
    Create Razorpay refund (full or partial).
    
    POST /api/payments/refund/
    Admin/Staff only
    """
    # Check if user is admin or staff
    if not (request.user.is_superuser or request.user.role in ['admin', 'staff']):
        raise PermissionDenied("Only admin or staff can create refunds")
    
    serializer = CreateRefundRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    payment_id = serializer.validated_data['payment_id']
    amount_rupees = serializer.validated_data.get('amount')
    
    try:
        # Find Payment by payment_id (Razorpay payment ID)
        try:
            payment = Payment.objects.get(payment_id=payment_id)
        except Payment.DoesNotExist:
            return Response(
                {'error': f'Payment with payment_id {payment_id} not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Payment.MultipleObjectsReturned:
            # Handle duplicate payment_ids - use the latest payment
            logger.warning(
                f"Multiple Payment records found for payment_id={payment_id}. "
                f"Using the latest payment for refund."
            )
            payment = Payment.objects.filter(payment_id=payment_id).latest('created_at')
        
        # Verify payment status is SUCCESS (can only refund successful payments)
        if payment.status != 'SUCCESS':
            raise ValidationError({
                'error': f'Can only refund successful payments. Current status: {payment.status}'
            })
        
        # Check if already refunded (idempotency)
        if payment.status == 'REFUNDED':
            logger.info(f"Payment {payment_id} already refunded")
            return Response(
                {'error': 'Payment already refunded'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Determine refund amount
        if amount_rupees is not None:
            # Partial refund
            amount_paise = int(float(amount_rupees) * 100)
            if amount_paise <= 0 or amount_paise > payment.amount:
                raise ValidationError({
                    'amount': 'Refund amount must be greater than 0 and not exceed payment amount'
                })
        else:
            # Full refund
            amount_paise = payment.amount
        
        # Create Razorpay refund
        client = get_razorpay_client()
        
        refund_data = {
            'payment_id': payment_id,
            'amount': amount_paise,
            'notes': {
                'refund_reason': 'Admin initiated refund',
                'original_order_id': payment.order_id,
            }
        }
        
        razorpay_refund = client.payment.refund(payment_id, refund_data)
        refund_id = razorpay_refund['id']
        
        # Update Payment model
        with transaction.atomic():
            try:
                payment = Payment.objects.select_for_update().get(payment_id=payment_id)
            except Payment.MultipleObjectsReturned:
                # Handle duplicate payment_ids - use the latest payment
                logger.warning(
                    f"Multiple Payment records found for payment_id={payment_id} in transaction. "
                    f"Using the latest payment for refund."
                )
                payment = Payment.objects.filter(payment_id=payment_id).select_for_update().latest('created_at')
            
            # Double-check status
            if payment.status == 'REFUNDED':
                return Response(
                    {'error': 'Payment already refunded'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            payment.status = 'REFUNDED'
            # Store refund details in raw_payload
            if payment.raw_payload:
                payment.raw_payload['refunds'] = payment.raw_payload.get('refunds', []) + [razorpay_refund]
            else:
                payment.raw_payload = {'refunds': [razorpay_refund]}
            payment.save()
        
        logger.info(
            f"Created Razorpay refund {refund_id} for payment {payment_id}, "
            f"amount={amount_paise} paise"
        )
        
        response_serializer = CreateRefundResponseSerializer({
            'refund_id': refund_id,
            'payment_id': payment_id,
            'amount': amount_paise,
            'status': 'REFUNDED',
            'message': 'Refund created successfully',
        })
        
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)
    
    except ValidationError:
        raise
    except Exception as e:
        logger.error(f"Error creating Razorpay refund: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to create refund. Please try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

