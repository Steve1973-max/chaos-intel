"""Integration exporters and formatters for OTel, Prometheus, Grafana, Loki, Tempo."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Dict, List
from schemas.telemetry import NormalizedMetricPoint, StructuredLogEntry, TraceSpan


class TelemetryExporters:
    """Formats normalized telemetry for external observability backends."""

    @staticmethod
    def to_opentelemetry_otlp(
        points: List[NormalizedMetricPoint],
        spans: List[TraceSpan],
    ) -> Dict[str, Any]:
        """Convert metrics and spans to standard OpenTelemetry OTLP JSON structure."""
        resource_metrics: List[Dict[str, Any]] = []
        for p in points:
            resource_metrics.append({
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": p.service_id}},
                        {"key": "telemetry.category", "value": {"stringValue": p.category}},
                    ]
                },
                "scopeMetrics": [
                    {
                        "scope": {"name": "chaos-intel.failure-intelligence"},
                        "metrics": [
                            {
                                "name": p.metric_name,
                                "unit": p.unit,
                                "gauge": {
                                    "dataPoints": [
                                        {
                                            "asDouble": p.value,
                                            "timeUnixNano": int(
                                                # Approximate nanoseconds
                                                float(p.timestamp.replace("Z", "+00:00").split("T")[0].replace("-", ""))
                                            ),
                                            "attributes": [
                                                {"key": k, "value": {"stringValue": str(v)}}
                                                for k, v in p.attributes.items()
                                            ],
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                ],
            })

        resource_spans: List[Dict[str, Any]] = []
        for s in spans:
            resource_spans.append({
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": s.service_id}}]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "chaos-intel.tracer"},
                        "spans": [
                            {
                                "traceId": s.trace_id,
                                "spanId": s.span_id,
                                "parentSpanId": s.parent_span_id or "",
                                "name": s.operation_name,
                                "status": {"code": 1 if s.status_code == "OK" else 2},
                                "attributes": [
                                    {"key": k, "value": {"stringValue": str(v)}}
                                    for k, v in s.attributes.items()
                                ],
                            }
                        ],
                    }
                ],
            })

        return {
            "resourceMetrics": resource_metrics,
            "resourceSpans": resource_spans,
        }

    @staticmethod
    def to_prometheus_text(points: List[NormalizedMetricPoint]) -> str:
        """Format metric points in Prometheus text exposition format."""
        lines: List[str] = []
        seen_metrics = set()

        for p in points:
            if p.missing:
                continue
            prom_name = p.metric_name.replace(".", "_").replace("-", "_")
            if prom_name not in seen_metrics:
                lines.append(f"# HELP {prom_name} Normalized metric for {p.metric_name}")
                lines.append(f"# TYPE {prom_name} gauge")
                seen_metrics.add(prom_name)

            label_pairs = [f'service="{p.service_id}"', f'category="{p.category}"']
            for k, v in sorted(p.attributes.items()):
                if isinstance(v, (str, int, float, bool)):
                    safe_k = k.replace(".", "_").replace("-", "_")
                    label_pairs.append(f'{safe_k}="{v}"')

            labels_str = "{" + ",".join(label_pairs) + "}"
            lines.append(f"{prom_name}{labels_str} {p.value}")

        return "\n".join(lines) + "\n"

    @staticmethod
    def to_grafana_dashboard_json(title: str, services: List[str], metrics: List[str]) -> Dict[str, Any]:
        """Generate declarative Grafana dashboard specification for system observability."""
        panels: List[Dict[str, Any]] = []
        for idx, m in enumerate(metrics):
            prom_name = m.replace(".", "_").replace("-", "_")
            panels.append({
                "id": idx + 1,
                "title": f"{m} by Service",
                "type": "timeseries",
                "gridPos": {"x": (idx % 2) * 12, "y": (idx // 2) * 8, "w": 12, "h": 8},
                "targets": [
                    {
                        "expr": f'{prom_name}{{service=~"{"|".join(services)}"}}',
                        "legendFormat": "{{service}}",
                        "refId": "A",
                    }
                ],
            })

        return {
            "title": title,
            "schemaVersion": 36,
            "timezone": "browser",
            "panels": panels,
            "tags": ["chaos-intel", "failure-intelligence"],
        }

    @staticmethod
    def to_loki_push_payload(logs: List[StructuredLogEntry]) -> Dict[str, Any]:
        """Format structured logs for Grafana Loki JSON push API."""
        streams: Dict[str, List[List[str]]] = {}
        for l in logs:
            stream_key = json.dumps({"service": l.service_id, "level": l.level}, sort_keys=True)
            # Loki expects [timestamp_nanoseconds_string, log_line_string]
            ts_nano = str(int(datetime.fromisoformat(l.timestamp.replace("Z", "+00:00")).timestamp() * 1e9))
            log_line = json.dumps({
                "message": l.message,
                "trace_id": l.trace_id,
                "span_id": l.span_id,
                "correlation_id": l.correlation_id,
                "error_type": l.error_type,
            })
            streams.setdefault(stream_key, []).append([ts_nano, log_line])

        return {
            "streams": [
                {"stream": json.loads(k), "values": v}
                for k, v in streams.items()
            ]
        }

    @staticmethod
    def to_tempo_trace_payload(spans: List[TraceSpan]) -> Dict[str, Any]:
        """Format distributed traces for Grafana Tempo / OpenTelemetry trace ingestion."""
        return {
            "batches": [
                {
                    "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "chaos-intel"}}]},
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": s.trace_id,
                                    "spanId": s.span_id,
                                    "parentSpanId": s.parent_span_id or "",
                                    "name": s.operation_name,
                                    "status": {"code": 1 if s.status_code == "OK" else 2},
                                    "attributes": [
                                        {"key": "service.name", "value": {"stringValue": s.service_id}},
                                        {"key": "duration_ms", "value": {"doubleValue": s.duration_ms}},
                                    ],
                                }
                                for s in spans
                            ]
                        }
                    ],
                }
            ]
        }
