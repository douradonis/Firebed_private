# Dockerfile - production-ready for Render
FROM python:3.9-slim

# System deps for pdf2image / pyzbar (optional) - safe / small
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential poppler-utils libzbar0 libjpeg-dev libpng-dev gcc \
  && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash myuser

WORKDIR /app

# copy requirements first for layer caching
COPY requirements.txt /app/requirements.txt

# install python deps
RUN pip install --upgrade pip setuptools wheel \
  && pip install --no-cache-dir -r /app/requirements.txt

# copy app
COPY . /app

# make upload / data dirs and set permissions for myuser
RUN mkdir -p /app/uploads /app/data \
    && chown -R myuser:myuser /app/uploads /app/data /app

USER myuser

# Expose dynamic port (Render injects $PORT env)
ENV PORT 10000
EXPOSE ${PORT}

# Start command - gunicorn will bind to $PORT
# Make sure your Flask app object is named "app" and file is app.py
CMD exec gunicorn app:app --bind 0.0.0.0:${PORT} --workers 4 --threads 8 --timeout 120
