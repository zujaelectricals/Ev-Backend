from rest_framework import serializers
from .models import Payment


class CreateOrderRequestSerializer(serializers.Serializer):
    """Serializer for create order request"""
    entity_type = serializers.ChoiceField(
        choices=['booking', 'payout'],
        help_text="Type of entity to create payment for"
    )
    entity_id = serializers.IntegerField(
        min_value=1,
        help_text="ID of the entity (booking_id, payout_id, etc.)"
    )
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        min_value=0.01,
        help_text="Amount in rupees for partial payment (optional - if not provided, uses full remaining amount for bookings or full amount for payouts)"
    )


class CreateOrderResponseSerializer(serializers.Serializer):
    """Serializer for create order response"""
    order_id = serializers.CharField()
    key_id = serializers.CharField()
    amount = serializers.IntegerField(help_text="Gross amount in paise (what user pays, includes gateway charges)")
    net_amount = serializers.IntegerField(help_text="Net amount in paise (what gets credited to booking/payout)")
    gateway_charges = serializers.IntegerField(help_text="Gateway charges in paise (2.36% of gross amount)")
    amount_rupees = serializers.FloatField(help_text="Gross amount in rupees (for display)")
    net_amount_rupees = serializers.FloatField(help_text="Net amount in rupees (for display)")
    gateway_charges_rupees = serializers.FloatField(help_text="Gateway charges in rupees (for display)")


class VerifyPaymentRequestSerializer(serializers.Serializer):
    """Serializer for verify payment request"""
    razorpay_order_id = serializers.CharField(required=True)
    razorpay_payment_id = serializers.CharField(required=True)
    razorpay_signature = serializers.CharField(required=True)


class VerifyPaymentResponseSerializer(serializers.Serializer):
    """Serializer for verify payment response"""
    order_id = serializers.CharField()
    payment_id = serializers.CharField()
    status = serializers.CharField()
    amount = serializers.IntegerField(help_text="Amount in paise")
    message = serializers.CharField()


class CreatePayoutRequestSerializer(serializers.Serializer):
    """Serializer for create payout request"""
    payout_id = serializers.IntegerField(
        min_value=1,
        help_text="ID of the Payout model instance"
    )


class CreatePayoutResponseSerializer(serializers.Serializer):
    """Serializer for create payout response"""
    payout_id = serializers.IntegerField()
    transaction_id = serializers.CharField(help_text="Razorpay payout/transfer ID")
    status = serializers.CharField()
    message = serializers.CharField()


class CreateRefundRequestSerializer(serializers.Serializer):
    """Serializer for create refund request"""
    payment_id = serializers.CharField(
        required=True,
        help_text="Razorpay payment_id from Payment model"
    )
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        help_text="Amount in rupees for partial refund (null/omitted = full refund)"
    )


class CreateRefundResponseSerializer(serializers.Serializer):
    """Serializer for create refund response"""
    refund_id = serializers.CharField(help_text="Razorpay refund ID")
    payment_id = serializers.CharField()
    amount = serializers.IntegerField(help_text="Refund amount in paise")
    status = serializers.CharField()
    message = serializers.CharField()


class PaymentSerializer(serializers.ModelSerializer):
    """Serializer for Payment model"""
    amount_in_rupees = serializers.ReadOnlyField()
    net_amount_in_rupees = serializers.ReadOnlyField()
    gateway_charges_in_rupees = serializers.ReadOnlyField()
    
    class Meta:
        model = Payment
        fields = [
            'id',
            'user',
            'order_id',
            'payment_id',
            'amount',
            'amount_in_rupees',
            'net_amount',
            'net_amount_in_rupees',
            'gateway_charges',
            'gateway_charges_in_rupees',
            'status',
            'content_type',
            'object_id',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'order_id',
            'payment_id',
            'created_at',
            'updated_at',
        ]

