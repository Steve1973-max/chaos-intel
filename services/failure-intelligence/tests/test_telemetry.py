"""Tests for Telemetry Ingestion, Normalization, Time-Series, and Exporters."""

from __future__ import annotations

import math
import sys
from pathlib import Path
import pytest

_FI_ROOT = Path(__file__).resolve().parents[1]
_APP_INTEL_ROOT = Path(__file__).resolve().parents[2] / "application-intelligence"

for p in (_FI_ROOT, _APP_INTEL_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from schemas.telemetry import (
    ApplicationMetrics,
    InfrastructureMetrics,
    NormalizedMetricPoint,
    ResilienceMetrics,
    StructuredLogEntry,
    TraceSpan,
)
from telemetry.collector import TelemetryCollector
from telemetry.exporters import TelemetryExporters
from telemetry.health_monitor import HealthMonitor
from telemetry.ingestor import TelemetryIngestor
from telemetry.logs import LogProcessor
from telemetry.timeseries import TimeSeriesProcessor
from telemetry.tracing import TraceProcessor


def test_telemetry_normalization_infrastructure():
    collector = TelemetryCollector()
    infra = InfrastructureMetrics(
        service_id="srv-order",
        cpu_utilization=78.5,
        memory_utilization=62.0,
        disk_utilization=45.0,
        disk_io_read_bytes_sec=1048576.0,
        disk_io_write_bytes_sec=524288.0,
        network_throughput_rx_bytes_sec=204800.0,
        network_throughput_tx_bytes_sec=102400.0,
    )
    points = collector.normalize_infrastructure(infra)
    assert len(points) == 7

    names = {p.metric_name for p in points}
    assert "infra.cpu_utilization" in names
    assert "infra.memory_utilization" in names
    assert "infra.disk_io_read_bytes_sec" in names

    cpu_pt = next(p for p in points if p.metric_name == "infra.cpu_utilization")
    assert cpu_pt.value == 78.5
    assert cpu_pt.unit == "%"
    assert cpu_pt.category == "infrastructure"
    assert cpu_pt.service_id == "srv-order"


def test_telemetry_normalization_application_and_resilience():
    collector = TelemetryCollector()
    app_m = ApplicationMetrics(
        service_id="srv-cart",
        request_rate=250.0,
        response_latency_p50_ms=45.0,
        response_latency_p95_ms=180.0,
        response_latency_p99_ms=350.0,
        error_rate=0.02,
        http_status_distribution={"2xx": 245, "5xx": 5},
        service_availability=0.98,
    )
    points = collector.normalize_application(app_m)
    assert len(points) == 6

    err_pt = next(p for p in points if p.metric_name == "app.error_rate")
    assert err_pt.value == 0.02
    assert err_pt.unit == "1"

    res_m = ResilienceMetrics(
        service_id="srv-cart",
        recovery_time_ms=1200.0,
        failure_duration_ms=4500.0,
        failed_dependency_count=1,
        degradation_severity="medium",
        experiment_impact_score=0.45,
    )
    res_points = collector.normalize_resilience(res_m)
    assert len(res_points) == 4
    rec_pt = next(p for p in res_points if p.metric_name == "resilience.recovery_time_ms")
    assert rec_pt.value == 1200.0


def test_missing_data_handling_strategies():
    """Verify missing telemetry is never silently invented, and imputation is flagged explicitly."""
    # Data points at T=0, T=1, [missing T=2, T=3], T=4
    pts = [
        NormalizedMetricPoint(
            metric_name="app.latency_p95_ms",
            category="application",
            service_id="srv-pay",
            timestamp="2026-11-05T12:00:00+00:00",
            value=100.0,
            unit="ms",
        ),
        NormalizedMetricPoint(
            metric_name="app.latency_p95_ms",
            category="application",
            service_id="srv-pay",
            timestamp="2026-11-05T12:00:01+00:00",
            value=110.0,
            unit="ms",
        ),
        NormalizedMetricPoint(
            metric_name="app.latency_p95_ms",
            category="application",
            service_id="srv-pay",
            timestamp="2026-11-05T12:00:04+00:00",
            value=200.0,
            unit="ms",
        ),
    ]

    # 1. Drop strategy: only keeps observed buckets
    dropped = TimeSeriesProcessor.resample_and_align(pts, bucket_seconds=1.0, missing_strategy="drop")
    assert len(dropped) == 3
    assert all(not p.imputed for p in dropped)

    # 2. Explicit marker: inserts NaN with missing=True
    marked = TimeSeriesProcessor.resample_and_align(pts, bucket_seconds=1.0, missing_strategy="explicit_marker")
    assert len(marked) == 5
    missing_items = [p for p in marked if p.missing]
    assert len(missing_items) == 2
    assert math.isnan(missing_items[0].value)

    # 3. Forward fill: repeats last value and flags imputed=True
    ffill = TimeSeriesProcessor.resample_and_align(pts, bucket_seconds=1.0, missing_strategy="forward_fill")
    assert len(ffill) == 5
    imputed_ffill = [p for p in ffill if p.imputed]
    assert len(imputed_ffill) == 2
    assert imputed_ffill[0].value == 110.0
    assert imputed_ffill[1].value == 110.0

    # 4. Linear interpolation: estimates trend and flags imputed=True
    interp = TimeSeriesProcessor.resample_and_align(pts, bucket_seconds=1.0, missing_strategy="linear_interpolate")
    assert len(interp) == 5
    imputed_interp = [p for p in interp if p.imputed]
    assert len(imputed_interp) == 2
    # Step from 110 to 200 over 3 intervals -> 140.0, 170.0
    assert imputed_interp[0].value == 140.0
    assert imputed_interp[1].value == 170.0


def test_time_series_aggregations():
    vals = [10.0, 20.0, 30.0, 40.0, 100.0]
    assert TimeSeriesProcessor.aggregate_points(vals, "mean") == 40.0
    assert TimeSeriesProcessor.aggregate_points(vals, "max") == 100.0
    assert TimeSeriesProcessor.aggregate_points(vals, "min") == 10.0
    assert TimeSeriesProcessor.aggregate_points(vals, "count") == 5.0
    assert TimeSeriesProcessor.aggregate_points(vals, "last") == 100.0
    assert TimeSeriesProcessor.aggregate_points(vals, "p95") == 100.0


def test_structured_log_processor():
    raw_json = '{"level": "ERROR", "message": "ConnectionRefusedError: Database pool exhausted", "service_id": "srv-order", "trace_id": "tr-001"}'
    log1 = LogProcessor.parse_entry(raw_json)
    assert log1.level == "ERROR"
    assert log1.service_id == "srv-order"
    assert log1.trace_id == "tr-001"
    assert log1.error_type == "ConnectionRefusedError"

    raw_text = "FATAL: OutOfMemoryError in worker thread"
    log2 = LogProcessor.parse_entry(raw_text, default_service_id="srv-web")
    assert log2.level == "FATAL"
    assert log2.service_id == "srv-web"
    assert log2.error_type == "OutOfMemoryError"

    filtered = LogProcessor.filter_errors([log1, log2])
    assert len(filtered) == 2


def test_distributed_trace_processing():
    processor = TraceProcessor()
    spans = [
        TraceSpan(
            trace_id="tr-abc",
            span_id="span-root",
            parent_span_id=None,
            service_id="srv-frontend",
            operation_name="GET /checkout",
            start_time="2026-11-05T12:00:00.000Z",
            end_time="2026-11-05T12:00:01.500Z",
            duration_ms=1500.0,
            status_code="ERROR",
        ),
        TraceSpan(
            trace_id="tr-abc",
            span_id="span-order",
            parent_span_id="span-root",
            service_id="srv-order",
            operation_name="POST /orders",
            start_time="2026-11-05T12:00:00.100Z",
            end_time="2026-11-05T12:00:01.400Z",
            duration_ms=1300.0,
            status_code="ERROR",
        ),
        TraceSpan(
            trace_id="tr-abc",
            span_id="span-db",
            parent_span_id="span-order",
            service_id="srv-db",
            operation_name="SQL INSERT orders",
            start_time="2026-11-05T12:00:00.200Z",
            end_time="2026-11-05T12:00:01.350Z",
            duration_ms=1150.0,
            status_code="ERROR",
        ),
    ]
    processor.ingest_spans(spans)

    tree = processor.get_trace("tr-abc")
    assert tree is not None
    assert tree.root_span.span_id == "span-root"
    assert tree.total_duration_ms == 1500.0
    assert len(tree.error_spans) == 3
    assert tree.services_involved == ["srv-db", "srv-frontend", "srv-order"]
    assert tree.get_service_call_sequence() == ["srv-frontend", "srv-order", "srv-db"]
    assert tree.find_slowest_span().span_id == "span-root"


def test_health_monitor_service_evaluation():
    monitor = HealthMonitor()

    # Healthy
    h1 = monitor.evaluate_service_health(service_id="srv-order", availability=0.999, error_rate=0.001, latency_p95_ms=120.0)
    assert h1.status == "HEALTHY"
    assert h1.health_score >= 0.95

    # Degraded due to elevated latency
    h2 = monitor.evaluate_service_health(service_id="srv-order", availability=0.995, error_rate=0.02, latency_p95_ms=1500.0)
    assert h2.status == "DEGRADED"
    assert any("latency" in r for r in h2.reasons)

    # Unhealthy due to high error rate
    h3 = monitor.evaluate_service_health(service_id="srv-order", availability=0.85, error_rate=0.35, latency_p95_ms=4000.0)
    assert h3.status == "UNHEALTHY"
    assert h3.health_score < 0.50


def test_telemetry_exporters():
    pts = [
        NormalizedMetricPoint(
            metric_name="app.error_rate",
            category="application",
            service_id="srv-order",
            timestamp="2026-11-05T12:00:00+00:00",
            value=0.15,
            unit="1",
        )
    ]
    spans = [
        TraceSpan(
            trace_id="tr-100",
            span_id="sp-100",
            service_id="srv-order",
            operation_name="checkout",
            start_time="2026-11-05T12:00:00Z",
            end_time="2026-11-05T12:00:01Z",
            duration_ms=1000.0,
            status_code="OK",
        )
    ]

    # Prometheus
    prom = TelemetryExporters.to_prometheus_text(pts)
    assert "app_error_rate" in prom
    assert 'service="srv-order"' in prom
    assert "0.15" in prom

    # OpenTelemetry OTLP JSON
    otlp = TelemetryExporters.to_opentelemetry_otlp(pts, spans)
    assert "resourceMetrics" in otlp
    assert "resourceSpans" in otlp

    # Grafana Dashboard Spec
    dash = TelemetryExporters.to_grafana_dashboard_json(
        title="Chaos Resilience",
        services=["srv-order", "srv-pay"],
        metrics=["app.error_rate", "infra.cpu_utilization"],
    )
    assert dash["title"] == "Chaos Resilience"
    assert len(dash["panels"]) == 2

    # Loki Push Payload
    logs = [
        StructuredLogEntry(
            log_id="l-1",
            timestamp="2026-11-05T12:00:00+00:00",
            service_id="srv-order",
            level="ERROR",
            message="Database unreachable",
        )
    ]
    loki = TelemetryExporters.to_loki_push_payload(logs)
    assert "streams" in loki
    assert len(loki["streams"]) == 1

    # Tempo Trace Payload
    tempo = TelemetryExporters.to_tempo_trace_payload(spans)
    assert "batches" in tempo

