FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /app/backend/requirements.txt

# Copy application source code
COPY backend /app/backend
COPY frontend /app/frontend
COPY alembic.ini /app/alembic.ini
COPY .env.example /app/.env.example

# Create directory for persistent uploads
RUN mkdir -p /app/uploads

EXPOSE 8000

# Startup script: apply migrations and start uvicorn (restricted proxy headers to internal Docker/private ranges)
CMD ["sh", "-c", "alembic upgrade head && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16'"]
