FROM python:3.11-slim

# --------------------------------------------------
# Environment
# --------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=ev_backend.settings

# --------------------------------------------------
# Workdir
# --------------------------------------------------
WORKDIR /app

# --------------------------------------------------
# System dependencies
# --------------------------------------------------
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# --------------------------------------------------
# Python dependencies
# --------------------------------------------------
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --default-timeout=300 -r requirements.txt

# --------------------------------------------------
# Project files
# --------------------------------------------------
COPY . .

# --------------------------------------------------
# Non-root user (security best practice)
# --------------------------------------------------
RUN useradd -m django
USER django

# --------------------------------------------------
# Port
# --------------------------------------------------
EXPOSE 8000

# --------------------------------------------------
# Start command
# --------------------------------------------------
CMD ["/bin/sh", "-c", \
     "python manage.py migrate && \
      python manage.py collectstatic --noinput && \
      gunicorn ev_backend.wsgi:application \
      --bind 0.0.0.0:8000 \
      --workers 3"]
