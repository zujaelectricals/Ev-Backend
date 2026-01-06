# EV Distribution Platform - Django Backend

A comprehensive Django monolith backend for EV distribution platform with MLM (Multi-Level Marketing) features, wallet management, binary tree structure, and financial compliance.

## 🧱 Tech Stack

- **Django 4.2** + **Django REST Framework**
- **JWT Authentication** with OTP (Email/Mobile)
- **Celery** + **RabbitMQ** for background tasks
- **Redis** for OTP storage and caching
- **SQLite** (development) / **MySQL** (production)
- **Docker** + **Docker Compose** for containerization
- **Nginx** for reverse proxy, rate limiting, and load balancing

## 🗂 Project Structure

```
ev_backend/
├── core/
│   ├── auth/          # OTP authentication, JWT tokens
│   ├── users/         # User management, roles, KYC, Nominee
│   ├── booking/       # EV bookings, payments, EMI tracking
│   ├── wallet/        # Wallet ledger, transaction types
│   ├── binary/        # Binary tree, pair matching
│   ├── payout/        # Payout requests, TDS, EMI auto-fill
│   ├── notification/  # User notifications
│   ├── compliance/    # Compliance documents, TDS records
│   └── reports/       # Dashboard and reports
├── ev_backend/        # Django project settings
├── nginx/             # Nginx configuration
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)

### Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd EV
   ```

2. **Create `.env` file**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Build and run with Docker**
   ```bash
   docker-compose up -d --build
   ```

4. **Run migrations**
   ```bash
   docker-compose exec django python manage.py migrate
   ```

5. **Create superuser**
   ```bash
   docker-compose exec django python manage.py createsuperuser
   ```

6. **Access the application**
   - API: http://localhost:8000/api/
   - Admin: http://localhost:8000/admin/
   - RabbitMQ Management: http://localhost:15672 (guest/guest)

## 🔐 Authentication

### OTP Login Flow

1. **Send OTP**
   ```bash
   POST /api/auth/send-otp/
   {
     "identifier": "user@example.com",
     "otp_type": "email"
   }
   ```

2. **Verify OTP & Login**
   ```bash
   POST /api/auth/verify-otp/
   {
     "identifier": "user@example.com",
     "otp_code": "123456",
     "otp_type": "email",
     "referral_code": "REF12345"  # Optional
   }
   ```

3. **Use JWT Token**
   ```bash
   Authorization: Bearer <access_token>
   ```

## 📋 Business Rules

| Rule | Logic |
|------|-------|
| Pre-booking | ₹500 minimum |
| Active Buyer | ₹5000 total paid |
| Earnings Limit | First 5 binary pairs without Active Buyer |
| EMI Deduction | 20% from 6th pair if not Active Buyer |
| Binary Pairs | Max 10 pairs per month |
| TDS | 5% with ₹10,000 ceiling |

## 💰 Wallet Module

### Transaction Types

- `REFERRAL_BONUS` - Referral earnings
- `BINARY_PAIR` - Binary pair matching earnings
- `EMI_DEDUCTION` - Automatic EMI deductions
- `RESERVE_DEDUCTION` - Reserve fund deductions
- `PAYOUT` - Withdrawal transactions

### Business Logic

- First 5 binary pair earnings are credited fully (even without Active Buyer)
- From 6th pair onwards: 20% deducted to EMI if user is not Active Buyer
- Active Buyers get full earnings from all pairs

## 🌳 Binary Module

- Left/Right binary tree structure
- Automatic pair matching
- Monthly limit: 10 pairs per user
- Earnings credited to wallet with business rules applied

## 💸 Payout Module

- TDS calculation: 5% with ₹10,000 ceiling
- EMI auto-fill option
- Bank transfer integration ready
- Admin approval workflow

## 🔄 Celery Tasks

Background tasks handled by Celery:

- `payment_completed` - Process payment and referral bonuses
- `pair_matched` - Handle binary pair earnings
- `emi_autofill` - Auto-fill EMI from payout
- `wallet_update` - Update wallet balances

## 🗄 Database Switch

Switch between SQLite (dev) and MySQL (prod) via `.env`:

```env
# Development
DB_ENGINE=sqlite

# Production
DB_ENGINE=mysql
DB_NAME=ev_backend
DB_USER=ev_user
DB_PASSWORD=ev_password
DB_HOST=mysql
DB_PORT=3306
```

## 🌐 Nginx Configuration

- **Rate Limiting**:
  - OTP endpoints: 5 requests/minute
  - Booking endpoints: 10 requests/minute
  - Other APIs: 100 requests/minute

- **SSL Ready**: Uncomment HTTPS configuration in `nginx/conf.d/default.conf`

- **Load Balancing**: Configured for multiple Django instances

## 📝 API Endpoints

### Authentication
- `POST /api/auth/send-otp/` - Send OTP
- `POST /api/auth/verify-otp/` - Verify OTP & Login
- `POST /api/auth/refresh/` - Refresh JWT token
- `POST /api/auth/logout/` - Logout

### Users
- `GET /api/users/profile/` - Get user profile
- `PUT /api/users/update_profile/` - Update profile
- `GET /api/users/kyc/` - KYC management
- `GET /api/users/nominee/` - Nominee management

### Booking
- `GET /api/booking/bookings/` - List bookings
- `POST /api/booking/bookings/` - Create booking
- `POST /api/booking/bookings/{id}/make_payment/` - Make payment

### Wallet
- `GET /api/wallet/my_wallet/` - Get wallet balance
- `GET /api/wallet/transactions/` - Transaction history

### Binary
- `GET /api/binary/nodes/my_tree/` - Get binary tree
- `POST /api/binary/pairs/check_pairs/` - Check for pairs
- `GET /api/binary/earnings/` - Earnings history

### Payout
- `GET /api/payout/` - List payouts
- `POST /api/payout/` - Request payout
- `POST /api/payout/{id}/process/` - Process payout (admin)

### Reports
- `GET /api/reports/dashboard/` - Dashboard stats
- `GET /api/reports/sales/` - Sales report (admin)
- `GET /api/reports/user/` - User report
- `GET /api/reports/wallet/` - Wallet report

## 🐳 Docker Services

- **django** - Django application server
- **celery** - Celery worker
- **celery-beat** - Celery beat scheduler
- **mysql** - MySQL database
- **redis** - Redis cache/OTP storage
- **rabbitmq** - RabbitMQ message broker
- **nginx** - Nginx reverse proxy

## 🔧 Development

### Local Development (without Docker)

1. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set environment variables**
   ```bash
   export DB_ENGINE=sqlite
   export SECRET_KEY=your-secret-key
   ```

4. **Run migrations**
   ```bash
   python manage.py migrate
   ```

5. **Create superuser**
   ```bash
   python manage.py createsuperuser
   ```

6. **Run development server**
   ```bash
   python manage.py runserver
   ```

7. **Run Celery worker** (in separate terminal)
   ```bash
   celery -A ev_backend worker --loglevel=info
   ```

## 📦 Production Deployment

1. **Update `.env` with production values**
2. **Set `DEBUG=False`**
3. **Configure SSL certificates in `nginx/ssl/`**
4. **Uncomment HTTPS configuration in Nginx**
5. **Run migrations**
6. **Collect static files**
7. **Scale services as needed**

## 🔒 Security Notes

- Change all default passwords and secrets
- Use strong SECRET_KEY in production
- Enable HTTPS in production
- Configure proper CORS origins
- Review rate limiting settings
- Regular security updates

## 📄 License

[Your License Here]

## 👥 Contributors

[Your Team Here]

