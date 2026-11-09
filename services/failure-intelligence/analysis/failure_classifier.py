"""Failure Classifier for CHAOS-INTEL Phase 4."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple
from schemas.anomaly import Anomaly
from schemas.finding import CorrelatedFailureCluster, FailureCategory
from schemas.telemetry import StructuredLogEntry, TraceSpan


class FailureClassificationResult:
    """Detailed classification output with scoring breakdown."""

    def __init__(
        self,
        category: FailureCategory,
        confidence: float,
        reasoning: str,
        category_scores: Dict[FailureCategory, float],
    ) -> None:
        self.category = category
        self.confidence = confidence
        self.reasoning = reasoning
        self.category_scores = category_scores


class FailureClassifier:
    """Classifies correlated failures into standard resilience taxonomy categories."""

    def classify(self, cluster: CorrelatedFailureCluster) -> FailureClassificationResult:
        """Evaluate evidence across anomalies, logs, traces, and chaos events to classify failure."""
        scores: Dict[FailureCategory, float] = {
            "Infrastructure": 0.0,
            "Network": 0.0,
            "Application": 0.0,
            "Database": 0.0,
            "Dependency": 0.0,
            "Configuration": 0.0,
            "ResourceExhaustion": 0.0,
            "Unknown": 0.1,
        }
        evidence_notes: List[str] = []

        # 1. Analyze Chaos Events (direct intent indicator)
        for ce in cluster.chaos_events:
            fault_type = str(ce.get("fault_type", "")).lower()
            if any(k in fault_type for k in ("cpu", "memory", "disk_io")):
                scores["ResourceExhaustion"] += 3.0
                scores["Infrastructure"] += 2.0
                evidence_notes.append(f"Chaos fault '{fault_type}' directly simulates resource exhaustion.")
            elif any(k in fault_type for k in ("network", "packet_loss", "latency")):
                scores["Network"] += 3.5
                evidence_notes.append(f"Chaos fault '{fault_type}' directly injects network partition/latency.")
            elif "database" in fault_type or "db" in fault_type:
                scores["Database"] += 3.5
                evidence_notes.append(f"Chaos fault '{fault_type}' directly targets database reachability.")
            elif "dependency" in fault_type:
                scores["Dependency"] += 3.5
                evidence_notes.append(f"Chaos fault '{fault_type}' directly disrupts dependency.")
            elif "service_unavailability" in fault_type or "process_termination" in fault_type:
                scores["Infrastructure"] += 2.5
                scores["Application"] += 2.0
                evidence_notes.append(f"Chaos fault '{fault_type}' terminates service/process.")

        # 2. Analyze Anomalies
        for anom in cluster.anomalies:
            metric = anom.metric.lower()
            if "cpu" in metric or "memory" in metric or "disk" in metric:
                if anom.detection_method == "resource_saturation" or anom.observed_value >= 90.0:
                    scores["ResourceExhaustion"] += 2.5
                scores["Infrastructure"] += 2.0
                evidence_notes.append(f"Observed resource anomaly on '{anom.metric}' ({anom.observed_value}).")
            elif "latency" in metric:
                scores["Network"] += 1.5
                scores["Application"] += 1.0
            elif "error_rate" in metric:
                scores["Application"] += 1.5
            elif "availability" in metric:
                scores["Application"] += 1.0

        # 3. Analyze Structured Logs
        for log in cluster.error_logs:
            msg = log.message.lower()
            err_type = str(log.error_type or "").lower()
            full_text = f"{msg} {err_type}"

            if any(k in full_text for k in ("oom", "out of memory", "resource exhaustion", "limit exceeded")):
                scores["ResourceExhaustion"] += 3.0
                evidence_notes.append(f"Log explicitly reports memory/resource exhaustion: {log.message[:80]}")
            elif any(k in full_text for k in ("connection refused", "econnrefused", "timeout", "timed out", "unreachable", "dns")):
                scores["Network"] += 2.0
                scores["Dependency"] += 1.5
            elif any(k in full_text for k in ("database", "sql", "postgres", "mysql", "redis", "query error", "deadlock")):
                scores["Database"] += 3.0
                evidence_notes.append(f"Log indicates database error: {log.message[:80]}")
            elif any(k in full_text for k in ("config", "missing environment", "invalid setting", "unauthorized", "auth")):
                scores["Configuration"] += 2.5
            else:
                scores["Application"] += 1.5

        # 4. Analyze Trace Spans
        for span in cluster.error_spans:
            op = span.operation_name.lower()
            if "db" in op or "sql" in op or "query" in op:
                scores["Database"] += 2.0
            elif "http" in op or "grpc" in op:
                if span.duration_ms > 3000:
                    scores["Network"] += 1.5
                    scores["Dependency"] += 1.5
                else:
                    scores["Application"] += 1.0

        # Find best category
        sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_cat, top_score = sorted_scores[0]
        second_cat, second_score = sorted_scores[1]

        total = sum(s for s in scores.values() if s > 0)
        confidence = 0.50
        if total > 0:
            confidence = round(min(0.98, max(0.40, top_score / (top_score + second_score + 0.1))), 2)

        reasoning = (
            f"Classified as '{top_cat}' with confidence {confidence:.2f} based on "
            f"{len(evidence_notes)} evidence points. "
            + (f"Key evidence: {evidence_notes[0]}" if evidence_notes else "Default baseline classification.")
        )

        return FailureClassificationResult(
            category=top_cat,
            confidence=confidence,
            reasoning=reasoning,
            category_scores={k: round(v, 2) for k, v in scores.items()},
        )

