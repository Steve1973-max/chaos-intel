"""Common API schemas for pagination, errors, and health."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PaginatedResponse(BaseModel, Generic[T]):
    """Standardized envelope for paginated collections."""

    items: List[T]
    total: int
    limit: int
    offset: int
    has_more: bool


class ErrorResponse(BaseModel):
    """Standardized error envelope."""

    error_code: str
    message: str
    correlation_id: str
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=utcnow_iso)


class HealthResponse(BaseModel):
    """Platform health status."""

    status: str  # HEALTHY, DEGRADED, UNHEALTHY
    version: str = "1.0.0"
    environment: str
    timestamp: str = Field(default_factory=utcnow_iso)
    services: Dict[str, Any] = Field(default_factory=dict)

