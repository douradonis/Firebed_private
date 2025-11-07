# Dockerfile (βελτιωμένη εκδοχή για Render Free)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Athens

WORKDIR /app

# ΜΟΝΟ τα απαραίτητα runtime deps:
# - libzbar0 (pyzbar), poppler-utils (pdf2image), libjpeg-dev + zlib1g-dev (Pillow)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libzbar0 \
    poppler-utils \
    libjpeg-dev \
    zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*

# Πρώτα τα requirements για caching
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r /app/requirements.txt

# Μετά όλος ο κώδικας
COPY . /app

# Δημιουργία φακέλων runtime (ephemeral fs στο Render)
RUN mkdir -p /app/uploads /app/data && chmod -R 777 /app/uploads /app/data

EXPOSE 5000

# Free tier: 1 worker, 8 threads, logs στο STDOUT
CMD gunicorn app:app \
    --bind 0.0.0.0:${PORT:-5000} \
    --workers 1 --threads 8 --timeout 180 \
    --access-logfile - --error-logfile -
