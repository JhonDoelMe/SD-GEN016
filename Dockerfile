# -----------------------------------------------------------------------------
# Stage 1: Build stage (compile native C extensions and install Python packages)
# -----------------------------------------------------------------------------
FROM python:3.14-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Install build tools and libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create isolated virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install python dependencies inside the virtualenv
COPY backend/requirements.txt /build/requirements.txt
RUN pip install --upgrade pip && \
    pip install -r /build/requirements.txt

# -----------------------------------------------------------------------------
# Stage 2: Runtime stage (lean, non-root, no compiler or build headers)
# -----------------------------------------------------------------------------
FROM python:3.14-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Install only essential runtime dependencies (curl for healthcheck, libpq5 for PostgreSQL client, fonts-dejavu-core for Cyrillic PDF)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Create non-privileged system user and group (INF-14)
RUN groupadd -r -g 10001 appuser && \
    useradd -r -u 10001 -g appuser -d /app -s /sbin/nologin appuser

# Copy application source code (owned by root:root, read-only for appuser)
COPY backend /app/backend
COPY frontend /app/frontend
COPY alembic.ini /app/alembic.ini
COPY .env.example /app/.env.example

# Restrict permissions: source code is read-only (755), only uploads and backups are writable (INF-14)
RUN mkdir -p /app/uploads /app/backups && \
    chown -R appuser:appuser /app/uploads /app/backups && \
    chmod 755 /app /app/backend /app/frontend && \
    chmod 775 /app/uploads /app/backups

USER appuser:appuser

EXPOSE 8000

# Startup script: safe Alembic migration and exec Uvicorn as PID 1 with unquoted forwarded-allow-ips (INF-12, INF-13, INF-16)
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips=\"${FORWARDED_ALLOW_IPS:-127.0.0.1,172.16.0.0/12,192.168.0.0/16}\""]
