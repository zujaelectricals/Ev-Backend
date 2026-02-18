# Razorpay Payout API Fix - Contact ID Requirement

## Problem Identified

**Error Message:**
```
The contact id field is required when customer id is not present.
```

**Root Cause:**
RazorpayX API requires either a `contact_id` or `customer_id` when creating a fund account. The previous implementation was missing this required field.

## Solution Implemented

### Changes Made

1. **Updated `core/payout/utils.py`** (lines 129-178)
   - Added contact creation step before fund account creation
   - Handles duplicate contact errors gracefully
   - Falls back to finding existing contact if creation fails

2. **Updated `core/payments/views.py`** (lines 1159-1209)
   - Added same contact creation logic to manual payout endpoint
   - Proper error handling with appropriate HTTP responses

### How It Works Now

1. **Create Razorpay Contact:**
   ```python
   contact_data = {
       'name': account_holder_name,
       'email': user.email,
       'contact': user.phone or '9999999999',
       'type': 'customer',
   }
   # Note: Razorpay Python SDK doesn't have contact resource
   # So we use direct API call via client.request()
   contact_response = client.request('POST', '/v1/contacts', contact_data)
   contact_id = contact_response['id']
   ```

2. **Create Fund Account with Contact ID:**
   ```python
   fund_account_data = {
       'contact_id': contact_id,  # ✅ Now included
       'account_type': 'bank_account',
       'bank_account': {
           'name': account_holder_name,
           'ifsc': ifsc_code,
           'account_number': account_number,
       }
   }
   fund_account = client.fund_account.create(fund_account_data)
   ```

3. **Create Payout:**
   ```python
   payout_data = {
       'fund_account': {
           'id': fund_account_id,
           'account_type': 'bank_account',
       },
       'amount': amount_paise,
       # ... other fields
   }
   razorpay_payout = client.payout.create(payout_data)
   ```

### Error Handling

- **Duplicate Contact:** If contact already exists, the code tries to find existing contact by email
- **Contact Creation Failure:** Logs error and raises exception (in utils.py) or returns error response (in views.py)
- **Fund Account Creation:** Continues with existing error handling

## Testing the Fix

### Step 1: Retry Existing Payout

Since payout ID 12 is already in `"processing"` status, you can retry it:

```bash
POST /api/payments/create-payout/
Authorization: Bearer {admin_token}

{
  "payout_id": 12
}
```

**Expected Result:**
- ✅ Contact created (or found if exists)
- ✅ Fund account created with contact_id
- ✅ Razorpay payout created
- ✅ `transaction_id` populated with Razorpay payout ID (e.g., `"pout_xxxxx"`)

### Step 2: Create New Payout

Create a new payout request - it should now work automatically:

```bash
POST /api/payout/
{
  "requested_amount": 1000,
  "bank_name": "State Bank of India",
  "account_number": "1234567890",
  "ifsc_code": "SBIN0000001",
  "account_holder_name": "Test ASA User"
}
```

**Expected Flow:**
1. Payout created → Status: `"pending"` (if approval needed) or `"processing"` (if auto-process)
2. Contact created in Razorpay
3. Fund account created with contact_id
4. Razorpay payout created
5. `transaction_id` populated
6. Webhook received when Razorpay processes it

## Verification

### Check Logs

After retrying, you should see:

```
[INFO] Created Razorpay contact cont_xxxxx for user 239
[INFO] Created Razorpay payout pout_xxxxx for Payout 12, amount=80000 paise
```

### Check Payout Status

```bash
GET /api/payout/12/
```

**Expected Response:**
```json
{
  "id": 12,
  "status": "processing",
  "transaction_id": "pout_xxxxxxxxxxxxx",  // ✅ Now populated!
  ...
}
```

### Check RazorpayX Dashboard

1. Go to **RazorpayX Dashboard** → **Contacts**
   - You should see the contact created for the user

2. Go to **RazorpayX Dashboard** → **Payouts**
   - You should see the payout with status: `queued`, `processing`, or `processed`

## Important Notes

1. **Contact Reuse:** The code tries to reuse existing contacts if they already exist (based on email)
2. **Phone Number:** Uses user's phone if available, otherwise defaults to `9999999999` (for test mode)
3. **Email:** Uses user's email, or generates a placeholder email if not available
4. **Test Mode:** All of this works in test mode with test keys

## Next Steps

1. ✅ **Retry payout ID 12** using `/api/payments/create-payout/`
2. ✅ **Verify transaction_id is populated**
3. ✅ **Check RazorpayX Dashboard** for contact and payout
4. ✅ **Monitor webhooks** - they should start working once payout is created in Razorpay

## Webhook Status

Once `transaction_id` is populated:
- ✅ Razorpay will process the payout
- ✅ Webhook events will be sent:
  - `payout.queued` - When payout is queued
  - `payout.processed` - When payout completes successfully
  - `payout.failed` - If payout fails
- ✅ Your webhook handler at `/api/payout/webhook/` will receive these events
- ✅ Payout status will be updated automatically via Celery tasks

