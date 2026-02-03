# Refund Webhook Verification Guide

This guide explains how to verify if a refund webhook from Razorpay was properly accepted and processed.

## Methods to Verify Refund Webhook Processing

### 1. **Check Webhook Response** (Immediate)

The webhook endpoint now returns a detailed response indicating processing status:

```json
{
  "status": "success",
  "event": "refund.processed",
  "event_id": "evt_xxxxx",
  "processed": true,
  "error": null
}
```

**Response Fields:**
- `status`: Always "success" (we return 200 OK to prevent Razorpay retries)
- `event`: The webhook event type (e.g., "refund.processed")
- `event_id`: Razorpay's event ID for tracking
- `processed`: `true` if refund was successfully processed, `false` otherwise
- `error`: Error message if processing failed (null if successful)

**Note:** Razorpay webhooks are typically sent via POST, so you may need to check server logs or implement webhook logging to see the response.

### 2. **Check Application Logs** (Recommended)

The webhook handler logs detailed information with emoji indicators:

**Success Logs:**
```
✅ Refund webhook processed successfully: payment_id=pay_xxx, refund_id=rfnd_xxx, order_id=order_xxx, event_id=evt_xxx
```

**Already Processed:**
```
✅ Refund webhook received (already processed): payment_id=pay_xxx, refund_id=rfnd_xxx, order_id=order_xxx, event_id=evt_xxx
```

**Error Logs:**
```
❌ Cannot process refund.processed webhook: payment_id is missing from webhook payload. event_id=evt_xxx
❌ Payment not found for payment_id=pay_xxx. refund_id=rfnd_xxx, event_id=evt_xxx
```

**Warning Logs:**
```
⚠️ Multiple Payment records found for payment_id=pay_xxx. Updating the latest payment to REFUNDED.
```

### 3. **Check Payment Model Status** (Database)

Query the `razorpay_payments` table to verify the payment status:

```python
from core.payments.models import Payment

# Find payment by payment_id
payment = Payment.objects.get(payment_id='pay_SBeWQdn5pM1hIF')
print(f"Status: {payment.status}")  # Should be 'REFUNDED'
print(f"Raw Payload: {payment.raw_payload}")  # Contains full webhook data
```

**Via Django Shell:**
```bash
python manage.py shell
```

```python
from core.payments.models import Payment

# Check by payment_id
payment = Payment.objects.filter(payment_id='pay_SBeWQdn5pM1hIF').first()
if payment:
    print(f"Order ID: {payment.order_id}")
    print(f"Payment ID: {payment.payment_id}")
    print(f"Status: {payment.status}")
    print(f"Updated At: {payment.updated_at}")
    
    # Check if refund data is in raw_payload
    if payment.raw_payload and 'refund' in str(payment.raw_payload):
        print("✅ Refund webhook data found in raw_payload")
    else:
        print("❌ No refund webhook data in raw_payload")
```

### 4. **Check by Order ID**

If you have the order_id:

```python
from core.payments.models import Payment

payment = Payment.objects.get(order_id='order_SBeWEISHmWkvLB')
print(f"Payment ID: {payment.payment_id}")
print(f"Status: {payment.status}")  # Should be 'REFUNDED' if refund processed
```

### 5. **Check Raw Payload for Refund Details**

The `raw_payload` field stores the complete webhook payload, including refund information:

```python
payment = Payment.objects.get(payment_id='pay_SBeWQdn5pM1hIF')
payload = payment.raw_payload

# Extract refund information
if payload and 'payload' in payload:
    refund_data = payload['payload'].get('refund', {})
    if refund_data:
        refund_entity = refund_data.get('entity', refund_data)
        refund_id = refund_entity.get('id')
        refund_amount = refund_entity.get('amount')  # in paise
        refund_status = refund_entity.get('status')
        
        print(f"Refund ID: {refund_id}")
        print(f"Refund Amount: ₹{refund_amount / 100:.2f}")
        print(f"Refund Status: {refund_status}")
```

### 6. **Check via API Endpoint** (If Available)

If you have an admin API endpoint to check payment status:

```bash
GET /api/payments/payments/?payment_id=pay_SBeWQdn5pM1hIF
```

### 7. **Database Query Examples**

**Find all refunded payments:**
```sql
SELECT order_id, payment_id, status, updated_at 
FROM razorpay_payments 
WHERE status = 'REFUNDED' 
ORDER BY updated_at DESC;
```

**Find payments by refund_id (from raw_payload):**
```sql
SELECT order_id, payment_id, status, raw_payload 
FROM razorpay_payments 
WHERE raw_payload::text LIKE '%rfnd_SBeWsllF7U1lmj%';
```

**Check recent refund webhooks:**
```sql
SELECT order_id, payment_id, status, updated_at, raw_payload 
FROM razorpay_payments 
WHERE status = 'REFUNDED' 
  AND updated_at > NOW() - INTERVAL '24 hours'
ORDER BY updated_at DESC;
```

## Verification Checklist

When verifying a refund webhook was processed:

- [ ] Check application logs for success message with ✅
- [ ] Verify Payment.status = 'REFUNDED' in database
- [ ] Check Payment.raw_payload contains refund data
- [ ] Verify Payment.updated_at timestamp matches webhook time
- [ ] Confirm refund_id exists in raw_payload
- [ ] Check for any error logs with ❌

## Common Issues

### Issue: Payment Status Not Updated to REFUNDED

**Possible Causes:**
1. Webhook not received (check Razorpay dashboard)
2. Webhook signature verification failed
3. Payment record not found in database
4. payment_id mismatch

**Solution:**
- Check application logs for error messages
- Verify payment_id exists in database
- Check Razorpay webhook delivery logs

### Issue: Multiple Payment Records with Same payment_id

**Solution:**
- The handler now uses the latest payment record
- Check logs for warning message
- Consider running cleanup command: `python manage.py cleanup_duplicate_payments`

### Issue: payment_id Missing from Webhook

**Solution:**
- Check logs for "payment_id is missing" error
- Verify webhook payload structure
- Check if refund entity contains payment_id

## Monitoring Recommendations

1. **Set up log monitoring** to alert on ❌ error logs
2. **Monitor Payment.status changes** to REFUNDED
3. **Track webhook event_id** to prevent duplicate processing
4. **Set up alerts** for failed webhook processing

## Testing Refund Webhook

To test refund webhook processing:

1. Create a test payment
2. Initiate refund via Razorpay dashboard or API
3. Check logs for webhook receipt
4. Verify Payment.status updated to REFUNDED
5. Check raw_payload contains refund data

## Additional Resources

- Razorpay Webhook Documentation: https://razorpay.com/docs/webhooks/
- Payment Model: `core/payments/models.py`
- Webhook Handler: `core/payments/views.py` (webhook function)

