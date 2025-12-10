#!/bin/sh
# Entrypoint script for Docker container
# Runs database migrations before starting the server

set -e

echo "Running database migrations..."
python scripts/migrate.py

echo "Starting Gunicorn server..."
exec gunicorn run:app --bind 0.0.0.0:8080 --workers 2 --timeout 120
