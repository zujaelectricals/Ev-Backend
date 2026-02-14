# Razorpay Webhook Handler Documentation

## Overview

The production-safe Razorpay webhook handler (`RazorpayWebhookView`) handles both payment and payout webhook events with proper signature verification, idempotency protection, and comprehensive logging.

## Features

- **Smart Signature Verification**: Routes to appropriate webhook secret based on event type
- **Safe Payload Extraction**: Uses defensive `.get()` chains to prevent KeyError
- **Idempotency Protection**: Prevents duplicate processing using `WebhookEvent` model
- **Comprehensive Logging**: Logs all webhook attempts for audit trail
- **Production-Safe**: Returns appropriate HTTP status codes and handles errors gracefully

## Supported Events

### Payment Events
- `payment.captured`: Payment successfully captured
- `refund.processed`: Refund successfully processed

### Payout Events
- `payout.queued`: Payout queued for processing
- `payout.processed`: Payout successfully processed
- `payout.failed`: Payout failed

## Logging Configuration

### Example Django Settings

Add the following to your `settings.py` or `settings_prod.py`:

```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/webhook.log',
            'maxBytes': 1024 * 1024 * 10,  # 10 MB
            'backupCount': 5,
            'formatter': 'verbose',
        },
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
    },
    'loggers': {
        'core.payments.views': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
        'core.payments.utils.signature': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}
```

### Recommended Log Levels

- **Production**: `INFO` level - logs all webhook attempts, signature verification results, and processing status
- **Development**: `DEBUG` level - includes detailed payload dumps
- **File Rotation**: Configure rotating file handler to prevent disk space issues

## Testing the Webhook

### Generate Test Signature

```python
import hmac
import hashlib
import json

# Your webhook secret (from settings)
webhook_secret = "your_webhook_secret_here"

# Sample payload
payload = {
    "event": "payment.captured",
    "payload": {
        "payment": {
            "entity": {
                "id": "pay_TEST123",
                "order_id": "order_TEST456",
                "status": "captured",
                "amount": 50000
            }
        }
    }
}

# Convert to JSON string
body = json.dumps(payload)

# Generate signature
signature = hmac.new(
    webhook_secret.encode('utf-8'),
    body.encode('utf-8'),
    hashlib.sha256
).hexdigest()

print(f"Signature: {signature}")
```

### Example cURL Request

#### Payment Event (payment.captured)

```bash
curl -X POST http://localhost:8000/api/payments/webhook/ \
  -H "Content-Type: application/json" \
  -H "X-Razorpay-Signature: <generated_signature>" \
  -d '{
    "event": "payment.captured",
    "id": "evt_TEST123",
    "payload": {
      "payment": {
        "entity": {
          "id": "pay_TEST123",
          "order_id": "order_TEST456",
          "status": "captured",
          "amount": 50000
        }
      }
    }
  }'
```

#### Refund Event (refund.processed)

```bash
curl -X POST http://localhost:8000/api/payments/webhook/ \
  -H "Content-Type: application/json" \
  -H "X-Razorpay-Signature: <generated_signature>" \
  -d '{
    "event": "refund.processed",
    "id": "evt_TEST456",
    "payload": {
      "refund": {
        "entity": {
          "id": "rfnd_TEST789",
          "payment_id": "pay_TEST123",
          "amount": 50000,
          "status": "processed"
        }
      }
    }
  }'
```

#### Payout Event (payout.processed)

```bash
curl -X POST http://localhost:8000/api/payments/webhook/ \
  -H "Content-Type: application/json" \
  -H "X-Razorpay-Signature: <generated_signature>" \
  -d '{
    "event": "payout.processed",
    "id": "evt_TEST789",
    "payload": {
      "payout": {
        "entity": {
          "id": "pout_TEST123",
          "amount": 100000,
          "status": "processed"
        }
      }
    }
  }'
```

**Note**: Replace `<generated_signature>` with the actual signature generated using the webhook secret.

### Testing Without Event ID

The webhook handler gracefully handles missing `event_id` by generating a fallback ID:

```bash
curl -X POST http://localhost:8000/api/payments/webhook/ \
  -H "Content-Type: application/json" \
  -H "X-Razorpay-Signature: <generated_signature>" \
  -d '{
    "event": "payment.captured",
    "payload": {
      "payment": {
        "entity": {
          "id": "pay_TEST123",
          "order_id": "order_TEST456"
        }
      }
    }
  }'
```

## Response Codes

- **200 OK**: Webhook processed successfully (or already processed - idempotent)
- **400 Bad Request**: 
  - Missing signature header
  - Invalid signature
  - Invalid JSON
  - Missing event type
  - Missing critical data (payment_id, payout_id, etc.)

## Idempotency

The webhook handler uses the `WebhookEvent` model to ensure idempotency:

1. If `event_id` exists in payload, it's used as the unique identifier
2. If `event_id` is missing, a fallback ID is generated from payload hash
3. If event already exists and is marked as `processed=True`, returns 200 immediately
4. If event exists but not processed, attempts to process again

## Security Notes

1. **Signature Verification**: Always verify webhook signature before processing
2. **Constant-Time Comparison**: Uses `hmac.compare_digest()` to prevent timing attacks
3. **Defensive Coding**: Never assumes payload structure - uses `.get()` chains
4. **Audit Trail**: All webhook attempts are logged for security auditing
5. **Error Handling**: Returns 200 for processed duplicates to prevent retries

## Environment Variables

Ensure these are set in your environment:

```bash
# Payment webhook secret (for payment.* and refund.* events)
RAZORPAY_WEBHOOK_SECRET=your_payment_webhook_secret

# Payout webhook secret (for payout.* events)
RAZORPAY_PAYOUT_WEBHOOK_SECRET=your_payout_webhook_secret
```

## Monitoring

Monitor webhook logs for:
- Invalid signatures (potential security issues)
- Missing event IDs (may indicate Razorpay API changes)
- Processing errors (check `error_message` in `WebhookEvent` model)
- Duplicate events (verify idempotency is working)

## Troubleshooting

### Webhook returns 400 "Invalid signature"
- Verify webhook secret is correct in settings
- Ensure raw request body is used for signature verification
- Check that signature header is `X-Razorpay-Signature`

### Event not being processed
- Check `WebhookEvent` model for error messages
- Verify event type is supported
- Check logs for detailed error information

### Duplicate processing
- Verify `WebhookEvent` model is being used correctly
- Check that `event_id` is being extracted properly
- Review transaction atomicity in webhook handler

