# Dockerfile - προτεινόμενο
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps needed for building wheels, pdf/image, zbar (pyzbar), etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    default-libmysqlclient-dev \
    poppler-utils \
    libzbar0 \
    libzbar-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy app
COPY . /app

# If you vendorized mydatanaut under /app/vendor, add it to PYTHONPATH
ENV PYTHONPATH="/app/vendor:${PYTHONPATH}"

# Install python deps
RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /app/requirements.txt

# Create runtime dirs and give wide perms (Render ephemeral container)
RUN mkdir -p /app/uploads /app/data \
    && chmod -R 777 /app/uploads /app/data

# Metadata - optional
EXPOSE 5000

# IMPORTANT: use shell form so $PORT is expanded by /bin/sh -c at container start
# Provide a fallback port for local runs (${PORT:-5000})
CMD gunicorn --bind 0.0.0.0:${PORT:-5000} app:app --workers 3 --threads 4 --timeout 120
