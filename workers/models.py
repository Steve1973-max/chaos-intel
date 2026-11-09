"""Platform database models for CHAOS-INTEL Phase 5.

Extends the authoritative persistence models in services/application-intelligence
without duplicating existing runs, leases, idempotency records, or audit events.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_APP_INTEL_PATH = Path(__file__).resolve().parents[1] / "services" / "application-intelligence"
if str(_APP_INTEL_PATH) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_PATH))

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from src.execution.persistence.models import Base, utcnow


class ApplicationRegistrationModel(Base):
    """Platform record for registered target applications."""

    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)  # directory, archive, git
    source_location: Mapped[str] = mapped_column(Text, nullable=False)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # SHA-256

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="registered")  # registered, analyzing, analyzed, failed
    metadata_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        Index("idx_app_name", "name"),
        CheckConstraint("status IN ('registered', 'analyzing', 'analyzed', 'failed')", name="check_valid_app_status"),
    )


class JobRecordModel(Base):
    """Authoritative platform record for asynchronous background tasks."""

    __tablename__ = "background_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)

    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="queued")
    # queued, running, completed, failed, cancelled, dead_letter

    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)

    worker_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        Index("idx_job_status_priority", "status", "priority"),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'dead_letter')",
            name="check_valid_job_status",
        ),
    )

