# Local deployment script for Windows PowerShell
$ErrorActionPreference = "Stop"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  CHAOS-INTEL — Local Production Stack Deployment" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Check prerequisites
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker is required but not installed or not in PATH."
    exit 1
}

# 2. Setup environment
if (-not (Test-Path .env)) {
    Write-Host "Creating .env from .env.example..." -ForegroundColor Yellow
    Copy-Item .env.example .env
}

# 3. Build & start containers
Write-Host "Building and starting containers..." -ForegroundColor Green
docker compose up -d --build

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "  Deployment initiated." -ForegroundColor Cyan
Write-Host "  - Web Dashboard:   http://localhost:80"
Write-Host "  - API Gateway:     http://localhost:8000/docs"
Write-Host "  - Health Probe:    http://localhost:8000/api/v1/health"
Write-Host "==========================================================" -ForegroundColor Cyan

