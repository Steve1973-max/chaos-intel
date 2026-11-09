"""API Gateway configuration for CHAOS-INTEL Phase 5 & 7."""

from __future__ import annotations

import os
from pydantic import BaseModel, Field


class ApiConfig(BaseModel):
    """Central configuration for FastAPI Gateway."""

    api_prefix: str = "/api/v1"
    environment: str = os.environ.get("ENVIRONMENT", "development")
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")

    # Security & Auth
    api_key_header: str = "X-API-Key"
    jwt_secret: str = os.environ.get("JWT_SECRET", "chaos-intel-secret-key-change-in-prod")
    admin_api_keys: list[str] = Field(default_factory=lambda: ["admin-key-supersecret", "test-admin-key"])
    operator_api_keys: list[str] = Field(default_factory=lambda: ["operator-key-secret", "test-operator-key"])
    viewer_api_keys: list[str] = Field(default_factory=lambda: ["viewer-key-public", "test-viewer-key"])

    # CORS Configuration
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:80",
            "http://127.0.0.1:80",
        ]
    )

    # File Upload & Archive Security Limits
    max_upload_size_bytes: int = 50 * 1024 * 1024  # 50 MB
    max_uncompressed_bytes: int = 150 * 1024 * 1024  # 150 MB (Zip-bomb defense)
    max_archive_files: int = 500  # Max file count inside archive
    allowed_archive_extensions: set[str] = Field(
        default_factory=lambda: {".zip", ".tar.gz", ".tgz", ".tar"}
    )
    upload_staging_dir: str = os.environ.get("UPLOAD_DIR", "staging_uploads")

    # Database & Redis
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./chaos_intel_platform.db")
    redis_url: str = os.environ.get("REDIS_URL", "redis://localhost:6379")

    # Rate Limiting & Concurrency
    rate_limit_requests_per_minute: int = 180
    max_concurrent_pipelines: int = 10
    default_page_limit: int = 20
    max_page_limit: int = 100


config = ApiConfig()
