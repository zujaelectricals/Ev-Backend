FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DJANGO_SETTINGS_MODULE=ev_backend.settings

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y ca-certificates

COPY requirements.txt /app/
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --default-timeout=300 -r requirements.txt


COPY . /app/



RUN useradd -m django
USER django

EXPOSE 8000


CMD ["/bin/sh","-c","python manage.py migrate && python manage.py collectstatic --noinput && gunicorn --bind 0.0.0.0:8000 --workers 3 ev_backend.wsgi:application"]
