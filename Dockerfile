FROM python:3.11-slim

# -----------------------------
# Environment
# -----------------------------
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=ev_backend.settings

WORKDIR /app

# -----------------------------
# System dependencies
# -----------------------------
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    ca-certificates \
    bash \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------
# Python dependencies
# -----------------------------
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --default-timeout=300 -r requirements.txt

# -----------------------------
# App source
# -----------------------------
COPY . .

# -----------------------------
# Non-root user
# -----------------------------
RUN useradd -m django && chown -R django:django /app
USER django

EXPOSE 8000

# -----------------------------
# Entrypoint
# -----------------------------
CMD ["bash", "-c", "\
echo 'Container starting...'; \
python manage.py migrate --noinput || true; \
python manage.py collectstatic --noinput || true; \
python -c \"\
import os, django; \
os.environ.setdefault('DJANGO_SETTINGS_MODULE','ev_backend.settings'); \
django.setup(); \
from django.contrib.auth import get_user_model; \
User=get_user_model(); \
username=os.getenv('DJANGO_SUPERUSER_USERNAME'); \
email=os.getenv('DJANGO_SUPERUSER_EMAIL'); \
password=os.getenv('DJANGO_SUPERUSER_PASSWORD'); \
if username and password and not User.objects.filter(username=username).exists(): \
    User.objects.create_superuser(username,email,password); \
    print('Superuser created'); \
else: \
    print('Superuser exists or env missing'); \
\"; \
gunicorn ev_backend.wsgi:application --bind 0.0.0.0:8000 --workers 1 --timeout 120"]
