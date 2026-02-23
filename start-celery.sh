#!/bin/sh
set -e

echo "Starting Celery worker..."
exec python -m celery worker -A ev_backend --loglevel=info --pool=solo
