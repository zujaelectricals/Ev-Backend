# Step-by-Step Guide: Testing Payout with Your Bank Details

## Your Test Bank Details (from RazorpayX):
- **Name**: Test ASA User
- **Account Number**: 1234567890
- **IFSC**: SBIN0000001
- **Bank Name**: State Bank of India (based on IFSC)

## Step-by-Step Testing Process

### Step 1: Create/Login as a User in Your Application

You need a user account in your application. You can either:
- **Create a new user** via registration endpoint
- **Use an existing user** if you have one

**Example: Create user via API**
```bash
POST /api/auth/register/
{
  "email": "testuser@example.com",
  "password": "TestPassword123!",
  "username": "testuser"
}
```

### Step 2: Ensure User Has Approved KYC

The payout requires **approved KYC**. You need to:

1. **Create/Update KYC for the user**:
   ```bash
   POST /api/kyc/
   {
     "pan_number": "ABCDE1234F",
     "aadhar_number": "123456789012",
     "bank_name": "State Bank of India",
     "account_number": "1234567890",
     "ifsc_code": "SBIN0000001",
     "account_holder_name": "Test ASA User"
   }
   ```

2. **Approve the KYC** (as admin):
   ```bash
   PATCH /api/kyc/{kyc_id}/
   {
     "status": "approved"
   }
   ```

   OR via Django admin panel → KYC → Approve

### Step 3: Ensure User Has Wallet Balance

The user needs sufficient wallet balance for the payout:

```bash
# Option 1: Add balance via admin panel
# Django Admin → Wallet → Add balance

# Option 2: Create a wallet transaction (if you have an endpoint)
# Or manually update via Django shell:
python manage.py shell
```

```python
from core.users.models import User
from core.wallet.utils import get_or_create_wallet

user = User.objects.get(email="testuser@example.com")
wallet = get_or_create_wallet(user)
wallet.balance = 10000  # Add ₹10,000 for testing
wallet.save()
```

### Step 4: Create Payout Request

Now create the payout using **the same bank details** you added in RazorpayX:

```bash
POST /api/payout/
Authorization: Bearer {user_access_token}

{
  "requested_amount": 1000,
  "bank_name": "State Bank of India",
  "account_number": "1234567890",
  "ifsc_code": "SBIN0000001",
  "account_holder_name": "Test ASA User",
  "reason": "Testing payout with RazorpayX"
}
```

**Important**: Use the **exact same bank details** you added in RazorpayX:
- ✅ Account Number: `1234567890`
- ✅ IFSC: `SBIN0000001`
- ✅ Account Holder Name: `Test ASA User`
- ✅ Bank Name: `State Bank of India` (or match the bank name from IFSC)

### Step 5: Process the Payout

#### Option A: Auto-Processing (if `payout_approval_needed = false`)

If auto-processing is enabled, the payout will automatically:
- Deduct from wallet
- Call Razorpay API
- Status becomes `"processing"`

#### Option B: Manual Approval (if `payout_approval_needed = true`)

1. **Check payout status** (should be `"pending"`):
   ```bash
   GET /api/payout/{payout_id}/
   ```

2. **Admin approves the payout**:
   ```bash
   POST /api/payout/{payout_id}/process/
   Authorization: Bearer {admin_access_token}
   ```

3. **Expected Response**:
   ```json
   {
     "message": "Payout processed successfully. Amount deducted from wallet.",
     "payout": {
       "id": 1,
       "status": "processing",
       "transaction_id": "pout_xxxxxxxxxxxxx",
       ...
     }
   }
   ```

### Step 6: Verify in RazorpayX Dashboard

1. Go to **RazorpayX Dashboard** → **Payouts**
2. You should see a payout with:
   - **Beneficiary**: Test ASA User
   - **Account**: 1234567890
   - **IFSC**: SBIN0000001
   - **Status**: `queued`, `processing`, or `processed`

### Step 7: Check Application Logs

Look for successful Razorpay API calls:

```
INFO: Created Razorpay payout pout_xxxxx for Payout {id}, amount=100000 paise
```

## Quick Test Script

Here's a complete test flow you can follow:

```bash
# 1. Login as user
POST /api/auth/login/
{
  "email": "testuser@example.com",
  "password": "TestPassword123!"
}
# Save the access_token

# 2. Check wallet balance
GET /api/wallet/
Authorization: Bearer {access_token}

# 3. Create payout
POST /api/payout/
Authorization: Bearer {access_token}
{
  "requested_amount": 1000,
  "bank_name": "State Bank of India",
  "account_number": "1234567890",
  "ifsc_code": "SBIN0000001",
  "account_holder_name": "Test ASA User"
}

# 4. If payout_approval_needed = true, approve as admin
POST /api/payout/{payout_id}/process/
Authorization: Bearer {admin_token}

# 5. Check payout status
GET /api/payout/{payout_id}/
Authorization: Bearer {access_token}
```

## Important Notes

1. **Bank Details Must Match**: The bank details in your payout request should match what you added in RazorpayX for successful processing.

2. **Test Mode**: Ensure you're using **test keys** (starting with `rzp_test_`) and Razorpay Dashboard is in **Test Mode**.

3. **No Real Money**: In test mode, no actual money is transferred. The payout is simulated.

4. **IFSC Validation**: The IFSC code `SBIN0000001` corresponds to State Bank of India. Make sure the bank name matches.

5. **KYC Requirement**: User must have **approved KYC** before creating payout.

6. **Wallet Balance**: User must have sufficient wallet balance (≥ requested_amount).

## Troubleshooting

**Error: "User must have approved KYC"**
- Solution: Approve the user's KYC first

**Error: "Insufficient wallet balance"**
- Solution: Add balance to user's wallet

**Error: "Fund account creation failed"**
- Solution: Verify IFSC code format and bank account number format

**Payout status stuck at "processing"**
- Check RazorpayX Dashboard for payout status
- Check application logs for Razorpay API errors
- Verify test keys are correctly configured

## Success Indicators

✅ Payout created successfully  
✅ Status changed to `"processing"`  
✅ `transaction_id` field populated (starts with `pout_`)  
✅ Wallet balance deducted  
✅ Payout visible in RazorpayX Dashboard  
✅ Logs show successful Razorpay API call  

