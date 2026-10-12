from typing import Optional, Dict, Any
from datetime import datetime, timezone
import uuid
from sqlalchemy import String, Integer, DateTime, JSON, ForeignKey, UniqueConstraint, Index, CheckConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

def utcnow():
    return datetime.now(timezone.utc)

class ExperimentRunModel(Base):
    __tablename__ = "experiment_runs"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    application_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    experiment_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    safety_decision_id: Mapped[str] = mapped_column(String, nullable=False)
    approval_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    state: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    
    correlation_id: Mapped[str] = mapped_column(String, nullable=False)
    metadata_payload: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    
    __table_args__ = (
        CheckConstraint('version > 0', name='check_version_positive'),
    )

class RunTransitionHistoryModel(Base):
    __tablename__ = "run_transitions"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("experiment_runs.id"), nullable=False, index=True)
    
    previous_state: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    new_state: Mapped[str] = mapped_column(String, nullable=False)
    
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    new_version: Mapped[int] = mapped_column(Integer, nullable=False)
    
    actor: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    correlation_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    causation_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    
    __table_args__ = (
        UniqueConstraint("run_id", "new_version", name="uq_run_transition_version"),
        CheckConstraint('new_version > expected_version', name='check_version_increment'),
    )

class IdempotencyRecordModel(Base):
    __tablename__ = "idempotency_records"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    application_id: Mapped[str] = mapped_column(String, nullable=False)
    operation_scope: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key_digest: Mapped[str] = mapped_column(String, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    
    owner_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="in_progress") # in_progress, completed
    
    terminal_result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    uncertain_outcome: Mapped[bool] = mapped_column(Integer, default=0, nullable=False) # 1 for True, 0 for False (using int for bool compat)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    __table_args__ = (
        UniqueConstraint("application_id", "operation_scope", "idempotency_key_digest", name="uq_idempotency_scope"),
        Index("idx_idempotency_lookup", "application_id", "operation_scope", "idempotency_key_digest"),
        CheckConstraint("status IN ('in_progress', 'completed')", name='check_valid_idempotency_status'),
    )

class LeaseRecordModel(Base):
    __tablename__ = "leases"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    resource_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String, nullable=False)
    
    status: Mapped[str] = mapped_column(String, nullable=False, default="active") # active, released, expired
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    __table_args__ = (
        CheckConstraint('fencing_token > 0', name='check_fencing_token_positive'),
        CheckConstraint('version > 0', name='check_lease_version_positive'),
        CheckConstraint("status IN ('active', 'released', 'expired')", name='check_valid_lease_status'),
    )

class AuditEventModel(Base):
    __tablename__ = "audit_events"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("experiment_runs.id"), index=True, nullable=True)
    application_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    experiment_id: Mapped[Optional[str]] = mapped_column(String, index=True, nullable=True)
    
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    
    previous_state: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    current_state: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    correlation_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    causation_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    
    redacted_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    
    __table_args__ = (
        Index("idx_audit_run", "run_id"),
    )

class OutboxEventModel(Base):
    __tablename__ = "transactional_outbox"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    delivery_status: Mapped[str] = mapped_column(String, nullable=False, default="pending") # pending, delivered, failed
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    
    __table_args__ = (
        Index("idx_outbox_status", "delivery_status"),
        CheckConstraint("delivery_status IN ('pending', 'delivered', 'failed')", name='check_valid_delivery_status'),
    )
