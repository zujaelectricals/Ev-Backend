"""
Django settings for ev_backend project (Azure Production Ready)
"""

from pathlib import Path
from decouple import config
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

SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", cast=bool, default=False)

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1",
).split(",")

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

    # Third party
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "storages",
    "django_celery_results",

    # Local
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
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
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
# DATABASE
# --------------------------------------------------

DB_ENGINE = config("DB_ENGINE", default="sqlite")

if DB_ENGINE == "mysql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": env("DB_NAME"),
            "USER": env("DB_USER"),
            "PASSWORD": env("DB_PASSWORD"),
            "HOST": env("DB_HOST"),
            "PORT": "3306",
            "OPTIONS": {
                "ssl": {"ca": "/etc/ssl/certs/ca-certificates.crt"}
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# --------------------------------------------------
# AUTH
# --------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "users.User"

# --------------------------------------------------
# INTERNATIONAL
# --------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------
# STATIC / MEDIA (AZURE)
# --------------------------------------------------

USE_AZURE_STORAGE = config("USE_AZURE_STORAGE", cast=bool, default=False)

AZURE_ACCOUNT_NAME = env("AZURE_STORAGE_NAME", default="")
AZURE_ACCOUNT_KEY = env("AZURE_STORAGE_KEY", default="")

if USE_AZURE_STORAGE:
    DEFAULT_FILE_STORAGE = "storages.backends.azure_storage.AzureStorage"
    STATICFILES_STORAGE = "storages.backends.azure_storage.AzureStorage"

    MEDIA_URL = f"https://{AZURE_ACCOUNT_NAME}.blob.core.windows.net/media/"
    STATIC_URL = f"https://{AZURE_ACCOUNT_NAME}.blob.core.windows.net/static/"
else:
    STATIC_URL = "/static/"
    STATIC_ROOT = BASE_DIR / "staticfiles"

    MEDIA_URL = "/media/"
    MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

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

jwt_secret_key = config("JWT_SECRET_KEY", default=SECRET_KEY)
if len(jwt_secret_key.encode()) < 32:
    jwt_secret_key = hashlib.sha256(jwt_secret_key.encode()).hexdigest()

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=config("ACCESS_TOKEN_LIFETIME", default=45, cast=int)),
    "REFRESH_TOKEN_LIFETIME": timedelta(minutes=config("REFRESH_TOKEN_LIFETIME", default=300, cast=int)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "SIGNING_KEY": jwt_secret_key,
}

# --------------------------------------------------
# REDIS / CACHE
# --------------------------------------------------

REDIS_URL = env("REDIS_URL")
REDIS_PASSWORD = env("REDIS_KEY")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "PASSWORD": REDIS_PASSWORD,
            "SSL": True,
        },
    }
}

# --------------------------------------------------
# CELERY (REDIS BROKER)
# --------------------------------------------------

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL

CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"

CELERY_TIMEZONE = TIME_ZONE

CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60

# --------------------------------------------------
# CORS
# --------------------------------------------------

CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="",
).split(",")

CORS_ALLOW_CREDENTIALS = True

# --------------------------------------------------
# BUSINESS RULES
# --------------------------------------------------

PRE_BOOKING_MIN_AMOUNT = config("PRE_BOOKING_MIN_AMOUNT", default=500, cast=int)
ACTIVE_BUYER_THRESHOLD = config("ACTIVE_BUYER_THRESHOLD", default=5000, cast=int)

# --------------------------------------------------
# PAYMENTS
# --------------------------------------------------

RAZORPAY_KEY_ID = config("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = config("RAZORPAY_KEY_SECRET")

RAZORPAY_WEBHOOK_SECRET = config("RAZORPAY_WEBHOOK_SECRET")
RAZORPAY_PAYOUT_WEBHOOK_SECRET = config("RAZORPAY_PAYOUT_WEBHOOK_SECRET")
