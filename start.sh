#!/usr/bin/env bash
set -e
# use env var PORT or default 10000
PORT="${PORT:-10000}"
exec gunicorn app:app --bind 0.0.0.0:${PORT} --workers 4 --threads 8 --timeout 120
