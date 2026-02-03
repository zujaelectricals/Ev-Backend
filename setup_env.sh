#!/bin/bash
# Setup script for EV Backend

echo "Creating .env file from template..."

cat > .env << EOF
# Database Configuration
DB_ENGINE=sqlite
# For MySQL (production)
# DB_ENGINE=mysql
# DB_NAME=ev_backend
# DB_USER=ev_user
# DB_PASSWORD=ev_password
# DB_HOST=mysql
# DB_PORT=3306

# Django Settings
SECRET_KEY=$(python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Redis Configuration
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0

# RabbitMQ Configuration
RABBITMQ_HOST=rabbitmq
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASSWORD=guest

# JWT Settings
JWT_SECRET_KEY=\$SECRET_KEY
JWT_ALGORITHM=HS256
ACCESS_TOKEN_LIFETIME=60
REFRESH_TOKEN_LIFETIME=1440

# Email Configuration (for OTP)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=

# SMS Configuration (for OTP - integrate with provider)
SMS_API_KEY=
SMS_API_URL=https://api.sms-provider.com

# Razorpay Configuration
# Get your keys from: https://dashboard.razorpay.com/app/keys
# Test Mode: Use Test Key ID and Test Key Secret (for development)
# Live Mode: Use Live Key ID and Live Key Secret (for production)
# Toggle between Test/Live mode in Razorpay Dashboard
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=
RAZORPAY_PAYOUT_WEBHOOK_SECRET=

# Business Rules
PRE_BOOKING_MIN_AMOUNT=500
ACTIVE_BUYER_THRESHOLD=5000
MAX_EARNINGS_BEFORE_ACTIVE_BUYER=5
EMI_DEDUCTION_PERCENTAGE=20
MAX_BINARY_PAIRS_PER_MONTH=10

# TDS Configuration
TDS_PERCENTAGE=5
TDS_CEILING=10000

# Booking Reservation Timeout (hours, empty/null = never expires)
BOOKING_RESERVATION_TIMEOUT_HOURS=24
EOF

echo ".env file created successfully!"

