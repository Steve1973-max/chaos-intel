"""Unified Telemetry Ingestor for CHAOS-INTEL Phase 4."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from schemas.telemetry import (
    ApplicationMetrics,
    InfrastructureMetrics,
    NormalizedMetricPoint,
    ResilienceMetrics,
    StructuredLogEntry,
    TraceSpan,
)
from telemetry.collector import TelemetryCollector
from telemetry.logs import LogProcessor
from telemetry.timeseries import TimeSeriesProcessor
from telemetry.tracing import TraceProcessor


class TelemetryIngestor:
    """Unified telemetry ingestor buffering and indexing metrics, logs, and traces."""

    def __init__(self) -> None:
        self.collector = TelemetryCollector()
        self.log_processor = LogProcessor()
        self.trace_processor = TraceProcessor()
        self._metric_points: List[NormalizedMetricPoint] = []
        self._logs: List[StructuredLogEntry] = []
        self._spans: List[TraceSpan] = []

    def ingest_metric_point(self, point: NormalizedMetricPoint) -> None:
        self._metric_points.append(point)

    def ingest_metric_points(self, points: List[NormalizedMetricPoint]) -> None:
        self._metric_points.extend(points)

    def ingest_infrastructure(self, m: InfrastructureMetrics) -> List[NormalizedMetricPoint]:
        pts = self.collector.normalize_infrastructure(m)
        self.ingest_metric_points(pts)
        return pts

    def ingest_application(self, m: ApplicationMetrics) -> List[NormalizedMetricPoint]:
        pts = self.collector.normalize_application(m)
        self.ingest_metric_points(pts)
        return pts

    def ingest_resilience(self, m: ResilienceMetrics) -> List[NormalizedMetricPoint]:
        pts = self.collector.normalize_resilience(m)
        self.ingest_metric_points(pts)
        return pts

    def ingest_log(self, raw: Dict[str, Any] | str, default_service_id: str = "unknown") -> StructuredLogEntry:
        entry = self.log_processor.parse_entry(raw, default_service_id=default_service_id)
        self._logs.append(entry)
        return entry

    def ingest_logs(self, raw_logs: List[Dict[str, Any] | str], default_service_id: str = "unknown") -> List[StructuredLogEntry]:
        entries = [self.ingest_log(l, default_service_id=default_service_id) for l in raw_logs]
        return entries

    def ingest_span(self, span: TraceSpan) -> None:
        self._spans.append(span)
        self.trace_processor.ingest_span(span)

    def ingest_spans(self, spans: List[TraceSpan]) -> None:
        for s in spans:
            self.ingest_span(s)

    def get_metrics(
        self,
        service_id: Optional[str] = None,
        metric_name: Optional[str] = None,
    ) -> List[NormalizedMetricPoint]:
        pts = self._metric_points
        if service_id:
            pts = [p for p in pts if p.service_id == service_id]
        if metric_name:
            pts = [p for p in pts if p.metric_name == metric_name]
        return list(pts)

    def get_logs(
        self,
        service_id: Optional[str] = None,
        level: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> List[StructuredLogEntry]:
        logs = self._logs
        if service_id:
            logs = [l for l in logs if l.service_id == service_id]
        if level:
            logs = [l for l in logs if l.level == level]
        if correlation_id:
            logs = [l for l in logs if l.correlation_id == correlation_id]
        return list(logs)

    def get_spans(
        self,
        service_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> List[TraceSpan]:
        spans = self._spans
        if service_id:
            spans = [s for s in spans if s.service_id == service_id]
        if trace_id:
            spans = [s for s in spans if s.trace_id == trace_id]
        return list(spans)

    def clear(self) -> None:
        self._metric_points.clear()
        self._logs.clear()
        self._spans.clear()
        self.trace_processor = TraceProcessor()

