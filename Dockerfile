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
set -e; \
if [ \"$SERVICE_ROLE\" = \"web\" ]; then \
    echo 'Starting Django Web (Gunicorn)'; \
    python manage.py migrate --noinput; \
    python manage.py collectstatic --noinput; \
    gunicorn ev_backend.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers 3 \
        --timeout 120; \
elif [ \"$SERVICE_ROLE\" = \"celery\" ]; then \
    echo 'Starting Celery Worker'; \
    python -m celery worker \
        -A ev_backend \
        --loglevel=info \
        --pool=solo; \
else \
    echo 'ERROR: SERVICE_ROLE not set (web | celery)'; \
    exit 1; \
fi"]
