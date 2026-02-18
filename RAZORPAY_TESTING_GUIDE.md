# Testing Razorpay Payouts with Test Keys

This guide explains how to test Razorpay payout functionality using test keys and secrets.

## Step 1: Get Test Keys from Razorpay Dashboard

1. **Login to Razorpay Dashboard**: https://dashboard.razorpay.com
2. **Switch to Test Mode**: 
   - Click on the mode toggle (top right) to switch to **Test Mode**
   - The dashboard will show "Test Mode" indicator
3. **Get API Keys**:
   - Go to **Settings** → **API Keys** (or directly: https://dashboard.razorpay.com/app/keys)
   - You'll see:
     - **Key ID**: Starts with `rzp_test_...`
     - **Key Secret**: Click "Reveal" to see the secret
4. **Get Webhook Secrets** (for testing webhooks):
   - Go to **Settings** → **Webhooks**
   - Create webhooks for:
     - **Payment Events**: `payment.captured`, `refund.processed`
     - **Payout Events**: `payout.processed`, `payout.failed`, `payout.queued`
   - Copy the webhook secret for each webhook

## Step 2: Configure Test Keys in Your Environment

### Option A: Update `.env` file

Add your test keys to your `.env` file:

```bash
# Razorpay Configuration (Test Mode)
RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxx
RAZORPAY_KEY_SECRET=your_test_key_secret_here
RAZORPAY_WEBHOOK_SECRET=your_payment_webhook_secret_here
RAZORPAY_PAYOUT_WEBHOOK_SECRET=your_payout_webhook_secret_here

# Optional: RazorpayX Account Number (if required for payouts)
# Get this from RazorpayX Dashboard → Settings → Account Details
RAZORPAY_ACCOUNT_NUMBER=your_razorpayx_account_number
```

### Option B: Set Environment Variables

**Windows (CMD):**
```cmd
set RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxx
set RAZORPAY_KEY_SECRET=your_test_key_secret_here
set RAZORPAY_WEBHOOK_SECRET=your_payment_webhook_secret_here
set RAZORPAY_PAYOUT_WEBHOOK_SECRET=your_payout_webhook_secret_here
```

**Windows (PowerShell):**
```powershell
$env:RAZORPAY_KEY_ID="rzp_test_xxxxxxxxxxxxx"
$env:RAZORPAY_KEY_SECRET="your_test_key_secret_here"
$env:RAZORPAY_WEBHOOK_SECRET="your_payment_webhook_secret_here"
$env:RAZORPAY_PAYOUT_WEBHOOK_SECRET="your_payout_webhook_secret_here"
```

**Linux/Mac:**
```bash
export RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxx
export RAZORPAY_KEY_SECRET=your_test_key_secret_here
export RAZORPAY_WEBHOOK_SECRET=your_payment_webhook_secret_here
export RAZORPAY_PAYOUT_WEBHOOK_SECRET=your_payout_webhook_secret_here
```

## Step 3: Restart Your Django Server

After updating environment variables, restart your Django development server:

```bash
python manage.py runserver
```

## Step 4: Test Payout Flow

### Test Case 1: Auto-Processing (payout_approval_needed = false)

1. **Set payout approval to false**:
   ```bash
   # Via Django shell or admin panel
   python manage.py shell
   ```
   ```python
   from core.settings.models import PlatformSettings
   settings = PlatformSettings.get_settings()
   settings.payout_approval_needed = False
   settings.save()
   ```

2. **Create a payout request**:
   ```bash
   POST /api/payout/
   {
     "requested_amount": 1000,
     "bank_name": "State Bank of India",
     "account_number": "1234567890",
     "ifsc_code": "SBIN0001234",
     "account_holder_name": "Test User"
   }
   ```

3. **Expected Behavior**:
   - Payout status immediately becomes `"processing"`
   - Wallet balance is deducted
   - Razorpay payout API is called automatically
   - `transaction_id` field is populated with Razorpay payout ID (starts with `pout_`)

### Test Case 2: Manual Approval (payout_approval_needed = true)

1. **Set payout approval to true**:
   ```python
   settings.payout_approval_needed = True
   settings.save()
   ```

2. **Create a payout request**:
   - Same as Test Case 1
   - Status will be `"pending"`

3. **Admin approves payout**:
   ```bash
   POST /api/payout/{id}/process/
   ```

4. **Expected Behavior**:
   - Status changes to `"processing"`
   - Wallet balance is deducted
   - Razorpay payout API is called automatically
   - `transaction_id` field is populated with Razorpay payout ID

## Step 5: Verify Razorpay API Calls

### Check Logs

The application logs all Razorpay API calls. Look for:

```
INFO: Created Razorpay payout pout_xxxxx for Payout {id}, amount=100000 paise (auto-processed)
```

### Check Razorpay Dashboard

1. Go to **RazorpayX Dashboard** → **Payouts**
2. You should see test payouts with status:
   - `queued`: Payout is queued
   - `processing`: Payout is being processed
   - `processed`: Payout completed successfully
   - `failed`: Payout failed (check failure reason)

## Step 6: Test Webhooks (Optional but Recommended)

### Setup Webhook URL

1. In Razorpay Dashboard → **Settings** → **Webhooks**
2. Add webhook URL: `https://your-domain.com/api/payout/webhook/`
   - For local testing, use tools like:
     - **ngrok**: `ngrok http 8000` → Use the ngrok URL
     - **localtunnel**: `lt --port 8000`
3. Select events:
   - `payout.processed`
   - `payout.failed`
   - `payout.queued`

### Test Webhook Locally

1. **Start ngrok**:
   ```bash
   ngrok http 8000
   ```

2. **Update webhook URL in Razorpay Dashboard**:
   ```
   https://your-ngrok-url.ngrok.io/api/payout/webhook/
   ```

3. **Trigger a payout** and watch webhook events in:
   - Razorpay Dashboard → **Webhooks** → **Events**
   - Your Django logs

## Important Notes for Test Mode

### 1. Test Bank Accounts

RazorpayX payouts in test mode work with:
- **Any valid bank account details** (IFSC, account number format must be valid)
- **No actual money is transferred** in test mode
- Payouts are simulated

### 2. Test Account Number

If your code uses `RAZORPAY_ACCOUNT_NUMBER`:
- Get it from **RazorpayX Dashboard** → **Settings** → **Account Details**
- In test mode, this is your test RazorpayX account number
- If not set, the payout may still work but check Razorpay documentation

### 3. Test Mode Limitations

- No real money transfers
- Webhooks are triggered but with test data
- Some features may behave differently than production
- Test payouts may process faster than production

### 4. Common Test Mode Issues

**Issue**: "Invalid API key"
- **Solution**: Ensure you're using test keys (starting with `rzp_test_`) and dashboard is in Test Mode

**Issue**: "Fund account creation failed"
- **Solution**: Verify bank account details format (IFSC, account number)

**Issue**: "Payout failed"
- **Solution**: Check RazorpayX Dashboard for failure reason. In test mode, some validations may still apply.

**Issue**: "Webhook not received"
- **Solution**: 
  - Verify webhook URL is accessible (use ngrok for local testing)
  - Check webhook secret matches
  - Verify webhook events are enabled in dashboard

## Verification Checklist

- [ ] Test keys configured in `.env` (starting with `rzp_test_`)
- [ ] Django server restarted after environment changes
- [ ] Razorpay Dashboard is in **Test Mode**
- [ ] Created payout request successfully
- [ ] Payout status changed to `"processing"`
- [ ] Razorpay payout ID stored in `transaction_id` field
- [ ] Checked RazorpayX Dashboard for payout status
- [ ] Webhooks configured (if testing webhook flow)
- [ ] Logs show successful Razorpay API calls

## Switching to Production

When ready for production:

1. **Switch Razorpay Dashboard to Live Mode**
2. **Get Live API Keys** from dashboard
3. **Update environment variables** with live keys:
   ```bash
   RAZORPAY_KEY_ID=rzp_live_xxxxxxxxxxxxx
   RAZORPAY_KEY_SECRET=your_live_key_secret_here
   ```
4. **Update webhook secrets** for production webhooks
5. **Test with small amounts first** before processing large payouts

## Additional Resources

- [RazorpayX Payouts API Documentation](https://razorpay.com/docs/api/x/payouts/)
- [Razorpay Test Mode Guide](https://razorpay.com/docs/payments/test-mode/)
- [RazorpayX Dashboard](https://dashboard.razorpay.com/app/x/payouts)

