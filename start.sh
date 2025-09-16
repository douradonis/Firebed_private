#!/usr/bin/env bash
set -euo pipefail

: "${PORT:=10000}"

# Run gunicorn (assumes module app:app)
exec gunicorn app:app --bind 0.0.0.0:${PORT} --workers 4 --threads 8 --timeout 120
