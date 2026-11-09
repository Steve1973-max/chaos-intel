"""Metrics collector and normalizer for CHAOS-INTEL Phase 4."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from schemas.telemetry import (
    ApplicationMetrics,
    InfrastructureMetrics,
    NormalizedMetricPoint,
    ResilienceMetrics,
    utcnow_iso,
)


class TelemetryCollector:
    """Collects and normalizes infrastructure, application, and resilience metrics."""

    METRIC_UNITS: Dict[str, str] = {
        # Infrastructure
        "infra.cpu_utilization": "%",
        "infra.memory_utilization": "%",
        "infra.disk_utilization": "%",
        "infra.disk_io_read_bytes_sec": "bytes/sec",
        "infra.disk_io_write_bytes_sec": "bytes/sec",
        "infra.network_throughput_rx_bytes_sec": "bytes/sec",
        "infra.network_throughput_tx_bytes_sec": "bytes/sec",
        # Application
        "app.request_rate": "req/sec",
        "app.response_latency_p50_ms": "ms",
        "app.response_latency_p95_ms": "ms",
        "app.response_latency_p99_ms": "ms",
        "app.error_rate": "1",
        "app.service_availability": "1",
        # Resilience
        "resilience.recovery_time_ms": "ms",
        "resilience.failure_duration_ms": "ms",
        "resilience.failed_dependency_count": "count",
        "resilience.experiment_impact_score": "1",
    }

    def normalize_infrastructure(self, m: InfrastructureMetrics) -> List[NormalizedMetricPoint]:
        """Convert infrastructure snapshot into individual normalized time-series points."""
        ts = m.timestamp or utcnow_iso()
        sid = m.service_id
        attrs = dict(m.attributes)

        return [
            NormalizedMetricPoint(
                metric_name="infra.cpu_utilization",
                category="infrastructure",
                service_id=sid,
                timestamp=ts,
                value=float(m.cpu_utilization),
                unit="%",
                attributes=attrs,
            ),
            NormalizedMetricPoint(
                metric_name="infra.memory_utilization",
                category="infrastructure",
                service_id=sid,
                timestamp=ts,
                value=float(m.memory_utilization),
                unit="%",
                attributes=attrs,
            ),
            NormalizedMetricPoint(
                metric_name="infra.disk_utilization",
                category="infrastructure",
                service_id=sid,
                timestamp=ts,
                value=float(m.disk_utilization),
                unit="%",
                attributes=attrs,
            ),
            NormalizedMetricPoint(
                metric_name="infra.disk_io_read_bytes_sec",
                category="infrastructure",
                service_id=sid,
                timestamp=ts,
                value=float(m.disk_io_read_bytes_sec),
                unit="bytes/sec",
                attributes=attrs,
            ),
            NormalizedMetricPoint(
                metric_name="infra.disk_io_write_bytes_sec",
                category="infrastructure",
                service_id=sid,
                timestamp=ts,
                value=float(m.disk_io_write_bytes_sec),
                unit="bytes/sec",
                attributes=attrs,
            ),
            NormalizedMetricPoint(
                metric_name="infra.network_throughput_rx_bytes_sec",
                category="infrastructure",
                service_id=sid,
                timestamp=ts,
                value=float(m.network_throughput_rx_bytes_sec),
                unit="bytes/sec",
                attributes=attrs,
            ),
            NormalizedMetricPoint(
                metric_name="infra.network_throughput_tx_bytes_sec",
                category="infrastructure",
                service_id=sid,
                timestamp=ts,
                value=float(m.network_throughput_tx_bytes_sec),
                unit="bytes/sec",
                attributes=attrs,
            ),
        ]

    def normalize_application(self, m: ApplicationMetrics) -> List[NormalizedMetricPoint]:
        """Convert application snapshot into individual normalized time-series points."""
        ts = m.timestamp or utcnow_iso()
        sid = m.service_id
        attrs = {**m.attributes, "http_status_distribution": m.http_status_distribution}

        return [
            NormalizedMetricPoint(
                metric_name="app.request_rate",
                category="application",
                service_id=sid,
                timestamp=ts,
                value=float(m.request_rate),
                unit="req/sec",
                attributes=attrs,
            ),
            NormalizedMetricPoint(
                metric_name="app.response_latency_p50_ms",
                category="application",
                service_id=sid,
                timestamp=ts,
                value=float(m.response_latency_p50_ms),
                unit="ms",
                attributes=attrs,
            ),
            NormalizedMetricPoint(
                metric_name="app.response_latency_p95_ms",
                category="application",
                service_id=sid,
                timestamp=ts,
                value=float(m.response_latency_p95_ms),
                unit="ms",
                attributes=attrs,
            ),
            NormalizedMetricPoint(
                metric_name="app.response_latency_p99_ms",
                category="application",
                service_id=sid,
                timestamp=ts,
                value=float(m.response_latency_p99_ms),
                unit="ms",
                attributes=attrs,
            ),
            NormalizedMetricPoint(
                metric_name="app.error_rate",
                category="application",
                service_id=sid,
                timestamp=ts,
                value=float(m.error_rate),
                unit="1",
                attributes=attrs,
            ),
            NormalizedMetricPoint(
                metric_name="app.service_availability",
                category="application",
                service_id=sid,
                timestamp=ts,
                value=float(m.service_availability),
                unit="1",
                attributes=attrs,
            ),
        ]

    def normalize_resilience(self, m: ResilienceMetrics) -> List[NormalizedMetricPoint]:
        """Convert resilience snapshot into individual normalized time-series points."""
        ts = m.timestamp or utcnow_iso()
        sid = m.service_id
        attrs = {**m.attributes, "degradation_severity": m.degradation_severity}
        points: List[NormalizedMetricPoint] = [
            NormalizedMetricPoint(
                metric_name="resilience.failed_dependency_count",
                category="resilience",
                service_id=sid,
                timestamp=ts,
                value=float(m.failed_dependency_count),
                unit="count",
                attributes=attrs,
            ),
            NormalizedMetricPoint(
                metric_name="resilience.experiment_impact_score",
                category="resilience",
                service_id=sid,
                timestamp=ts,
                value=float(m.experiment_impact_score),
                unit="1",
                attributes=attrs,
            ),
        ]

        if m.recovery_time_ms is not None:
            points.append(
                NormalizedMetricPoint(
                    metric_name="resilience.recovery_time_ms",
                    category="resilience",
                    service_id=sid,
                    timestamp=ts,
                    value=float(m.recovery_time_ms),
                    unit="ms",
                    attributes=attrs,
                )
            )

        if m.failure_duration_ms is not None:
            points.append(
                NormalizedMetricPoint(
                    metric_name="resilience.failure_duration_ms",
                    category="resilience",
                    service_id=sid,
                    timestamp=ts,
                    value=float(m.failure_duration_ms),
                    unit="ms",
                    attributes=attrs,
                )
            )

        return points

