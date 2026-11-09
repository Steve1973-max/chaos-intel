"""Threshold-based anomaly detection for CHAOS-INTEL Phase 4."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, List, Literal, Optional, Tuple
from anomaly.base import AnomalyDetector
from schemas.anomaly import Anomaly, AnomalySeverity
from schemas.telemetry import NormalizedMetricPoint

OperatorType = Literal[">", ">=", "<", "<="]


class MetricThresholdRule:
    """Configurable threshold rule for a specific metric."""

    def __init__(
        self,
        metric_name: str,
        operator: OperatorType,
        threshold: float,
        critical_threshold: Optional[float] = None,
        default_baseline: float = 0.0,
    ) -> None:
        self.metric_name = metric_name
        self.operator = operator
        self.threshold = threshold
        self.critical_threshold = critical_threshold
        self.default_baseline = default_baseline

    def evaluate(self, val: float) -> Tuple[bool, AnomalySeverity]:
        """Check if value breaches threshold and return severity."""
        breached = False
        if self.operator == ">":
            breached = val > self.threshold
        elif self.operator == ">=":
            breached = val >= self.threshold
        elif self.operator == "<":
            breached = val < self.threshold
        elif self.operator == "<=":
            breached = val <= self.threshold

        if not breached:
            return False, "info"

        severity: AnomalySeverity = "medium"
        if self.critical_threshold is not None:
            crit = False
            if self.operator in (">", ">="):
                crit = val >= self.critical_threshold
            else:
                crit = val <= self.critical_threshold
            if crit:
                severity = "critical"
            else:
                severity = "high"
        else:
            severity = "high"

        return True, severity


class ThresholdAnomalyDetector(AnomalyDetector):
    """Deterministic threshold-based anomaly detector."""

    DEFAULT_RULES: List[MetricThresholdRule] = [
        MetricThresholdRule("infra.cpu_utilization", ">=", 85.0, critical_threshold=95.0, default_baseline=20.0),
        MetricThresholdRule("infra.memory_utilization", ">=", 85.0, critical_threshold=95.0, default_baseline=35.0),
        MetricThresholdRule("infra.disk_utilization", ">=", 90.0, critical_threshold=98.0, default_baseline=40.0),
        MetricThresholdRule("app.error_rate", ">=", 0.05, critical_threshold=0.20, default_baseline=0.001),
        MetricThresholdRule("app.service_availability", "<=", 0.98, critical_threshold=0.90, default_baseline=1.0),
        MetricThresholdRule("app.response_latency_p95_ms", ">=", 1000.0, critical_threshold=3000.0, default_baseline=100.0),
    ]

    def __init__(self, rules: Optional[List[MetricThresholdRule]] = None) -> None:
        self.rules: Dict[str, MetricThresholdRule] = {
            r.metric_name: r for r in (rules or self.DEFAULT_RULES)
        }

    def detect(
        self,
        points: List[NormalizedMetricPoint],
        baseline_points: Optional[List[NormalizedMetricPoint]] = None,
    ) -> List[Anomaly]:
        anomalies: List[Anomaly] = []

        # Map baseline values if provided
        baselines: Dict[str, float] = {}
        if baseline_points:
            for bp in baseline_points:
                baselines[f"{bp.service_id}:{bp.metric_name}"] = bp.value

        for p in points:
            if p.missing:
                continue

            rule = self.rules.get(p.metric_name)
            if not rule:
                continue

            breached, severity = rule.evaluate(p.value)
            if not breached:
                continue

            base_val = baselines.get(f"{p.service_id}:{p.metric_name}", rule.default_baseline)
            dev_pct = 0.0
            if base_val != 0.0:
                dev_pct = round(((p.value - base_val) / abs(base_val)) * 100.0, 2)
            else:
                dev_pct = round(p.value * 100.0, 2)

            anom_id = f"anom-thresh-{hashlib.sha256(f'{p.service_id}:{p.metric_name}:{p.timestamp}'.encode()).hexdigest()[:8]}"
            anomalies.append(
                Anomaly(
                    anomaly_id=anom_id,
                    timestamp=p.timestamp,
                    affected_service=p.service_id,
                    metric=p.metric_name,
                    observed_value=p.value,
                    baseline_value=base_val,
                    deviation_percentage=dev_pct,
                    severity=severity,
                    detection_method="threshold",
                    evidence_references=[
                        {
                            "type": "metric_threshold_breach",
                            "metric": p.metric_name,
                            "observed": p.value,
                            "threshold": rule.threshold,
                            "timestamp": p.timestamp,
                        }
                    ],
                    confidence=0.95,
                    metadata={"operator": rule.operator, "unit": p.unit},
                )
            )

        return anomalies

