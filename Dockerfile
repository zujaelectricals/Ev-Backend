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
echo SERVICE_ROLE=$SERVICE_ROLE; \
python --version; \
ls -la; \
python manage.py migrate --noinput || true; \
python manage.py collectstatic --noinput || true; \
echo 'Starting Django development server for debugging'; \
python manage.py runserver 0.0.0.0:8000"]
