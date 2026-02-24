"""
Django settings for ev_backend (Azure Production)
"""

from pathlib import Path
import environ
import os
from datetime import timedelta
import hashlib

# --------------------------------------------------
# BASE
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)

ALLOWED_HOSTS = env.list(
    "ALLOWED_HOSTS",
    default=["*"],  # Azure App Service
)

# --------------------------------------------------
# APPLICATIONS
# --------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "storages",
    "django_celery_results",

    # Local apps
    "core.auth",
    "core.users",
    "core.inventory",
    "core.booking",
    "core.wallet",
    "core.binary",
    "core.payout",
    "core.notification",
    "core.compliance",
    "core.reports",
    "core.settings",
    "core.payments",
    "core.gallery",
]

# --------------------------------------------------
# MIDDLEWARE
# --------------------------------------------------

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "ev_backend.cors_middleware.CorsPreflightMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ev_backend.urls"
WSGI_APPLICATION = "ev_backend.wsgi.application"

# --------------------------------------------------
# TEMPLATES
# --------------------------------------------------

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------
# DATABASE
# --------------------------------------------------

DB_ENGINE = env("DB_ENGINE", default="sqlite")

if DB_ENGINE == "mysql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env("DB_NAME"),
            "USER": env("DB_USER"),
            "PASSWORD": env("DB_PASSWORD"),
            "HOST": env("DB_HOST"),
            "PORT": env("DB_PORT", default="3306"),
            "OPTIONS": {
                "ssl": {
                    "ca": "/etc/ssl/certs/ca-certificates.crt"
                }
            },
        }
    }
else:
    # Use data directory for SQLite to ensure write permissions in Docker
    db_path = BASE_DIR / "data" / "db.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": db_path,
        }
    }

# --------------------------------------------------
# AUTH
# --------------------------------------------------

AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------
# INTERNATIONAL
# --------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------
# STATIC & MEDIA (AZURE BLOB STORAGE)
# --------------------------------------------------

DEFAULT_FILE_STORAGE = "storages.backends.azure_storage.AzureStorage"
STATICFILES_STORAGE = "storages.backends.azure_storage.AzureStorage"

AZURE_ACCOUNT_NAME = env("AZURE_STORAGE_NAME")
AZURE_ACCOUNT_KEY = env("AZURE_STORAGE_KEY")

AZURE_STATIC_CONTAINER = env("AZURE_STATIC_CONTAINER", default="static")
AZURE_MEDIA_CONTAINER = env("AZURE_MEDIA_CONTAINER", default="media")

AZURE_CONTAINER = AZURE_STATIC_CONTAINER

STATIC_URL = f"https://{AZURE_ACCOUNT_NAME}.blob.core.windows.net/{AZURE_STATIC_CONTAINER}/"
MEDIA_URL = f"https://{AZURE_ACCOUNT_NAME}.blob.core.windows.net/{AZURE_MEDIA_CONTAINER}/"

# --------------------------------------------------
# REST FRAMEWORK
# --------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
     "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/hour",
        "user": "1000/hour",
        "otp": "5/minute",
        "otp_identifier": "5/minute",
    },
}

# --------------------------------------------------
# JWT
# --------------------------------------------------

jwt_secret_key = env("JWT_SECRET_KEY", default=SECRET_KEY)

if len(jwt_secret_key.encode()) < 32:
    jwt_secret_key = hashlib.sha256(jwt_secret_key.encode()).hexdigest()

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("ACCESS_TOKEN_LIFETIME", 45)),
    "REFRESH_TOKEN_LIFETIME": timedelta(minutes=env.int("REFRESH_TOKEN_LIFETIME", 300)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "SIGNING_KEY": jwt_secret_key,
}
ACCESS_TOKEN_LIFETIME = env.int("ACCESS_TOKEN_LIFETIME", default=45)
REFRESH_TOKEN_LIFETIME = env.int("REFRESH_TOKEN_LIFETIME", default=300)

# --------------------------------------------------
# REDIS / CELERY
# --------------------------------------------------

REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

CSRF_TRUSTED_ORIGINS = [
    "https://ev-backend-api-dca5g4adcrgwhbfg.southindia-01.azurewebsites.net",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

# Only use secure cookies in production (HTTPS)
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG

CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SAMESITE = "Lax"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Only redirect to HTTPS in production (not in development)
SECURE_SSL_REDIRECT = not DEBUG


# --------------------------------------------------
# MSG91
# --------------------------------------------------

MSG91_AUTH_KEY = env("MSG91_AUTH_KEY", default="")
MSG91_COMPANY_NAME = env("MSG91_COMPANY_NAME", default="ZUJA ELECTRICAL INNOVATION PRIVATE LIMITED")
# --------------------------------------------------
# CORS
# --------------------------------------------------

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:8080", "http://127.0.0.1:8080"])
CORS_ALLOW_CREDENTIALS = True

# Allow all methods and headers
CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]

# --------------------------------------------------
# OTP
# --------------------------------------------------

OTP_LENGTH = env.int("OTP_LENGTH", default=6)
OTP_EXPIRY_SECONDS = env.int("OTP_EXPIRY_SECONDS", default=300)
OTP_EXPIRY_MINUTES = env.int("OTP_EXPIRY_MINUTES", default=20)

# --------------------------------------------------
# PAYMENTS
# --------------------------------------------------

RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID", default="")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET", default="")
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET", default="")
RAZORPAY_PAYOUT_WEBHOOK_SECRET = env("RAZORPAY_PAYOUT_WEBHOOK_SECRET", default="")

# Razorpay API timeout & retry tuning
# Connect timeout: 10s is enough for a healthy connection to Razorpay
# Read timeout: 20s — Razorpay order creation rarely takes >5s normally
# Max retries: 1 — retrying once is enough; avoids 3x multiplier on latency
# Backoff base: 1s — wait 1s before the single retry
RAZORPAY_CONNECT_TIMEOUT = env.int("RAZORPAY_CONNECT_TIMEOUT", default=10)
RAZORPAY_READ_TIMEOUT = env.int("RAZORPAY_READ_TIMEOUT", default=20)
RAZORPAY_MAX_RETRIES = env.int("RAZORPAY_MAX_RETRIES", default=1)
RAZORPAY_RETRY_BACKOFF_BASE = env.int("RAZORPAY_RETRY_BACKOFF_BASE", default=1)
# RazorpayX (Payouts) - separate credentials for payout operations
RAZORPAYX_KEY_ID = env("RAZORPAYX_KEY_ID", default="")
RAZORPAYX_KEY_SECRET = env("RAZORPAYX_KEY_SECRET", default="")
RAZORPAYX_ACCOUNT_NUMBER = env("RAZORPAYX_ACCOUNT_NUMBER", default="")
RAZORPAY_PAYOUT_WEBHOOK_SECRET = env("RAZORPAY_PAYOUT_WEBHOOK_SECRET", default="")
# --------------------------------------------------
# BUSINESS RULES
# --------------------------------------------------

PRE_BOOKING_MIN_AMOUNT = env.int("PRE_BOOKING_MIN_AMOUNT", default=500)

# --------------------------------------------------
# FRONTEND
# --------------------------------------------------

FRONTEND_BASE_URL = env("FRONTEND_BASE_URL", default="http://localhost:8080")

# --------------------------------------------------
# DEFAULT
# --------------------------------------------------

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "ERROR",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}

