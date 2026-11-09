"""Service and dependency health monitoring for CHAOS-INTEL Phase 4."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

HealthStatus = Literal["HEALTHY", "DEGRADED", "UNHEALTHY", "UNKNOWN"]


class ServiceHealthSnapshot(BaseModel):
    """Health status and summary metrics for a service."""

    service_id: str
    status: HealthStatus
    health_score: float = Field(ge=0.0, le=1.0)
    availability_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    latency_p95_ms: float = Field(default=0.0, ge=0.0)
    failed_dependencies: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)


class DependencyHealthSnapshot(BaseModel):
    """Health status between a source caller and target dependency."""

    source_service_id: str
    target_service_id: str
    status: HealthStatus
    healthy: bool = True
    consecutive_failures: int = 0
    latency_ms: float = 0.0
    error_message: Optional[str] = None


class HealthMonitor:
    """Monitors service and dependency health against resilience thresholds."""

    def __init__(
        self,
        error_rate_degraded_threshold: float = 0.05,
        error_rate_unhealthy_threshold: float = 0.20,
        availability_degraded_threshold: float = 0.98,
        availability_unhealthy_threshold: float = 0.90,
        latency_p95_degraded_ms: float = 1000.0,
        latency_p95_unhealthy_ms: float = 3000.0,
    ) -> None:
        self.err_deg = error_rate_degraded_threshold
        self.err_unh = error_rate_unhealthy_threshold
        self.avail_deg = availability_degraded_threshold
        self.avail_unh = availability_unhealthy_threshold
        self.lat_deg = latency_p95_degraded_ms
        self.lat_unh = latency_p95_unhealthy_ms

    def evaluate_service_health(
        self,
        service_id: str,
        availability: float = 1.0,
        error_rate: float = 0.0,
        latency_p95_ms: float = 0.0,
        failed_dependencies: Optional[List[str]] = None,
    ) -> ServiceHealthSnapshot:
        """Evaluate service health status and compute health score [0.0..1.0]."""
        failed_deps = failed_dependencies or []
        reasons: List[str] = []
        is_unhealthy = False
        is_degraded = False

        if error_rate >= self.err_unh:
            is_unhealthy = True
            reasons.append(f"Error rate {error_rate:.2%} exceeds unhealthy threshold {self.err_unh:.2%}")
        elif error_rate >= self.err_deg:
            is_degraded = True
            reasons.append(f"Error rate {error_rate:.2%} exceeds degraded threshold {self.err_deg:.2%}")

        if availability <= self.avail_unh:
            is_unhealthy = True
            reasons.append(f"Availability {availability:.2%} below unhealthy threshold {self.avail_unh:.2%}")
        elif availability <= self.avail_deg:
            is_degraded = True
            reasons.append(f"Availability {availability:.2%} below degraded threshold {self.avail_deg:.2%}")

        if latency_p95_ms >= self.lat_unh:
            is_unhealthy = True
            reasons.append(f"P95 latency {latency_p95_ms:.1f}ms exceeds unhealthy threshold {self.lat_unh}ms")
        elif latency_p95_ms >= self.lat_deg:
            is_degraded = True
            reasons.append(f"P95 latency {latency_p95_ms:.1f}ms exceeds degraded threshold {self.lat_deg}ms")

        if len(failed_deps) > 0:
            is_degraded = True
            reasons.append(f"Failed downstream dependencies: {failed_deps}")

        status: HealthStatus
        if is_unhealthy:
            status = "UNHEALTHY"
        elif is_degraded:
            status = "DEGRADED"
        else:
            status = "HEALTHY"

        # Compute composite health score: availability (50%), error rate (30%), latency factor (20%)
        lat_score = max(0.0, min(1.0, 1.0 - (latency_p95_ms / max(1.0, self.lat_unh))))
        err_score = max(0.0, 1.0 - (error_rate / max(0.01, self.err_unh)))
        avail_score = max(0.0, min(1.0, availability))
        score = round((0.5 * avail_score) + (0.3 * err_score) + (0.2 * lat_score), 3)

        return ServiceHealthSnapshot(
            service_id=service_id,
            status=status,
            health_score=score,
            availability_ratio=availability,
            error_rate=error_rate,
            latency_p95_ms=latency_p95_ms,
            failed_dependencies=failed_deps,
            reasons=reasons,
        )

