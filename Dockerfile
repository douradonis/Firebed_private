# Dockerfile - production-ready for Render (Flask + pdf2image/pyzbar support)
FROM python:3.9-slim

# system packages needed by pdf2image / pyzbar / pillow / build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential poppler-utils libzbar0 libjpeg-dev libpng-dev gcc \
  && rm -rf /var/lib/apt/lists/*

# create non-root user
RUN useradd --create-home --shell /bin/bash myuser

WORKDIR /app

# copy requirements first for caching
COPY requirements.txt /app/requirements.txt

# upgrade pip and install Python deps (includes gunicorn)
RUN pip install --upgrade pip setuptools wheel \
  && pip install --no-cache-dir -r /app/requirements.txt

# copy application files
COPY . /app

# create data folders and set ownership
RUN mkdir -p /app/uploads /app/data \
    && chown -R myuser:myuser /app/uploads /app/data /app

USER myuser

# Ensure PORT environment variable is available when run on Render
ENV PORT 10000
EXPOSE ${PORT}

# Start with gunicorn; assume Flask app object is "app" inside app.py (module: app)
CMD exec gunicorn app:app --bind 0.0.0.0:${PORT} --workers 4 --threads 8 --timeout 120
