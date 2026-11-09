# Production Dockerfile for CHAOS-INTEL Distributed Background Worker
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip && \
    pip install fastapi uvicorn pydantic starlette sqlalchemy redis psycopg[binary] httpx anyio python-multipart networkx alembic jsonschema referencing pyyaml

COPY packages /app/packages
COPY services /app/services
COPY workers /app/workers
COPY apps/api /app/apps/api

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import workers.worker; print('ok')" || exit 1

CMD ["python", "-m", "workers.worker"]

