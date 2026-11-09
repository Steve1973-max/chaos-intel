"""Failure Correlator for CHAOS-INTEL Phase 4.

Correlates anomalies, structured logs, distributed trace spans, test failures,
and chaos experiment events across temporal windows and service topologies.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from schemas.anomaly import Anomaly
from schemas.finding import CorrelatedFailureCluster
from schemas.telemetry import StructuredLogEntry, TraceSpan


def parse_epoch(ts: str) -> float:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


class FailureCorrelator:
    """Correlates multi-modal telemetry and experiment events into unified clusters."""

    def __init__(self, time_window_seconds: float = 30.0) -> None:
        self.time_window_seconds = time_window_seconds

    def correlate(
        self,
        correlation_id: str,
        anomalies: List[Anomaly],
        error_logs: List[StructuredLogEntry],
        error_spans: List[TraceSpan],
        test_failures: Optional[List[Dict[str, Any]]] = None,
        chaos_events: Optional[List[Dict[str, Any]]] = None,
    ) -> List[CorrelatedFailureCluster]:
        """Group events into correlated failure clusters."""
        test_fails = test_failures or []
        chaos_evs = chaos_events or []

        if not (anomalies or error_logs or error_spans or test_fails or chaos_evs):
            return []

        # Collect all timestamps to find global time range
        all_timestamps: List[float] = []
        for a in anomalies:
            all_timestamps.append(parse_epoch(a.timestamp))
        for l in error_logs:
            all_timestamps.append(parse_epoch(l.timestamp))
        for s in error_spans:
            all_timestamps.append(parse_epoch(s.start_time))
        for tf in test_fails:
            if "ended_at" in tf:
                all_timestamps.append(parse_epoch(tf["ended_at"]))
            elif "started_at" in tf:
                all_timestamps.append(parse_epoch(tf["started_at"]))
        for ce in chaos_evs:
            if "timestamp" in ce:
                all_timestamps.append(parse_epoch(ce["timestamp"]))

        all_timestamps = [t for t in all_timestamps if t > 0.0]
        if not all_timestamps:
            min_ts = datetime.now(timezone.utc).isoformat()
            max_ts = min_ts
        else:
            min_ts = datetime.fromtimestamp(min(all_timestamps), tz=timezone.utc).isoformat()
            max_ts = datetime.fromtimestamp(max(all_timestamps), tz=timezone.utc).isoformat()

        # Identify all affected services
        affected_services: Set[str] = set()
        for a in anomalies:
            affected_services.add(a.affected_service)
        for l in error_logs:
            affected_services.add(l.service_id)
        for s in error_spans:
            affected_services.add(s.service_id)
        for tf in test_fails:
            if "service_id" in tf:
                affected_services.add(tf["service_id"])
        for ce in chaos_evs:
            if "target_id" in ce:
                affected_services.add(ce["target_id"])

        # Determine primary affected service (prefer explicit chaos target or service with most errors)
        service_error_counts: Dict[str, int] = {}
        for a in anomalies:
            service_error_counts[a.affected_service] = service_error_counts.get(a.affected_service, 0) + 2
        for l in error_logs:
            service_error_counts[l.service_id] = service_error_counts.get(l.service_id, 0) + 1
        for s in error_spans:
            service_error_counts[s.service_id] = service_error_counts.get(s.service_id, 0) + 1

        primary_service = "unknown"
        if chaos_evs and "target_id" in chaos_evs[0]:
            primary_service = chaos_evs[0]["target_id"]
        elif service_error_counts:
            primary_service = max(service_error_counts.items(), key=lambda item: item[1])[0]
        elif affected_services:
            primary_service = sorted(affected_services)[0]

        cluster_id = f"cluster-{hashlib.sha256(f'{correlation_id}:{min_ts}'.encode()).hexdigest()[:8]}"

        cluster = CorrelatedFailureCluster(
            cluster_id=cluster_id,
            correlation_id=correlation_id,
            time_window_start=min_ts,
            time_window_end=max_ts,
            primary_affected_service=primary_service,
            affected_services=sorted(affected_services),
            anomalies=anomalies,
            error_logs=error_logs,
            error_spans=error_spans,
            test_failures=test_fails,
            chaos_events=chaos_evs,
            metadata={
                "anomaly_count": len(anomalies),
                "error_log_count": len(error_logs),
                "error_span_count": len(error_spans),
                "test_failure_count": len(test_fails),
                "chaos_event_count": len(chaos_evs),
            },
        )
        return [cluster]

