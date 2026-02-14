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
# System dependencies (IMPORTANT for Azure SSH)
# --------------------------------------------------
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    ca-certificates \
    bash \
    procps \
    curl \
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
# Non-root user (Azure + security friendly)
# --------------------------------------------------
RUN useradd -m django \
    && chown -R django:django /app
USER django

# --------------------------------------------------
# Port
# --------------------------------------------------
EXPOSE 8000

# --------------------------------------------------
# Startup command
# --------------------------------------------------
CMD ["/bin/bash", "-c", \
     "python manage.py migrate && \
     python manage.py create_admin && \
      python manage.py collectstatic --noinput && \
      gunicorn ev_backend.wsgi:application \
      --bind 0.0.0.0:8000 \
      --workers 3 \
      --timeout 120"]
