# EV Distribution Platform - Complete Project Documentation

## Table of Contents
1. [Project Overview](#project-overview)
2. [Folder Structure & Implementation](#folder-structure--implementation)
3. [Workflow Documentation](#workflow-documentation)
4. [Project Logic, Routing & Flow](#project-logic-routing--flow)
5. [Database Models & Relationships](#database-models--relationships)
6. [API Endpoints & Routing](#api-endpoints--routing)
7. [Business Rules & Logic](#business-rules--logic)
8. [Background Tasks & Celery](#background-tasks--celery)
9. [Deployment Architecture](#deployment-architecture)

---

## Project Overview

The **EV Distribution Platform** is a Django-based monolithic backend system designed for an Electric Vehicle distribution business with integrated MLM (Multi-Level Marketing) features. The platform manages:

- **User Management**: Registration, authentication, KYC, and nominee management
- **Inventory Management**: EV vehicle catalog with images, features, and specifications
- **Booking System**: EV bookings with payment tracking and EMI options
- **Wallet System**: Single wallet ledger with multiple transaction types
- **Binary Tree MLM**: Left/Right binary tree structure with automatic pair matching
- **Payout System**: Withdrawal requests with TDS calculation and EMI auto-fill
- **Compliance**: Document management and TDS record keeping
- **Notifications**: User notification system
- **Reports**: Dashboard and analytics

### Technology Stack

- **Framework**: Django 4.2.7 + Django REST Framework 3.14.0
- **Authentication**: JWT (JSON Web Tokens) with OTP verification
- **Database**: SQLite (dev) / MySQL 8.0 (production)
- **Cache/OTP Storage**: Redis 7
- **Task Queue**: Celery 5.3.4 + RabbitMQ
- **Web Server**: Gunicorn + Nginx
- **Containerization**: Docker + Docker Compose

---

## Folder Structure & Implementation

### Root Directory Structure

```
EV/
├── core/                          # Main application modules
│   ├── auth/                      # Authentication module
│   ├── users/                     # User management module
│   ├── inventory/                 # Vehicle inventory module
│   ├── booking/                   # Booking & payment module
│   ├── wallet/                    # Wallet & transactions module
│   ├── binary/                    # Binary tree MLM module
│   ├── payout/                    # Payout requests module
│   ├── notification/              # Notification module
│   ├── compliance/                # Compliance & TDS module
│   └── reports/                   # Reports & analytics module
├── ev_backend/                    # Django project settings
│   ├── settings.py                # Main configuration
│   ├── urls.py                    # Root URL configuration
│   ├── wsgi.py                    # WSGI configuration
│   ├── asgi.py                    # ASGI configuration
│   └── celery.py                  # Celery configuration
├── nginx/                         # Nginx configuration
│   ├── nginx.conf                 # Main Nginx config
│   └── conf.d/
│       └── default.conf           # Site-specific config
├── media/                         # User-uploaded files
├── staticfiles/                   # Collected static files
├── manage.py                      # Django management script
├── requirements.txt               # Python dependencies
├── Dockerfile                     # Docker image definition
├── docker-compose.yml             # Multi-container orchestration
├── README.md                      # Quick start guide
├── ARCHITECTURE.md                # Architecture overview
└── PROJECT_DOCUMENTATION.md       # This file
```

### Module Structure (Each Core Module)

Each module in `core/` follows a consistent structure:

```
module_name/
├── __init__.py                    # Module initialization
├── models.py                      # Database models
├── serializers.py                 # DRF serializers
├── views.py                       # API views/viewsets
├── urls.py                        # URL routing
├── admin.py                       # Django admin configuration
├── apps.py                        # App configuration
├── tasks.py                       # Celery tasks (if applicable)
├── utils.py                       # Utility functions (if applicable)
└── migrations/                    # Database migrations
    └── __init__.py
```

### Detailed Module Implementation

#### 1. Authentication Module (`core/auth/`)

**Purpose**: Handle user authentication via OTP (Email/Mobile)

**Key Files**:
- `models.py`: No models (uses User model from users app)
- `views.py`: OTP generation, verification, JWT token generation
- `utils.py`: OTP generation, Redis storage, email/SMS sending
- `urls.py`: Authentication endpoints

**Implementation Details**:
- OTP stored in Redis with 10-minute expiry
- JWT access tokens (60 min) and refresh tokens (24 hours)
- Referral code handling during signup
- Support for email and mobile OTP

#### 2. Users Module (`core/users/`)

**Purpose**: User management, profiles, KYC, and nominee information

**Key Models**:
- `User`: Custom user model with roles, distributor flag, Active Buyer status
- `KYC`: Know Your Customer documents and verification
- `Nominee`: Nominee information with KYC verification

**Key Features**:
- Custom user manager for email/mobile authentication
- Role-based access (admin, staff, user)
- Active Buyer status auto-update (when total paid ≥ ₹5000)
- Referral code generation and tracking
- KYC document upload and verification workflow
- Nominee management with KYC verification

#### 3. Inventory Module (`core/inventory/`)

**Purpose**: EV vehicle catalog management

**Key Models**:
- `Vehicle`: Vehicle details with JSON fields for features and specifications
- `VehicleImage`: Multiple images per vehicle with primary image support

**Key Features**:
- Flexible features list (JSON array)
- Flexible specifications dictionary (JSON object)
- Multiple images per vehicle
- Primary image designation
- Image ordering support

#### 4. Booking Module (`core/booking/`)

**Purpose**: EV booking and payment management

**Key Models**:
- `Booking`: Booking records with status tracking
- `Payment`: Payment transaction records

**Key Features**:
- Unique booking number generation (EV + 8 alphanumeric)
- Payment option: Full payment or EMI
- Status tracking: pending → active → completed
- Active Buyer status update on payment
- Automatic expiry (30 days)
- Referral tracking
- EMI tracking (amount, duration, paid count)

**Business Rules**:
- Minimum pre-booking: ₹500
- Active Buyer threshold: ₹5000 total paid

#### 5. Wallet Module (`core/wallet/`)

**Purpose**: Single wallet ledger system

**Key Models**:
- `Wallet`: User wallet with balance tracking
- `WalletTransaction`: Complete transaction ledger

**Transaction Types**:
- `REFERRAL_BONUS`: Referral earnings
- `BINARY_PAIR`: Binary pair matching earnings
- `EMI_DEDUCTION`: Automatic EMI deductions
- `RESERVE_DEDUCTION`: Reserve fund deductions
- `PAYOUT`: Withdrawal transactions
- `DEPOSIT`: Manual deposits
- `REFUND`: Refund transactions

**Key Utilities** (`utils.py`):
- `get_or_create_wallet()`: Get or create wallet
- `add_wallet_balance()`: Add balance with business rules
- `deduct_wallet_balance()`: Deduct balance with validation

**Business Rules** (implemented in `add_wallet_balance()`):
- First 5 binary pair earnings: Full credit (even without Active Buyer)
- From 6th pair: 20% deducted to EMI if not Active Buyer
- Active Buyers: Full earnings from all pairs

#### 6. Binary Module (`core/binary/`)

**Purpose**: Binary tree structure and pair matching for MLM

**Key Models**:
- `BinaryNode`: Binary tree node (left/right structure)
- `BinaryPair`: Matched pair records
- `BinaryEarning`: Earnings from pairs

**Key Utilities** (`utils.py`):
- `create_binary_node()`: Create binary node for user
- `add_to_binary_tree()`: Add user to binary tree
- `find_next_available_position()`: Level-order tree insertion
- `check_and_create_pair()`: Check and create binary pairs

**Features**:
- Left/Right binary tree structure
- Level-order insertion (balanced tree)
- Automatic pair matching
- Monthly limit: 10 pairs per user
- Pair counting and tracking
- Automatic wallet credit via Celery

#### 7. Payout Module (`core/payout/`)

**Purpose**: Payout requests and financial compliance

**Key Models**:
- `Payout`: Payout requests with TDS calculation
- `PayoutTransaction`: Payout transaction records

**Key Features**:
- TDS calculation: 5% with ₹10,000 ceiling
- EMI auto-fill option
- Bank transfer integration ready
- Admin approval workflow
- Status tracking: pending → processing → completed

**Business Rules**:
- TDS: 5% of requested amount (max ₹10,000)
- Net amount = Requested amount - TDS

#### 8. Notification Module (`core/notification/`)

**Purpose**: User notifications

**Key Models**:
- `Notification`: User notifications with read/unread tracking

**Features**:
- Multiple notification types
- Read/unread status
- Reference to related objects (booking, payout, etc.)

#### 9. Compliance Module (`core/compliance/`)

**Purpose**: Legal and tax compliance

**Key Models**:
- `ComplianceDocument`: Document storage
- `TDSRecord`: TDS records for tax compliance

**Features**:
- Document upload and verification
- TDS certificate generation
- Financial year tracking

#### 10. Reports Module (`core/reports/`)

**Purpose**: Analytics and reporting

**Endpoints**:
- Dashboard statistics
- Sales reports (admin)
- User activity reports
- Wallet transaction reports

---

## Workflow Documentation

### 1. User Registration & Authentication Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    User Registration Flow                    │
└─────────────────────────────────────────────────────────────┘

1. User requests OTP
   POST /api/auth/send-otp/
   {
     "identifier": "user@example.com",
     "otp_type": "email"
   }
   ↓
   [OTP generated & stored in Redis (10 min expiry)]
   ↓
   [Email/SMS sent to user]

2. User verifies OTP
   POST /api/auth/verify-otp/
   {
     "identifier": "user@example.com",
     "otp_code": "123456",
     "otp_type": "email",
     "referral_code": "REF12345"  # Optional
   }
   ↓
   [OTP validated from Redis]
   ↓
   [User created/authenticated]
   ↓
   [Referral relationship established (if code provided)]
   ↓
   [JWT tokens generated]
   ↓
   [Response: access_token, refresh_token, user data]

3. User uses JWT token for authenticated requests
   Authorization: Bearer <access_token>
```

### 2. Booking & Payment Flow

```
┌─────────────────────────────────────────────────────────────┐
│                  Booking & Payment Flow                      │
└─────────────────────────────────────────────────────────────┘

1. User creates booking
   POST /api/booking/bookings/
   {
     "vehicle_model": 1,
     "booking_amount": 500,
     "payment_option": "emi_options",
     ...
   }
   ↓
   [Booking created with status='pending']
   ↓
   [Booking number generated: EVXXXXXXXX]
   ↓
   [Expiry set: 30 days from now]

2. User makes payment
   POST /api/booking/bookings/{id}/make_payment/
   {
     "amount": 500,
     "payment_method": "online"
   }
   ↓
   [Payment record created]
   ↓
   [Booking.total_paid updated]
   ↓
   [Booking.remaining_amount calculated]
   ↓
   [If total_paid >= 5000: status='active', confirmed_at set]
   ↓
   [If remaining_amount <= 0: status='completed', completed_at set]
   ↓
   [User.is_active_buyer updated]
   ↓
   [Celery task: payment_completed triggered]
   ↓
   [Referral bonus credited (if applicable)]

3. Payment Processing (Celery Task)
   payment_completed(booking_id, amount)
   ↓
   [Check if user was referred]
   ↓
   [Calculate referral bonus (5% of amount)]
   ↓
   [Credit referrer's wallet]
   ↓
   [Create REFERRAL_BONUS transaction]
```

### 3. Binary Tree & Pair Matching Flow

```
┌─────────────────────────────────────────────────────────────┐
│            Binary Tree & Pair Matching Flow                  │
└─────────────────────────────────────────────────────────────┘

1. User added to binary tree
   [When user registers with referral code]
   ↓
   [BinaryNode created for referrer (if not exists)]
   ↓
   [BinaryNode created for new user]
   ↓
   [Tree position determined: left or right]
   ↓
   [Level-order insertion if side is full]
   ↓
   [Parent's left_count or right_count updated]

2. Pair matching check
   POST /api/binary/pairs/check_pairs/
   ↓
   [Check user's BinaryNode]
   ↓
   [Verify: left_count > 0 AND right_count > 0]
   ↓
   [Check monthly limit: pairs_this_month < 10]
   ↓
   [Get one left user and one right user]
   ↓
   [Create BinaryPair record]
   ↓
   [Create BinaryEarning record]
   ↓
   [Update node counts (decrement left_count, right_count)]
   ↓
   [Celery task: pair_matched triggered]

3. Pair Processing (Celery Task)
   pair_matched(pair_id)
   ↓
   [Get BinaryPair]
   ↓
   [Count previous pairs for user]
   ↓
   [Call add_wallet_balance() with business rules]
   ↓
   [Business rules applied in wallet utils]
   ↓
   [Wallet credited (with EMI deduction if applicable)]
   ↓
   [BinaryPair status='processed']
```

### 4. Wallet Transaction Flow

```
┌─────────────────────────────────────────────────────────────┐
│              Wallet Transaction Flow                         │
└─────────────────────────────────────────────────────────────┘

Credit Transaction (add_wallet_balance):
   ↓
   [Get or create wallet]
   ↓
   [For BINARY_PAIR transactions:]
   ↓
   [Count previous BINARY_PAIR transactions]
   ↓
   [If previous_pairs < 5: Full amount credited]
   ↓
   [If previous_pairs >= 5 AND not Active Buyer:]
   ↓
   [Calculate 20% EMI deduction]
   ↓
   [Create EMI_DEDUCTION transaction]
   ↓
   [Credit remaining 80%]
   ↓
   [If Active Buyer: Full amount credited]
   ↓
   [Update wallet.balance]
   ↓
   [Update wallet.total_earned (for earnings)]
   ↓
   [Create WalletTransaction record]

Debit Transaction (deduct_wallet_balance):
   ↓
   [Get wallet]
   ↓
   [Validate: balance >= amount]
   ↓
   [Deduct from wallet.balance]
   ↓
   [Update wallet.total_withdrawn (for PAYOUT)]
   ↓
   [Create WalletTransaction record]
```

### 5. Payout Request Flow

```
┌─────────────────────────────────────────────────────────────┐
│                  Payout Request Flow                         │
└─────────────────────────────────────────────────────────────┘

1. User requests payout
   POST /api/payout/
   {
     "requested_amount": 10000,
     "bank_name": "HDFC Bank",
     "account_number": "1234567890",
     "ifsc_code": "HDFC0001234",
     "account_holder_name": "John Doe",
     "emi_auto_filled": true
   }
   ↓
   [Validate wallet balance >= requested_amount]
   ↓
   [Calculate TDS: 5% (max ₹10,000)]
   ↓
   [Calculate net_amount = requested_amount - tds_amount]
   ↓
   [If emi_auto_filled: Calculate EMI amount]
   ↓
   [Create Payout record (status='pending')]

2. Admin processes payout
   POST /api/payout/{id}/process/
   ↓
   [Admin approval]
   ↓
   [Deduct from wallet (deduct_wallet_balance)]
   ↓
   [Create PAYOUT transaction]
   ↓
   [If EMI auto-fill: Deduct EMI amount]
   ↓
   [Update Payout status='processing']
   ↓
   [Bank transfer initiated (integration ready)]
   ↓
   [Update Payout status='completed']
   ↓
   [Create PayoutTransaction records]
```

---

## Project Logic, Routing & Flow

### URL Routing Structure

```
Root URL Configuration (ev_backend/urls.py)
│
├── /admin/                        # Django admin panel
│
├── /api/auth/                     # Authentication endpoints
│   ├── send-otp/                  # Send OTP
│   ├── verify-otp/                # Verify OTP & login
│   ├── refresh/                   # Refresh JWT token
│   ├── logout/                    # Logout
│   ├── signup/                    # Signup
│   ├── verify-signup-otp/         # Verify signup OTP
│   ├── create-admin/              # Create admin user
│   └── create-staff/              # Create staff user
│
├── /api/users/                    # User management
│   ├── profile/                   # Get/update profile
│   ├── kyc/                       # KYC management
│   └── nominee/                   # Nominee management
│
├── /api/inventory/                # Vehicle inventory
│   ├── vehicles/                  # Vehicle CRUD
│   └── vehicle-images/            # Vehicle images
│
├── /api/booking/                   # Booking & payments
│   ├── bookings/                  # Booking CRUD
│   │   └── {id}/make_payment/     # Make payment
│   └── payments/                  # Payment records
│
├── /api/wallet/                    # Wallet management
│   ├── my_wallet/                 # Get wallet balance
│   └── transactions/              # Transaction history
│
├── /api/binary/                    # Binary tree MLM
│   ├── nodes/                     # Binary node operations
│   │   └── my_tree/               # Get user's tree
│   ├── pairs/                     # Binary pair operations
│   │   └── check_pairs/           # Check for pairs
│   └── earnings/                  # Earnings history
│
├── /api/payout/                    # Payout requests
│   ├── /                          # Payout CRUD
│   │   └── {id}/process/          # Process payout (admin)
│   └── transactions/              # Payout transactions
│
├── /api/notifications/             # Notifications
│   └── /                          # Notification CRUD
│
├── /api/compliance/                # Compliance
│   ├── documents/                 # Compliance documents
│   └── tds/                       # TDS records
│
└── /api/reports/                   # Reports & analytics
    ├── dashboard/                 # Dashboard stats
    ├── sales/                     # Sales report (admin)
    ├── user/                      # User report
    └── wallet/                    # Wallet report
```

### Request Flow Architecture

```
┌──────────────┐
│   Client     │
│  (Frontend)  │
└──────┬───────┘
       │
       │ HTTP Request
       ↓
┌─────────────────────────────────────┐
│         Nginx (Port 80/443)         │
│  - Rate Limiting                    │
│  - SSL Termination                  │
│  - Load Balancing                   │
│  - Static File Serving              │
└──────┬──────────────────────────────┘
       │
       │ Proxy to Django
       ↓
┌─────────────────────────────────────┐
│    Django (Gunicorn) Port 8000      │
│  - Request Processing               │
│  - Authentication (JWT)             │
│  - Permission Checks                │
│  - View Execution                   │
│  - Serialization                    │
└──────┬──────────────────────────────┘
       │
       ├─────────────────┬─────────────────┐
       ↓                 ↓                 ↓
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   MySQL      │  │    Redis     │  │   RabbitMQ   │
│  (Database)  │  │  (Cache/OTP) │  │ (Task Queue) │
└──────────────┘  └──────────────┘  └──────┬───────┘
                                           │
                                           ↓
                                    ┌──────────────┐
                                    │    Celery    │
                                    │   Workers    │
                                    │ (Background  │
                                    │   Tasks)     │
                                    └──────────────┘
```

### Authentication Flow

```
1. Unauthenticated Request
   ↓
   [Check for Authorization header]
   ↓
   [If missing: Return 401 Unauthorized]
   ↓
   [If present: Extract Bearer token]
   ↓
   [Validate JWT token]
   ↓
   [If invalid/expired: Return 401]
   ↓
   [If valid: Extract user from token]
   ↓
   [Set request.user]
   ↓
   [Continue to view]
```

### Permission Flow

```
1. Authenticated Request
   ↓
   [Check IsAuthenticated permission]
   ↓
   [Check role-based permissions (if applicable)]
   ↓
   [Check object-level permissions (if applicable)]
   ↓
   [If denied: Return 403 Forbidden]
   ↓
   [If allowed: Execute view]
```

### Data Flow: Booking Creation

```
1. POST /api/booking/bookings/
   ↓
   [Request reaches BookingViewSet.create()]
   ↓
   [Serializer validates data]
   ↓
   [Check minimum booking amount (₹500)]
   ↓
   [Create Booking instance]
   ↓
   [Generate booking_number]
   ↓
   [Set expiry (30 days)]
   ↓
   [Save to database]
   ↓
   [Return serialized response]
```

### Data Flow: Binary Pair Matching

```
1. POST /api/binary/pairs/check_pairs/
   ↓
   [Request reaches BinaryPairViewSet.check_pairs()]
   ↓
   [Get user's BinaryNode]
   ↓
   [Check if pair can be created]
   ↓
   [Call check_and_create_pair() utility]
   ↓
   [Create BinaryPair]
   ↓
   [Create BinaryEarning]
   ↓
   [Trigger Celery task: pair_matched.delay()]
   ↓
   [Return response]
   ↓
   [Celery worker picks up task]
   ↓
   [Execute pair_matched() task]
   ↓
   [Call add_wallet_balance() with business rules]
   ↓
   [Wallet credited]
   ↓
   [BinaryPair status='processed']
```

---

## Database Models & Relationships

### Entity Relationship Overview

```
User (Custom User Model)
│
├── OneToOne → Wallet
├── OneToOne → BinaryNode
├── OneToOne → KYC
├── OneToOne → Nominee
│
├── ForeignKey → referred_by (User, self-referential)
├── ForeignKey → referrals (User, reverse)
│
├── OneToMany → bookings (Booking)
├── OneToMany → payments (Payment)
├── OneToMany → wallet_transactions (WalletTransaction)
├── OneToMany → binary_pairs (BinaryPair)
├── OneToMany → binary_earnings (BinaryEarning)
├── OneToMany → payouts (Payout)
└── OneToMany → notifications (Notification)

Booking
│
├── ForeignKey → user (User)
├── ForeignKey → vehicle_model (Vehicle)
├── ForeignKey → referred_by (User, optional)
│
└── OneToMany → payments (Payment)

Payment
│
├── ForeignKey → booking (Booking)
└── ForeignKey → user (User)

Wallet
│
├── OneToOne → user (User)
│
└── OneToMany → transactions (WalletTransaction)

WalletTransaction
│
├── ForeignKey → user (User)
└── ForeignKey → wallet (Wallet)

BinaryNode
│
├── OneToOne → user (User)
├── ForeignKey → parent (BinaryNode, self-referential)
│
└── OneToMany → children (BinaryNode, reverse)

BinaryPair
│
├── ForeignKey → user (User)
├── ForeignKey → left_user (User)
├── ForeignKey → right_user (User)
│
└── OneToMany → earnings (BinaryEarning)

BinaryEarning
│
├── ForeignKey → user (User)
└── ForeignKey → binary_pair (BinaryPair)

Payout
│
├── ForeignKey → user (User)
├── ForeignKey → wallet (Wallet)
│
└── OneToMany → transactions (PayoutTransaction)

Vehicle
│
└── OneToMany → images (VehicleImage)
```

### Key Model Relationships

1. **User → Wallet**: One-to-One
   - Each user has exactly one wallet
   - Wallet created automatically on first transaction

2. **User → BinaryNode**: One-to-One
   - Each user has one position in the binary tree
   - Node created when user joins with referral

3. **User → Booking**: One-to-Many
   - User can have multiple bookings
   - Booking tracks user's payment history

4. **Booking → Payment**: One-to-Many
   - Booking can have multiple payment records
   - Tracks payment history for a booking

5. **BinaryNode → BinaryNode**: Self-referential (Tree)
   - Parent-child relationship
   - Left/Right side designation

6. **BinaryPair → BinaryEarning**: One-to-Many
   - Each pair can have earnings record
   - Tracks EMI deductions

---

## API Endpoints & Routing

### Authentication Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/api/auth/send-otp/` | Send OTP to email/mobile | No |
| POST | `/api/auth/verify-otp/` | Verify OTP & get JWT tokens | No |
| POST | `/api/auth/refresh/` | Refresh access token | No |
| POST | `/api/auth/logout/` | Logout (blacklist token) | Yes |
| POST | `/api/auth/signup/` | User signup | No |
| POST | `/api/auth/verify-signup-otp/` | Verify signup OTP | No |
| POST | `/api/auth/create-admin/` | Create admin user | Admin |
| POST | `/api/auth/create-staff/` | Create staff user | Admin |

### User Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/users/profile/` | Get user profile | Yes |
| PUT | `/api/users/update_profile/` | Update profile | Yes |
| GET | `/api/users/kyc/` | Get KYC details | Yes |
| POST | `/api/users/kyc/` | Submit KYC | Yes |
| GET | `/api/users/nominee/` | Get nominee details | Yes |
| POST | `/api/users/nominee/` | Add/update nominee | Yes |

### Inventory Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/inventory/vehicles/` | List vehicles | No |
| POST | `/api/inventory/vehicles/` | Create vehicle | Admin/Staff |
| GET | `/api/inventory/vehicles/{id}/` | Get vehicle details | No |
| PUT | `/api/inventory/vehicles/{id}/` | Update vehicle | Admin/Staff |
| DELETE | `/api/inventory/vehicles/{id}/` | Delete vehicle | Admin |
| GET | `/api/inventory/vehicle-images/` | List images | No |
| POST | `/api/inventory/vehicle-images/` | Upload image | Admin/Staff |

### Booking Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/booking/bookings/` | List user's bookings | Yes |
| POST | `/api/booking/bookings/` | Create booking | Yes |
| GET | `/api/booking/bookings/{id}/` | Get booking details | Yes |
| PUT | `/api/booking/bookings/{id}/` | Update booking | Yes |
| POST | `/api/booking/bookings/{id}/make_payment/` | Make payment | Yes |
| GET | `/api/booking/payments/` | List payments | Yes |

### Wallet Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/wallet/my_wallet/` | Get wallet balance | Yes |
| GET | `/api/wallet/transactions/` | List transactions | Yes |
| GET | `/api/wallet/transactions/{id}/` | Get transaction details | Yes |

### Binary Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/binary/nodes/my_tree/` | Get user's binary tree | Yes |
| GET | `/api/binary/pairs/` | List binary pairs | Yes |
| POST | `/api/binary/pairs/check_pairs/` | Check and create pairs | Yes |
| GET | `/api/binary/earnings/` | List earnings | Yes |

### Payout Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/payout/` | List payouts | Yes |
| POST | `/api/payout/` | Request payout | Yes |
| GET | `/api/payout/{id}/` | Get payout details | Yes |
| POST | `/api/payout/{id}/process/` | Process payout | Admin |
| GET | `/api/payout/transactions/` | List payout transactions | Yes |

### Notification Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/notifications/` | List notifications | Yes |
| PUT | `/api/notifications/{id}/mark_read/` | Mark as read | Yes |

### Compliance Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/compliance/documents/` | List documents | Yes |
| POST | `/api/compliance/documents/` | Upload document | Yes |
| GET | `/api/compliance/tds/` | List TDS records | Yes |

### Reports Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/api/reports/dashboard/` | Dashboard stats | Yes |
| GET | `/api/reports/sales/` | Sales report | Admin |
| GET | `/api/reports/user/` | User report | Yes |
| GET | `/api/reports/wallet/` | Wallet report | Yes |

---

## Business Rules & Logic

### 1. Booking Rules

| Rule | Value | Implementation |
|------|-------|----------------|
| Minimum pre-booking | ₹500 | Enforced in `BookingSerializer` |
| Active Buyer threshold | ₹5000 total paid | Auto-updated in `User.update_active_buyer_status()` |
| Booking expiry | 30 days | Set in `Booking.save()` |
| Booking number format | EV + 8 alphanumeric | Generated in `Booking.generate_booking_number()` |

### 2. Wallet & Earnings Rules

| Rule | Value | Implementation |
|------|-------|----------------|
| First 5 binary pairs | Full credit (no Active Buyer required) | `wallet/utils.py:add_wallet_balance()` |
| 6th pair onwards (not Active Buyer) | 20% EMI deduction | `wallet/utils.py:add_wallet_balance()` |
| Active Buyer | Full earnings from all pairs | `wallet/utils.py:add_wallet_balance()` |
| Referral bonus | 5% of payment amount | `booking/tasks.py:payment_completed()` |

### 3. Binary Tree Rules

| Rule | Value | Implementation |
|------|-------|----------------|
| Monthly pair limit | 10 pairs per user | `binary/utils.py:check_and_create_pair()` |
| Tree insertion | Level-order (balanced) | `binary/utils.py:find_next_available_position()` |
| Pair matching | Requires both left and right | `binary/utils.py:check_and_create_pair()` |

### 4. Payout Rules

| Rule | Value | Implementation |
|------|-------|----------------|
| TDS percentage | 5% | `payout/models.py:Payout.calculate_tds()` |
| TDS ceiling | ₹10,000 | `payout/models.py:Payout.calculate_tds()` |
| Net amount | Requested - TDS | `payout/models.py:Payout.calculate_tds()` |
| EMI auto-fill | Optional | `payout/models.py:Payout` |

### 5. Authentication Rules

| Rule | Value | Implementation |
|------|-------|----------------|
| OTP expiry | 10 minutes | Redis TTL in `auth/utils.py` |
| OTP length | 6 digits | Generated in `auth/utils.py` |
| Access token lifetime | 60 minutes | `settings.py:SIMPLE_JWT` |
| Refresh token lifetime | 24 hours | `settings.py:SIMPLE_JWT` |

---

## Background Tasks & Celery

### Celery Configuration

- **Broker**: RabbitMQ (AMQP)
- **Result Backend**: Redis
- **Task Serialization**: JSON
- **Time Zone**: Asia/Kolkata
- **Task Time Limit**: 30 minutes
- **Task Soft Time Limit**: 25 minutes

### Celery Tasks

#### 1. `core.booking.tasks.payment_completed`

**Trigger**: When payment is completed for a booking

**Purpose**: Process referral bonuses

**Logic**:
```python
1. Get booking and user
2. Check if user was referred
3. If referred and booking confirmed:
   - Calculate referral bonus (5% of amount)
   - Credit referrer's wallet
   - Create REFERRAL_BONUS transaction
```

#### 2. `core.binary.tasks.pair_matched`

**Trigger**: When binary pair is matched

**Purpose**: Credit wallet with business rules

**Logic**:
```python
1. Get BinaryPair
2. Count previous pairs
3. Call add_wallet_balance() with:
   - transaction_type='BINARY_PAIR'
   - amount=pair.earning_amount
   - Business rules applied automatically
4. Update pair status='processed'
```

#### 3. `core.payout.tasks.emi_autofill`

**Trigger**: When payout is processed with EMI auto-fill

**Purpose**: Auto-fill EMI from payout amount

**Logic**:
```python
1. Get Payout
2. Calculate EMI amount
3. Deduct from wallet
4. Create EMI_DEDUCTION transaction
5. Update booking EMI records
```

### Celery Workers

- **Worker**: `celery -A ev_backend worker --loglevel=info`
- **Beat Scheduler**: `celery -A ev_backend beat --loglevel=info`

### Task Queue Flow

```
Django View
   ↓
[Trigger Celery Task]
   ↓
[Task sent to RabbitMQ]
   ↓
[Celery Worker picks up task]
   ↓
[Task executed]
   ↓
[Result stored in Redis (if needed)]
```

---

## Deployment Architecture

### Docker Services

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Compose                       │
└─────────────────────────────────────────────────────────┘

Services:
├── django (Port 8000)
│   └── Gunicorn with 3 workers
│
├── celery (Background tasks)
│   └── Celery worker
│
├── celery-beat (Scheduled tasks)
│   └── Celery beat scheduler
│
├── mysql (Port 3306)
│   └── MySQL 8.0 database
│
├── redis (Port 6379)
│   └── Redis 7 cache & OTP storage
│
├── rabbitmq (Ports 5672, 15672)
│   └── RabbitMQ message broker
│
└── nginx (Ports 80, 443)
    └── Nginx reverse proxy
```

### Network Architecture

```
Internet
   │
   ↓
┌─────────────────┐
│   Nginx (80/443)│
│  - Rate Limiting│
│  - SSL/TLS      │
│  - Load Balance │
└────────┬────────┘
         │
         ├──────────────┬──────────────┐
         ↓              ↓              ↓
    ┌─────────┐   ┌─────────┐   ┌─────────┐
    │ Django  │   │ Django  │   │ Django  │
    │Instance1│   │Instance2│   │Instance3│
    └────┬────┘   └────┬────┘   └────┬────┘
         │             │             │
         └─────────────┴─────────────┘
                      │
         ┌────────────┼────────────┐
         ↓            ↓            ↓
    ┌─────────┐  ┌─────────┐  ┌─────────┐
    │  MySQL  │  │  Redis  │  │ RabbitMQ│
    │Primary  │  │ Cache   │  │  Broker │
    └─────────┘  └─────────┘  └────┬────┘
                                   │
                              ┌─────────┐
                              │ Celery  │
                              │ Workers │
                              └─────────┘
```

### Environment Configuration

**Development**:
- Database: SQLite
- Debug: True
- Email Backend: Console
- Static Files: Django development server

**Production**:
- Database: MySQL 8.0
- Debug: False
- Email Backend: SMTP
- Static Files: Nginx + WhiteNoise
- SSL/TLS: Enabled
- Rate Limiting: Enabled

### Scaling Considerations

1. **Horizontal Scaling**: Multiple Django instances behind Nginx
2. **Database**: Read replicas, connection pooling
3. **Caching**: Redis for frequently accessed data
4. **Background Tasks**: Multiple Celery workers
5. **CDN**: Static files and media delivery

---

## Additional Notes

### Security Features

1. **Rate Limiting** (Nginx):
   - OTP endpoints: 5 requests/minute
   - Booking endpoints: 10 requests/minute
   - Other APIs: 100 requests/minute

2. **Authentication**:
   - JWT tokens with refresh mechanism
   - OTP expiry (10 minutes)
   - Token blacklisting on logout

3. **Authorization**:
   - Role-based access control
   - Permission classes on all endpoints
   - Admin-only endpoints protected

4. **Data Protection**:
   - SQL injection protection (Django ORM)
   - XSS protection
   - CSRF protection
   - Secure password hashing

### Development Workflow

1. **Local Development**:
   ```bash
   python manage.py runserver
   celery -A ev_backend worker --loglevel=info
   ```

2. **Docker Development**:
   ```bash
   docker-compose up -d
   docker-compose exec django python manage.py migrate
   ```

3. **Testing**:
   - Unit tests (to be implemented)
   - Integration tests (to be implemented)
   - API testing (Postman/Insomnia)

### Future Enhancements

1. API versioning (`/api/v1/`, `/api/v2/`)
2. GraphQL alternative to REST
3. WebSocket for real-time notifications
4. Payment gateway integration (Razorpay, Stripe)
5. SMS provider integration (Twilio, AWS SNS)
6. File storage (AWS S3, CloudFront)
7. Search (Elasticsearch)
8. Comprehensive test coverage
9. API documentation (Swagger/OpenAPI)

---

## Conclusion

This documentation provides a comprehensive overview of the EV Distribution Platform, covering:

- **Folder Structure**: Detailed module organization
- **Workflow**: Step-by-step process flows
- **Routing & Flow**: URL structure and request handling
- **Database Models**: Entity relationships
- **Business Rules**: All implemented logic
- **Deployment**: Architecture and scaling

For specific implementation details, refer to the source code in each module's files.

---

**Last Updated**: 2024
**Version**: 1.0
**Maintained By**: Development Team

