# CHAOS-INTEL Setup & Local Development Guide

## Prerequisites
- Python 3.12+ (or Python 3.14)
- Node.js 20+ & npm 10+
- Docker & Docker Compose (optional for containerized deployment)

---

## Local Development Setup

### 1. Python Backend & Services
```bash
# Clone repository
git clone https://github.com/example/chaos-intel.git
cd chaos-intel

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install platform packages
pip install --upgrade pip
pip install fastapi "uvicorn[standard]" pydantic starlette sqlalchemy redis psycopg[binary] httpx anyio pytest pytest-asyncio
```

### 2. Frontend Web Dashboard
```bash
cd apps/web
npm install
npm run dev
# Starts local Vite development server on http://localhost:3000
```

### 3. Running FastAPI Platform Gateway
```bash
# From repository root:
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
# API Gateway available on http://127.0.0.1:8000
# OpenAPI Docs on http://127.0.0.1:8000/docs
```

---

## Docker Compose Production Stack
```bash
# Copy environment configuration
cp .env.example .env

# Start all containers in background
docker compose up -d --build

# Verify health probes
docker compose ps
```
- Dashboard UI: `http://localhost:80`
- API Gateway: `http://localhost:8000/docs`
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

