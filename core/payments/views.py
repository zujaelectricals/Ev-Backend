from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.conf import settings
import json
import logging
import time
import requests
from functools import wraps
from urllib3.exceptions import ReadTimeoutError as Urllib3ReadTimeoutError

from .models import Payment
from .serializers import (
    CreateOrderRequestSerializer,
    VerifyPaymentRequestSerializer,
    CreatePayoutRequestSerializer,
    CreatePayoutResponseSerializer,
    CreateRefundRequestSerializer,
    CreateRefundResponseSerializer,
)

from .utils.razorpay_client import get_razorpay_client
from .utils.razorpayx_client import (
    create_razorpayx_contact,
    get_razorpayx_contact_by_email,
    create_razorpayx_fund_account,
    create_razorpayx_payout
)
from .utils.signature import verify_payment_signature, verify_webhook_signature

# ✅ ASYNC TASK
from core.payments.tasks import process_booking_payment_task

logger = logging.getLogger(__name__)

RAZORPAY_NET_TO_GROSS_DIVISOR = 0.9764
RAZORPAY_MAX_RETRIES = getattr(settings, 'RAZORPAY_MAX_RETRIES', 2)
RAZORPAY_RETRY_BACKOFF_BASE = getattr(settings, 'RAZORPAY_RETRY_BACKOFF_BASE', 1)


def retry_on_timeout(max_retries=RAZORPAY_MAX_RETRIES, backoff_base=RAZORPAY_RETRY_BACKOFF_BASE):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (requests.exceptions.Timeout, Urllib3ReadTimeoutError):
                    if attempt == max_retries:
                        raise
                    time.sleep(backoff_base * (2 ** attempt))
        return wrapper
    return decorator


def _calculate_gross_amount_with_charges(net_amount_rupees):
    from decimal import Decimal, ROUND_HALF_UP
    net = Decimal(str(net_amount_rupees))
    gross = (net / Decimal(str(RAZORPAY_NET_TO_GROSS_DIVISOR))).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP
    )
    return float(gross), float(gross - net)


# ───────────────────────── CREATE ORDER ─────────────────────────
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_order(request):
    serializer = CreateOrderRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    entity_type = serializer.validated_data['entity_type']
    entity_id = serializer.validated_data['entity_id']

    from core.booking.models import Booking
    booking = Booking.objects.get(id=entity_id)

    net_amount = float(booking.remaining_amount)
    gross_amount, gateway_charges = _calculate_gross_amount_with_charges(net_amount)

    client = get_razorpay_client()

    @retry_on_timeout()
    def create_order_api():
        return client.order.create({
            "amount": int(gross_amount * 100),
            "currency": "INR",
            "receipt": f"{entity_type}_{entity_id}",
        })

    razorpay_order = create_order_api()

    Payment.objects.create(
        user=request.user,
        order_id=razorpay_order['id'],
        amount=int(gross_amount * 100),
        net_amount=int(net_amount * 100),
        gateway_charges=int(gateway_charges * 100),
        status='CREATED',
        content_type=ContentType.objects.get_for_model(Booking),
        object_id=entity_id,
        raw_payload=razorpay_order,
    )

    return Response({
        'order_id': razorpay_order['id'],
        'key_id': settings.RAZORPAY_KEY_ID,
        'amount': int(gross_amount * 100),
    }, status=201)


# ───────────────────────── VERIFY PAYMENT ─────────────────────────
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_payment(request):
    serializer = VerifyPaymentRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    order_id = serializer.validated_data['razorpay_order_id']
    payment_id = serializer.validated_data['razorpay_payment_id']
    signature = serializer.validated_data['razorpay_signature']

    try:
        payment = Payment.objects.get(order_id=order_id)
    except Payment.DoesNotExist:
        return Response({'error': 'Order not found'}, status=404)

    if payment.status in ['SUCCESS', 'FAILED']:
        return Response({'status': payment.status})

    if not verify_payment_signature(order_id, payment_id, signature):
        payment.status = 'FAILED'
        payment.save()
        return Response({'status': 'FAILED'})

    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(order_id=order_id)
        payment.status = 'SUCCESS'
        payment.payment_id = payment_id
        payment.save()

    # ✅ ASYNC
    process_booking_payment_task.delay(payment.id)

    return Response({'status': 'SUCCESS'})


# ───────────────────────── WEBHOOK ─────────────────────────
@csrf_exempt
def webhook(request):
    signature = request.META.get('HTTP_X_RAZORPAY_SIGNATURE')
    if not signature:
        return JsonResponse({'error': 'missing signature'}, status=400)

    body = request.body
    if not verify_webhook_signature(body, signature):
        return JsonResponse({'error': 'invalid signature'}, status=400)

    payload = json.loads(body.decode())
    event = payload.get('event')
    entity = payload.get('payload', {}).get('payment', {}).get('entity', {})

    order_id = entity.get('order_id')
    payment_id = entity.get('id')

    if not order_id:
        return JsonResponse({'status': 'ignored'}, status=200)

    with transaction.atomic():
        try:
            payment = Payment.objects.select_for_update().get(order_id=order_id)
        except Payment.DoesNotExist:
            return JsonResponse({'status': 'not_found'}, status=200)

        if event in ['payment.captured', 'order.paid']:
            if payment.status != 'SUCCESS':
                payment.status = 'SUCCESS'
                payment.payment_id = payment_id
                payment.raw_payload = payload
                payment.save()
                process_booking_payment_task.delay(payment.id)

        elif event == 'payment.failed':
            payment.status = 'FAILED'
            payment.save()

    return JsonResponse({'status': 'ok'}, status=200)


# ───────────────────────── CREATE PAYOUT ─────────────────────────
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_payout(request):
    if not (request.user.is_superuser or request.user.role in ['admin', 'staff']):
        raise PermissionDenied("Only admin or staff can create payouts")

    serializer = CreatePayoutRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    from core.payout.models import Payout
    payout = Payout.objects.get(id=serializer.validated_data['payout_id'])

    if payout.status != 'processing':
        raise ValidationError({'error': 'Payout must be in processing state'})

    amount_paise = int(float(payout.net_amount) * 100)
    razorpayx_account_number = settings.RAZORPAYX_ACCOUNT_NUMBER

    user = payout.user
    contact_data = {
        'name': payout.account_holder_name,
        'email': user.email or f'user_{user.id}@example.com',
        'contact': getattr(user, 'phone', '9999999999'),
        'type': 'customer',
    }

    contact = create_razorpayx_contact(contact_data)
    fund_account = create_razorpayx_fund_account({
        'contact_id': contact['id'],
        'account_type': 'bank_account',
        'bank_account': {
            'name': payout.account_holder_name,
            'ifsc': payout.ifsc_code,
            'account_number': payout.account_number,
        }
    })

    payout_result = create_razorpayx_payout({
        'account_number': razorpayx_account_number,
        'amount': amount_paise,
        'currency': 'INR',
        'mode': 'NEFT',
        'purpose': 'payout',
        'fund_account': fund_account,
    })

    payout.transaction_id = payout_result['id']
    payout.save()

    return Response(CreatePayoutResponseSerializer({
        'payout_id': payout.id,
        'transaction_id': payout.transaction_id,
        'status': payout.status,
        'message': 'Payout created successfully',
    }).data, status=201)


# ───────────────────────── CREATE REFUND ─────────────────────────
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_refund(request):
    if not (request.user.is_superuser or request.user.role in ['admin', 'staff']):
        raise PermissionDenied("Only admin or staff can create refunds")

    serializer = CreateRefundRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    payment = Payment.objects.get(payment_id=serializer.validated_data['payment_id'])

    if payment.status != 'SUCCESS':
        raise ValidationError({'error': 'Only successful payments can be refunded'})

    amount = serializer.validated_data.get('amount')
    amount_paise = int(amount * 100) if amount else payment.amount

    client = get_razorpay_client()
    refund = client.payment.refund(payment.payment_id, {'amount': amount_paise})

    payment.status = 'REFUNDED'
    payment.raw_payload = payment.raw_payload or {}
    payment.raw_payload['refund'] = refund
    payment.save()

    return Response(CreateRefundResponseSerializer({
        'refund_id': refund['id'],
        'payment_id': payment.payment_id,
        'amount': amount_paise,
        'status': 'REFUNDED',
        'message': 'Refund processed successfully',
    }).data, status=201)
