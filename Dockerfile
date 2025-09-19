FROM python:3.9-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps needed for pandas/openpyxl and building wheels
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    libffi-dev \
    libssl-dev \
    default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy app
COPY . /app

# Ensure vendor path presence (if you vendorized mydatanaut under /app/vendor)
ENV PYTHONPATH="/app/vendor:${PYTHONPATH}"

# Install python deps
RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r /app/requirements.txt

# Create runtime dirs
RUN mkdir -p /app/uploads /app/data
RUN chmod -R 777 /app/uploads /app/data

# Expose
EXPOSE 5000

# Use gunicorn in production (Render will set $PORT env)
CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "app:app", "--workers", "3", "--threads", "4"]
