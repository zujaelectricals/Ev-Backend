# Payout Diagnostic Guide

## Current Status Analysis

Based on your payout response:
```json
{
  "id": 12,
  "status": "processing",
  "transaction_id": null,  // ❌ This should have a Razorpay payout ID (pout_xxxxx)
  "processed_at": "2026-02-18T09:54:42.655321+05:30"
}
```

### ❌ Problem Identified

**The Razorpay payout API was NOT successfully called.**

**Why?**
- If Razorpay API was successful, `transaction_id` would be populated with a Razorpay payout ID (starting with `pout_`)
- Since it's `null`, the API call either:
  1. Failed silently (error was caught and logged)
  2. Wasn't triggered due to missing configuration
  3. Encountered an exception

## Step 1: Check Django Logs

The application logs all Razorpay API errors. Check your Django logs for:

```bash
# Look for these log messages:

# If Razorpay client initialization failed:
"Error initializing Razorpay payout for Payout 12: ..."

# If Razorpay API call failed:
"Razorpay API error creating payout for Payout 12: ..."
```

**Where to check logs:**
- Django console output (if running `python manage.py runserver`)
- Log files (if configured in `settings.py`)
- Docker logs (if running in Docker)

## Step 2: Verify Razorpay Configuration

Check if Razorpay keys are properly configured:

```bash
# Check environment variables
python manage.py shell
```

```python
from django.conf import settings

# Check if keys are set
print("RAZORPAY_KEY_ID:", settings.RAZORPAY_KEY_ID)
print("RAZORPAY_KEY_SECRET:", "***" if settings.RAZORPAY_KEY_SECRET else "NOT SET")

# Test Razorpay client initialization
try:
    from core.payments.utils.razorpay_client import get_razorpay_client
    client = get_razorpay_client()
    print("✅ Razorpay client initialized successfully")
except Exception as e:
    print(f"❌ Razorpay client initialization failed: {e}")
```

## Step 3: Manual Retry via API

Since the payout status is `"processing"` but `transaction_id` is `null`, you can manually trigger the Razorpay API call:

```bash
POST /api/payments/create-payout/
Authorization: Bearer {admin_token}

{
  "payout_id": 12
}
```

**Expected Response (Success):**
```json
{
  "payout_id": 12,
  "transaction_id": "pout_xxxxxxxxxxxxx",
  "status": "processing",
  "message": "Payout created successfully"
}
```

**Expected Response (Error):**
```json
{
  "error": "Failed to create payout: [error message]"
}
```

## Step 4: Check Common Issues

### Issue 1: Missing Razorpay Keys

**Symptom:** `transaction_id` is null, no error in logs

**Solution:**
1. Verify `.env` file has:
   ```bash
   RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxx
   RAZORPAY_KEY_SECRET=your_test_key_secret
   ```
2. Restart Django server after updating `.env`

### Issue 2: Invalid Test Keys

**Symptom:** Error like "Invalid API key" or "Authentication failed"

**Solution:**
1. Verify keys start with `rzp_test_` (for test mode)
2. Ensure Razorpay Dashboard is in **Test Mode**
3. Regenerate keys if needed

### Issue 3: Missing RAZORPAY_ACCOUNT_NUMBER

**Symptom:** Payout creation fails with account number error

**Solution:**
1. Get RazorpayX account number from Dashboard → Settings → Account Details
2. Add to `.env`:
   ```bash
   RAZORPAY_ACCOUNT_NUMBER=your_razorpayx_account_number
   ```
3. Note: This might be optional in test mode, but some configurations require it

### Issue 4: Fund Account Creation Failed

**Symptom:** Error creating fund account

**Solution:**
1. Verify bank account details format:
   - IFSC: 11 characters (e.g., `SBIN0000001`)
   - Account number: Valid format
   - Account holder name: Matches bank records
2. In test mode, fund accounts may need to be verified first

### Issue 5: Network/Connection Issues

**Symptom:** Timeout or connection errors

**Solution:**
1. Check internet connectivity
2. Verify Razorpay API is accessible
3. Check firewall/proxy settings

## Step 5: Check Webhook Status

### Current Webhook Status: ❌ Not Applicable

**Why?**
- Webhooks are triggered by Razorpay when payout status changes
- Since `transaction_id` is `null`, the payout was never created in Razorpay
- Therefore, **no webhook will be received** until the payout is successfully created

### After Fixing the Issue

Once `transaction_id` is populated, webhooks will work:

1. **Webhook Events to Expect:**
   - `payout.queued` - Payout queued for processing
   - `payout.processed` - Payout completed successfully
   - `payout.failed` - Payout failed

2. **Check Webhook Logs:**
   ```python
   # In Django shell
   from core.payout.models import PayoutWebhookLog
   
   # Check recent webhook events
   PayoutWebhookLog.objects.all().order_by('-created_at')[:10]
   ```

3. **Webhook Endpoint:**
   - URL: `/api/payout/webhook/`
   - Method: POST
   - Headers: `X-Razorpay-Signature` (for verification)

## Step 6: Complete Diagnostic Script

Run this complete diagnostic:

```python
# python manage.py shell

from core.payout.models import Payout
from django.conf import settings
from core.payments.utils.razorpay_client import get_razorpay_client

# 1. Check payout
payout = Payout.objects.get(id=12)
print(f"Payout ID: {payout.id}")
print(f"Status: {payout.status}")
print(f"Transaction ID: {payout.transaction_id}")
print(f"Net Amount: ₹{payout.net_amount}")

# 2. Check Razorpay config
print("\n=== Razorpay Configuration ===")
print(f"Key ID: {settings.RAZORPAY_KEY_ID}")
print(f"Key Secret: {'***SET***' if settings.RAZORPAY_KEY_SECRET else 'NOT SET'}")
print(f"Account Number: {getattr(settings, 'RAZORPAY_ACCOUNT_NUMBER', 'NOT SET')}")

# 3. Test Razorpay client
print("\n=== Testing Razorpay Client ===")
try:
    client = get_razorpay_client()
    print("✅ Client initialized")
    
    # Test API connectivity (optional)
    # account = client.account.fetch()
    # print(f"✅ API connection successful: {account.get('id', 'N/A')}")
except Exception as e:
    print(f"❌ Client initialization failed: {e}")

# 4. Check bank details
print("\n=== Bank Details ===")
print(f"Account Number: {payout.account_number}")
print(f"IFSC: {payout.ifsc_code}")
print(f"Account Holder: {payout.account_holder_name}")
print(f"Bank Name: {payout.bank_name}")

# 5. Check webhook logs
print("\n=== Webhook Logs ===")
from core.payout.models import PayoutWebhookLog
webhooks = PayoutWebhookLog.objects.filter(
    payload__icontains=str(payout.id)
).order_by('-created_at')[:5]
if webhooks:
    for wh in webhooks:
        print(f"Event: {wh.event_type}, Status: {wh.status}, ID: {wh.event_id}")
else:
    print("No webhook events found for this payout")
```

## Quick Fix: Retry Payout Creation

If everything is configured correctly, simply retry:

```bash
# As admin user
POST /api/payments/create-payout/
Authorization: Bearer {admin_access_token}

{
  "payout_id": 12
}
```

This will:
1. Verify payout status is `"processing"`
2. Create Razorpay fund account
3. Create Razorpay payout
4. Update `transaction_id` with Razorpay payout ID
5. Return success response

## Expected Flow After Fix

1. ✅ Payout created → Status: `"processing"`
2. ✅ Razorpay API called → `transaction_id` populated: `"pout_xxxxx"`
3. ✅ Razorpay processes payout → Status in Razorpay: `queued` → `processing` → `processed`
4. ✅ Webhook received → Status updated to `"completed"` in your app
5. ✅ `completed_at` timestamp set

## Summary

**Current State:**
- ✅ Payout created and processed (wallet deducted)
- ❌ Razorpay API not called (transaction_id is null)
- ❌ No webhook received (payout not in Razorpay)

**Next Steps:**
1. Check Django logs for errors
2. Verify Razorpay configuration
3. Retry via `/api/payments/create-payout/` endpoint
4. Monitor webhooks after successful Razorpay payout creation

