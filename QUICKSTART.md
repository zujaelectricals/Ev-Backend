# Quick Start Guide

## 🚀 Getting Started in 5 Minutes

### Prerequisites
- Docker and Docker Compose installed
- Git (optional)

### Step 1: Clone and Setup
```bash
cd EV
```

### Step 2: Create Environment File
```bash
# Copy the example (or create manually)
# Edit .env with your settings
```

### Step 3: Start Services
```bash
docker-compose up -d --build
```

### Step 4: Run Migrations
```bash
docker-compose exec django python manage.py migrate
```

### Step 5: Create Admin User
```bash
docker-compose exec django python manage.py createsuperuser
```

### Step 6: Access the Application
- **API**: http://localhost:8000/api/
- **Admin Panel**: http://localhost:8000/admin/
- **RabbitMQ Management**: http://localhost:15672 (guest/guest)

## 📝 First API Call

### 1. Send OTP
```bash
curl -X POST http://localhost:8000/api/auth/send-otp/ \
  -H "Content-Type: application/json" \
  -d '{
    "identifier": "test@example.com",
    "otp_type": "email"
  }'
```

### 2. Verify OTP & Login
```bash
curl -X POST http://localhost:8000/api/auth/verify-otp/ \
  -H "Content-Type: application/json" \
  -d '{
    "identifier": "test@example.com",
    "otp_code": "123456",
    "otp_type": "email"
  }'
```

### 3. Use JWT Token
```bash
# Replace <access_token> with token from step 2
curl -X GET http://localhost:8000/api/users/profile/ \
  -H "Authorization: Bearer <access_token>"
```

## 🔧 Common Commands

### Using Makefile
```bash
make build          # Build Docker images
make up             # Start services
make down           # Stop services
make migrate        # Run migrations
make createsuperuser # Create admin
make logs           # View logs
make restart        # Restart services
```

### Using Docker Compose Directly
```bash
docker-compose up -d              # Start in background
docker-compose down               # Stop services
docker-compose logs -f django     # View Django logs
docker-compose exec django bash   # Access Django container
docker-compose restart celery     # Restart Celery
```

### Django Management Commands
```bash
docker-compose exec django python manage.py migrate
docker-compose exec django python manage.py createsuperuser
docker-compose exec django python manage.py shell
docker-compose exec django python manage.py collectstatic
```

## 🐛 Troubleshooting

### Services won't start
```bash
# Check logs
docker-compose logs

# Rebuild containers
docker-compose down
docker-compose up -d --build
```

### Database connection errors
- Check `.env` file has correct database credentials
- Ensure MySQL container is running: `docker-compose ps`
- Wait for MySQL to be ready (may take 30 seconds)

### Celery not processing tasks
- Check Celery logs: `docker-compose logs celery`
- Ensure RabbitMQ is running: `docker-compose ps rabbitmq`
- Restart Celery: `docker-compose restart celery`

### Port already in use
- Change ports in `docker-compose.yml`
- Or stop conflicting services

## 📚 Next Steps

1. **Configure Email**: Update EMAIL_* settings in `.env`
2. **Configure SMS**: Add SMS provider credentials
3. **Set Production Settings**: Update `DEBUG=False`, add `ALLOWED_HOSTS`
4. **SSL Setup**: Configure SSL certificates in `nginx/ssl/`
5. **Read Documentation**: See `README.md` and `ARCHITECTURE.md`

## 🎯 Testing the System

### Create a Test User
1. Send OTP to email/mobile
2. Verify OTP to create account
3. Check user in admin panel

### Create a Booking
```bash
curl -X POST http://localhost:8000/api/booking/bookings/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "vehicle_model": "EV Model X",
    "booking_amount": 500,
    "total_amount": 50000
  }'
```

### Check Wallet
```bash
curl -X GET http://localhost:8000/api/wallet/my_wallet/ \
  -H "Authorization: Bearer <token>"
```

## 💡 Tips

- Use `docker-compose logs -f` to follow all logs
- Check RabbitMQ management UI for queue status
- Use Django admin for quick data inspection
- Redis data persists in `redis_data` volume
- MySQL data persists in `mysql_data` volume

## 🔗 Useful Links

- Django Admin: http://localhost:8000/admin/
- API Root: http://localhost:8000/api/
- RabbitMQ: http://localhost:15672
- Health Check: http://localhost:80/health/

