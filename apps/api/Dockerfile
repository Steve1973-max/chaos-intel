# Production Dockerfile for CHAOS-INTEL FastAPI API Gateway
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt* ./
RUN pip install --upgrade pip && \
    pip install fastapi uvicorn[standard] pydantic starlette sqlalchemy redis psycopg[binary] httpx anyio python-multipart networkx alembic jsonschema referencing

# Copy application code
COPY apps/api /app/apps/api
COPY packages /app/packages
COPY services /app/services
COPY workers /app/workers

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

