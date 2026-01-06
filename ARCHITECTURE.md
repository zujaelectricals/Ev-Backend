# EV Distribution Platform - Architecture Documentation

## System Architecture

### Overview
This is a Django monolith backend designed for an EV distribution platform with MLM (Multi-Level Marketing) features. The system is production-ready and can be easily split into microservices later.

### Technology Stack

#### Core Framework
- **Django 4.2.7** - Web framework
- **Django REST Framework 3.14.0** - API framework
- **Python 3.11** - Programming language

#### Authentication & Security
- **JWT (JSON Web Tokens)** - Token-based authentication
- **OTP (One-Time Password)** - Email/Mobile verification
- **Redis** - OTP storage and session management

#### Background Processing
- **Celery 5.3.4** - Distributed task queue
- **RabbitMQ** - Message broker
- **Redis** - Result backend

#### Database
- **SQLite** - Development database
- **MySQL 8.0** - Production database
- **Database switching** via environment variable

#### Infrastructure
- **Docker** - Containerization
- **Docker Compose** - Multi-container orchestration
- **Nginx** - Reverse proxy, load balancer, rate limiting
- **Gunicorn** - WSGI HTTP server

## Module Architecture

### 1. Authentication Module (`core.auth`)
**Purpose**: Handle user authentication via OTP

**Components**:
- OTP generation and verification
- Redis-based OTP storage (10-minute expiry)
- JWT token generation
- Referral code handling

**Key Features**:
- Email OTP support
- Mobile OTP support (SMS integration ready)
- Automatic referral code generation
- JWT access and refresh tokens

### 2. Users Module (`core.users`)
**Purpose**: User management and profile

**Models**:
- `User` - Custom user model with roles, distributor flag, Active Buyer status
- `KYC` - Know Your Customer documents and verification
- `Nominee` - Nominee information

**Key Features**:
- Role-based access (admin, staff, user)
- Distributor flag for MLM hierarchy
- Active Buyer status (auto-updated at ₹5000 paid)
- KYC verification workflow
- Nominee management

### 3. Booking Module (`core.booking`)
**Purpose**: EV booking and payment management

**Models**:
- `Booking` - EV booking records
- `Payment` - Payment transactions

**Business Rules**:
- Minimum pre-booking amount: ₹500
- Active Buyer threshold: ₹5000 total paid
- EMI tracking and management
- Automatic status updates

**Celery Tasks**:
- `payment_completed` - Process referral bonuses

### 4. Wallet Module (`core.wallet`)
**Purpose**: Single wallet ledger system

**Models**:
- `Wallet` - User wallet with balance tracking
- `WalletTransaction` - Complete transaction ledger

**Transaction Types**:
- `REFERRAL_BONUS` - Referral earnings
- `BINARY_PAIR` - Binary pair matching earnings
- `EMI_DEDUCTION` - Automatic EMI deductions
- `RESERVE_DEDUCTION` - Reserve fund deductions
- `PAYOUT` - Withdrawal transactions
- `DEPOSIT` - Manual deposits
- `REFUND` - Refund transactions

**Business Rules**:
1. First 5 binary pair earnings: Full credit (even without Active Buyer)
2. From 6th pair onwards: 20% deducted to EMI if not Active Buyer
3. Active Buyers: Full earnings from all pairs

### 5. Binary Module (`core.binary`)
**Purpose**: Binary tree structure and pair matching

**Models**:
- `BinaryNode` - Binary tree node (left/right structure)
- `BinaryPair` - Matched pair records
- `BinaryEarning` - Earnings from pairs

**Features**:
- Left/Right binary tree
- Automatic pair matching
- Monthly limit: 10 pairs per user
- Level-order tree insertion
- Pair counting and tracking

**Celery Tasks**:
- `pair_matched` - Process pair earnings with business rules

### 6. Payout Module (`core.payout`)
**Purpose**: Payout requests and financial compliance

**Models**:
- `Payout` - Payout requests
- `PayoutTransaction` - Payout transaction records

**Features**:
- TDS calculation (5% with ₹10,000 ceiling)
- EMI auto-fill option
- Bank transfer integration ready
- Admin approval workflow

**Celery Tasks**:
- `emi_autofill` - Auto-fill EMI from payout amount

### 7. Notification Module (`core.notification`)
**Purpose**: User notifications

**Models**:
- `Notification` - User notifications

**Features**:
- Multiple notification types
- Read/unread tracking
- Reference to related objects

### 8. Compliance Module (`core.compliance`)
**Purpose**: Legal and tax compliance

**Models**:
- `ComplianceDocument` - Document storage
- `TDSRecord` - TDS records for tax compliance

**Features**:
- Document upload and verification
- TDS certificate generation
- Financial year tracking

### 9. Reports Module (`core.reports`)
**Purpose**: Analytics and reporting

**Endpoints**:
- Dashboard statistics
- Sales reports
- User activity reports
- Wallet transaction reports

## Data Flow

### User Registration Flow
1. User requests OTP (email/mobile)
2. OTP stored in Redis (10 min expiry)
3. User verifies OTP
4. User created/authenticated
5. JWT tokens generated
6. Referral code assigned (if new user)
7. Referral relationship established (if code provided)

### Booking Flow
1. User creates booking (min ₹500)
2. Payment made
3. Booking status updated
4. Active Buyer status checked/updated
5. Celery task: `payment_completed` triggered
6. Referral bonus credited (if applicable)

### Binary Pair Flow
1. User added to binary tree
2. Left/Right counts updated
3. Pair matching checked
4. If pair found:
   - BinaryPair created
   - Monthly limit checked
   - Celery task: `pair_matched` triggered
   - Wallet updated with business rules
   - EMI deduction applied (if applicable)

### Payout Flow
1. User requests payout
2. Wallet balance validated
3. TDS calculated
4. EMI auto-fill (optional)
5. Admin approval
6. Wallet debited
7. Bank transfer processed

## Business Rules Summary

| Rule | Implementation |
|------|----------------|
| Pre-booking minimum | ₹500 (enforced in BookingSerializer) |
| Active Buyer threshold | ₹5000 total paid (auto-updated in User model) |
| First 5 earnings | Full credit without Active Buyer (Wallet utils) |
| EMI deduction | 20% from 6th pair if not Active Buyer (Wallet utils) |
| Binary pairs limit | 10 pairs per month (Binary utils) |
| TDS percentage | 5% (Payout model) |
| TDS ceiling | ₹10,000 (Payout model) |

## Security Features

1. **Rate Limiting** (Nginx):
   - OTP endpoints: 5 req/min
   - Booking endpoints: 10 req/min
   - Other APIs: 100 req/min

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
   - XSS protection (Django templates)
   - CSRF protection
   - Secure password hashing

## Scalability Considerations

### Current Architecture (Monolith)
- All modules in single Django project
- Shared database
- Centralized authentication
- Easy to develop and deploy

### Future Microservices Split
The architecture is designed for easy splitting:

1. **Auth Service**: OTP, JWT, User management
2. **Booking Service**: Bookings, Payments
3. **Wallet Service**: Wallet, Transactions
4. **Binary Service**: Binary tree, Pair matching
5. **Payout Service**: Payouts, TDS
6. **Notification Service**: Notifications
7. **Compliance Service**: Documents, TDS records
8. **Reports Service**: Analytics, Reports

### Scaling Strategies
- **Horizontal Scaling**: Multiple Django instances behind Nginx
- **Database**: Read replicas, connection pooling
- **Caching**: Redis for frequently accessed data
- **Background Tasks**: Multiple Celery workers
- **CDN**: Static files and media

## Deployment Architecture

```
Internet
   |
   v
Nginx (Load Balancer + Rate Limiter)
   |
   +---> Django Instance 1 (Gunicorn)
   +---> Django Instance 2 (Gunicorn)
   +---> Django Instance 3 (Gunicorn)
   |
   +---> Celery Workers (Multiple)
   |
   v
MySQL (Primary) + Read Replicas
   |
Redis (Cache + OTP Storage)
   |
RabbitMQ (Message Broker)
```

## Environment Configuration

### Development
- SQLite database
- Console email backend
- Debug mode enabled
- Local Redis/RabbitMQ

### Production
- MySQL database
- SMTP email backend
- Debug mode disabled
- SSL/TLS enabled
- Production Redis/RabbitMQ
- Monitoring and logging

## Monitoring & Logging

### Recommended Tools
- **Application Monitoring**: Sentry, New Relic
- **Logging**: ELK Stack, CloudWatch
- **Metrics**: Prometheus, Grafana
- **Uptime**: Pingdom, UptimeRobot

### Key Metrics to Monitor
- API response times
- Error rates
- Database query performance
- Celery task queue length
- Redis memory usage
- Nginx request rates

## Future Enhancements

1. **API Versioning**: `/api/v1/`, `/api/v2/`
2. **GraphQL**: Alternative to REST
3. **WebSocket**: Real-time notifications
4. **Payment Gateway Integration**: Razorpay, Stripe
5. **SMS Provider Integration**: Twilio, AWS SNS
6. **File Storage**: AWS S3, CloudFront
7. **Search**: Elasticsearch for user/bookings search
8. **Caching**: More aggressive Redis caching
9. **API Documentation**: Swagger/OpenAPI
10. **Testing**: Unit tests, integration tests

