"""Typed client for Failure Intelligence service."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from .base import BaseServiceClient, ServiceClientError
from .loader import get_failure_intel_classes

UnifiedFailureAnalyzer, NormalizedMetricPoint, StructuredLogEntry, TraceSpan = get_failure_intel_classes()


class FailureIntelligenceClient(BaseServiceClient):
    """Client for telemetry ingestion, anomaly detection, failure correlation, and root-cause analysis."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: float = 60.0,
        direct_adapter: Optional[Any] = None,
    ) -> None:
        super().__init__(
            service_name="failure-intelligence",
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            direct_adapter=direct_adapter or UnifiedFailureAnalyzer,
        )
        self._analyzer = UnifiedFailureAnalyzer() if UnifiedFailureAnalyzer else None
        self._reports: Dict[str, Any] = {}

    async def ingest_telemetry(
        self,
        correlation_id: str,
        metrics: Optional[List[Any]] = None,
        logs: Optional[List[Any]] = None,
        spans: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """Ingest metrics, logs, or traces into the failure intelligence buffer."""
        if self._analyzer is not None:
            ing = self._analyzer.ingestor
            count_m = 0
            count_l = 0
            count_s = 0
            if metrics:
                for m in metrics:
                    if isinstance(m, dict):
                        from schemas.telemetry import NormalizedMetricPoint
                        m = NormalizedMetricPoint(
                            service_id=m.get("service_id", "service-default"),
                            metric_name=m.get("metric_name", "custom_metric"),
                            category=m.get("category", "application"),
                            value=float(m.get("value", 0.0)),
                            unit=m.get("unit", ""),
                            timestamp=m.get("timestamp") or "2026-11-06T00:00:00Z",
                        )
                    ing.ingest_metric_point(m)
                    count_m += 1
            if logs:
                for l in logs:
                    ing.ingest_log(l)
                    count_l += 1
            if spans:
                for s in spans:
                    if isinstance(s, dict):
                        from schemas.telemetry import TraceSpan
                        s = TraceSpan(
                            trace_id=s.get("trace_id", "tr-default"),
                            span_id=s.get("span_id", "sp-default"),
                            service_id=s.get("service_id", s.get("service", "service-default")),
                            operation_name=s.get("operation_name", s.get("operation", "exec")),
                            start_time=s.get("start_time") or "2026-11-06T00:00:00Z",
                            end_time=s.get("end_time") or "2026-11-06T00:00:01Z",
                            duration_ms=float(s.get("duration_ms", 10.0)),
                            status_code="OK" if s.get("status", "ok").upper() != "ERROR" else "ERROR",
                        )
                    ing.ingest_span(s)
                    count_s += 1
            return {
                "status": "ACCEPTED",
                "metrics_ingested": count_m,
                "logs_ingested": count_l,
                "spans_ingested": count_s,
                "correlation_id": correlation_id,
            }

        # HTTP transport
        payload = {
            "metrics": [m if isinstance(m, dict) else m.model_dump() for m in (metrics or [])],
            "logs": [l if isinstance(l, dict) else l.model_dump() for l in (logs or [])],
            "spans": [s if isinstance(s, dict) else s.model_dump() for s in (spans or [])],
        }
        return await self._request("POST", "/api/v1/telemetry/ingest", correlation_id=correlation_id, json_payload=payload)

    async def analyze_experiment(
        self,
        app: Any,
        chaos_report: Any,
        test_results: List[Any],
        correlation_id: str,
        additional_logs: Optional[List[Any]] = None,
        additional_spans: Optional[List[Any]] = None,
    ) -> Any:
        """Run unified failure correlation, anomaly detection, root-cause generation, and recommendation synthesis."""
        if self._analyzer is not None:
            try:
                report = self._analyzer.analyze_experiment(
                    app=app,
                    chaos_report=chaos_report,
                    test_results=test_results,
                    additional_logs=additional_logs,
                    additional_spans=additional_spans,
                    correlation_id_override=correlation_id,
                )
                self._reports[report.analysis_id] = report
                return report
            except Exception as exc:
                raise ServiceClientError(
                    f"Failure intelligence analysis failed: {exc}",
                    self.service_name,
                    correlation_id=correlation_id,
                ) from exc

        # HTTP transport
        payload = {
            "application_id": getattr(app, "application_id", ""),
            "chaos_report_id": getattr(chaos_report, "report_id", ""),
            "test_results_count": len(test_results or []),
        }
        res = await self._request("POST", "/api/v1/analyze", correlation_id=correlation_id, json_payload=payload)
        return res

    async def get_analysis_report(self, analysis_id: str, correlation_id: str) -> Optional[Any]:
        """Retrieve analysis report by ID."""
        if analysis_id in self._reports:
            return self._reports[analysis_id]
        if self.base_url:
            return await self._request("GET", f"/api/v1/reports/{analysis_id}", correlation_id=correlation_id)
        return None

    async def get_recommendations(self, analysis_id: str, correlation_id: str) -> List[Any]:
        """Retrieve recommendations for analysis report."""
        report = await self.get_analysis_report(analysis_id, correlation_id)
        if report and getattr(report, "recommendations", None) is not None:
            return report.recommendations
        return []
