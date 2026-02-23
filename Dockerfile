FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=ev_backend.settings

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    ca-certificates \
    bash \
    procps \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --default-timeout=300 -r requirements.txt

COPY . .

RUN useradd -m django && chown -R django:django /app
USER django

EXPOSE 8000

CMD ["/bin/bash", "-c", "\
if [ \"$SERVICE_ROLE\" = \"web\" ]; then \
    echo 'Starting Django Web (Gunicorn)' && \
    python manage.py migrate && \
    python manage.py collectstatic --noinput && \
    gunicorn ev_backend.wsgi:application \
        --bind 0.0.0.0:8000 \
        --workers 3 \
        --timeout 120 ; \
elif [ \"$SERVICE_ROLE\" = \"celery\" ]; then \
    echo 'Starting Celery Worker' && \
    celery -A ev_backend worker --loglevel=info --concurrency=2 ; \
else \
    echo 'ERROR: SERVICE_ROLE not set (web | celery)' && exit 1 ; \
fi"]
