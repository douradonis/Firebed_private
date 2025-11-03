FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Minimal system deps (no zbar). Keep poppler for pdf2image.
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends build-essential git libpq-dev libffi-dev libssl-dev poppler-utils libjpeg-dev zlib1g-dev && rm -rf /var/lib/apt/lists/*

COPY . /app

ENV PYTHONPATH="/app/vendor:${PYTHONPATH}"
RUN pip install --upgrade pip setuptools wheel && pip install --no-cache-dir -r /app/requirements.txt

EXPOSE 5000
CMD gunicorn --bind 0.0.0.0:${PORT:-5000} app:app --workers 3 --threads 4 --timeout 120
