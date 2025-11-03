# Dockerfile - no zbar needed (fallback uses OpenCV)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (no zbar). Keep poppler for pdf2image.
RUN apt-get update && apt-get install -y --no-install-recommends \    build-essential \    git \    libpq-dev \    libffi-dev \    libssl-dev \    default-libmysqlclient-dev \    poppler-utils \    libjpeg-dev \    zlib1g-dev \    libopenblas-dev \    && rm -rf /var/lib/apt/lists/*

# Copy app
COPY . /app

# Optional: vendor path
ENV PYTHONPATH="/app/vendor:${PYTHONPATH}"

# Install python deps
RUN pip install --upgrade pip setuptools wheel \    && pip install --no-cache-dir -r /app/requirements.txt

# Runtime dirs
RUN mkdir -p /app/uploads /app/data \    && chmod -R 777 /app/uploads /app/data

EXPOSE 5000

# Use shell form so $PORT is expanded at runtime
CMD gunicorn --bind 0.0.0.0:${PORT:-5000} app:app --workers 3 --threads 4 --timeout 120
