#!/usr/bin/env bash
set -euo pipefail

echo "=========================================================="
echo "  CHAOS-INTEL — Local Production Stack Deployment"
echo "=========================================================="

# 1. Check prerequisites
command -v docker >/dev/null 2>&1 || { echo >&2 "Error: docker is required but not installed."; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo >&2 "Error: docker compose is required."; exit 1; }

# 2. Setup environment
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

# 3. Build & start containers
echo "Building and starting containers in detached mode..."
docker compose up -d --build

# 4. Wait for services
echo "Waiting for health probes..."
timeout 60 bash -c 'until docker compose ps | grep -q "(healthy)"; do sleep 2; done'

echo "=========================================================="
echo "  Deployment Complete!"
echo "  - Web Dashboard:   http://localhost:80"
echo "  - API Gateway:     http://localhost:8000/docs"
echo "  - Health Probe:    http://localhost:8000/api/v1/health"
echo "=========================================================="

