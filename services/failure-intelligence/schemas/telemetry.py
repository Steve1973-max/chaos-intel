"""Telemetry models and schemas for CHAOS-INTEL Phase 4."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

MetricCategory = Literal["infrastructure", "application", "resilience"]
MetricType = Literal["gauge", "counter", "histogram"]
LogLevel = Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]
SpanStatus = Literal["OK", "ERROR"]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class NormalizedMetricPoint(BaseModel):
    """Normalized, timestamped metric data point."""

    metric_name: str
    category: MetricCategory
    service_id: str
    timestamp: str = Field(default_factory=utcnow_iso)
    value: float
    unit: str
    attributes: Dict[str, Any] = Field(default_factory=dict)
    imputed: bool = False
    missing: bool = False


class InfrastructureMetrics(BaseModel):
    """Infrastructure-layer metrics snapshot for a component/node."""

    service_id: str
    timestamp: str = Field(default_factory=utcnow_iso)
    cpu_utilization: float = Field(ge=0.0, le=100.0)
    memory_utilization: float = Field(ge=0.0, le=100.0)
    disk_utilization: float = Field(ge=0.0, le=100.0)
    disk_io_read_bytes_sec: float = Field(default=0.0, ge=0.0)
    disk_io_write_bytes_sec: float = Field(default=0.0, ge=0.0)
    network_throughput_rx_bytes_sec: float = Field(default=0.0, ge=0.0)
    network_throughput_tx_bytes_sec: float = Field(default=0.0, ge=0.0)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class ApplicationMetrics(BaseModel):
    """Application-layer service performance metrics snapshot."""

    service_id: str
    timestamp: str = Field(default_factory=utcnow_iso)
    request_rate: float = Field(default=0.0, ge=0.0)
    response_latency_p50_ms: float = Field(default=0.0, ge=0.0)
    response_latency_p95_ms: float = Field(default=0.0, ge=0.0)
    response_latency_p99_ms: float = Field(default=0.0, ge=0.0)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    http_status_distribution: Dict[str, int] = Field(default_factory=dict)
    service_availability: float = Field(default=1.0, ge=0.0, le=1.0)
    db_connection_health: Dict[str, Any] = Field(default_factory=dict)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class ResilienceMetrics(BaseModel):
    """Fault recovery and system resilience metrics."""

    service_id: str
    timestamp: str = Field(default_factory=utcnow_iso)
    recovery_time_ms: Optional[float] = None
    failure_duration_ms: Optional[float] = None
    failed_dependency_count: int = Field(default=0, ge=0)
    degradation_severity: str = "low"
    experiment_impact_score: float = Field(default=0.0, ge=0.0, le=1.0)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class StructuredLogEntry(BaseModel):
    """Structured log record with correlation and tracing context."""

    log_id: str
    timestamp: str = Field(default_factory=utcnow_iso)
    service_id: str
    level: LogLevel
    message: str
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    correlation_id: Optional[str] = None
    error_type: Optional[str] = None
    stack_trace: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)


class TraceSpan(BaseModel):
    """Distributed tracing span record."""

    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    service_id: str
    operation_name: str
    start_time: str
    end_time: str
    duration_ms: float = Field(ge=0.0)
    status_code: SpanStatus = "OK"
    attributes: Dict[str, Any] = Field(default_factory=dict)
    events: List[Dict[str, Any]] = Field(default_factory=list)

