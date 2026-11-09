"""Specialized pattern anomaly detectors for CHAOS-INTEL Phase 4."""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional
from anomaly.base import AnomalyDetector
from schemas.anomaly import Anomaly, AnomalySeverity
from schemas.telemetry import NormalizedMetricPoint


class LatencySpikeDetector(AnomalyDetector):
    """Detects sudden, dramatic response latency spikes (>= 2x baseline)."""

    def __init__(self, spike_multiplier: float = 2.0, min_latency_threshold_ms: float = 500.0) -> None:
        self.spike_multiplier = spike_multiplier
        self.min_latency_threshold_ms = min_latency_threshold_ms

    def detect(
        self,
        points: List[NormalizedMetricPoint],
        baseline_points: Optional[List[NormalizedMetricPoint]] = None,
    ) -> List[Anomaly]:
        anomalies: List[Anomaly] = []
        baselines: Dict[str, float] = {}
        if baseline_points:
            for bp in baseline_points:
                if "latency" in bp.metric_name and not bp.missing:
                    baselines[f"{bp.service_id}:{bp.metric_name}"] = bp.value

        for p in points:
            if "latency" not in p.metric_name or p.missing:
                continue
            base = baselines.get(f"{p.service_id}:{p.metric_name}", 150.0)
            if p.value >= self.min_latency_threshold_ms and p.value >= (base * self.spike_multiplier):
                ratio = round(p.value / max(1.0, base), 2)
                severity: AnomalySeverity = "critical" if ratio >= 4.0 else "high"
                dev_pct = round(((p.value - base) / base) * 100.0, 2)
                anom_id = f"anom-spike-{hashlib.sha256(f'{p.service_id}:{p.timestamp}'.encode()).hexdigest()[:8]}"

                anomalies.append(
                    Anomaly(
                        anomaly_id=anom_id,
                        timestamp=p.timestamp,
                        affected_service=p.service_id,
                        metric=p.metric_name,
                        observed_value=p.value,
                        baseline_value=base,
                        deviation_percentage=dev_pct,
                        severity=severity,
                        detection_method="latency_spike",
                        evidence_references=[
                            {
                                "type": "latency_spike_breach",
                                "metric": p.metric_name,
                                "observed_ms": p.value,
                                "baseline_ms": base,
                                "spike_ratio": ratio,
                            }
                        ],
                        confidence=0.92,
                        metadata={"spike_ratio": ratio},
                    )
                )

        return anomalies


class ErrorRateIncreaseDetector(AnomalyDetector):
    """Detects sudden or sustained error rate increases."""

    def __init__(self, baseline_max_error_rate: float = 0.02, min_increase_delta: float = 0.05) -> None:
        self.baseline_max_error_rate = baseline_max_error_rate
        self.min_increase_delta = min_increase_delta

    def detect(
        self,
        points: List[NormalizedMetricPoint],
        baseline_points: Optional[List[NormalizedMetricPoint]] = None,
    ) -> List[Anomaly]:
        anomalies: List[Anomaly] = []
        baselines: Dict[str, float] = {}
        if baseline_points:
            for bp in baseline_points:
                if bp.metric_name == "app.error_rate" and not bp.missing:
                    baselines[bp.service_id] = bp.value

        for p in points:
            if p.metric_name != "app.error_rate" or p.missing:
                continue
            base = baselines.get(p.service_id, self.baseline_max_error_rate)
            delta = p.value - base
            if delta >= self.min_increase_delta or (p.value >= 0.05 and p.value >= base * 3.0):
                severity: AnomalySeverity = "critical" if p.value >= 0.25 else "high"
                dev_pct = round(((p.value - base) / max(0.001, base)) * 100.0, 2)
                anom_id = f"anom-err-{hashlib.sha256(f'{p.service_id}:{p.timestamp}'.encode()).hexdigest()[:8]}"

                anomalies.append(
                    Anomaly(
                        anomaly_id=anom_id,
                        timestamp=p.timestamp,
                        affected_service=p.service_id,
                        metric=p.metric_name,
                        observed_value=p.value,
                        baseline_value=base,
                        deviation_percentage=dev_pct,
                        severity=severity,
                        detection_method="error_rate_increase",
                        evidence_references=[
                            {
                                "type": "error_rate_surge",
                                "observed_rate": p.value,
                                "baseline_rate": base,
                                "delta": round(delta, 4),
                            }
                        ],
                        confidence=0.95,
                        metadata={"delta": round(delta, 4)},
                    )
                )

        return anomalies


class AvailabilityDegradationDetector(AnomalyDetector):
    """Detects service availability degradation below SLA thresholds."""

    def __init__(self, availability_threshold: float = 0.95) -> None:
        self.availability_threshold = availability_threshold

    def detect(
        self,
        points: List[NormalizedMetricPoint],
        baseline_points: Optional[List[NormalizedMetricPoint]] = None,
    ) -> List[Anomaly]:
        anomalies: List[Anomaly] = []
        for p in points:
            if p.metric_name != "app.service_availability" or p.missing:
                continue
            if p.value < self.availability_threshold:
                severity: AnomalySeverity = "critical" if p.value < 0.85 else "high"
                dev_pct = round((1.0 - p.value) * 100.0, 2)
                anom_id = f"anom-avail-{hashlib.sha256(f'{p.service_id}:{p.timestamp}'.encode()).hexdigest()[:8]}"

                anomalies.append(
                    Anomaly(
                        anomaly_id=anom_id,
                        timestamp=p.timestamp,
                        affected_service=p.service_id,
                        metric=p.metric_name,
                        observed_value=p.value,
                        baseline_value=1.0,
                        deviation_percentage=dev_pct,
                        severity=severity,
                        detection_method="availability_degradation",
                        evidence_references=[
                            {
                                "type": "availability_drop",
                                "observed": p.value,
                                "threshold": self.availability_threshold,
                            }
                        ],
                        confidence=0.98,
                        metadata={"threshold": self.availability_threshold},
                    )
                )

        return anomalies


class ResourceSaturationDetector(AnomalyDetector):
    """Detects sustained CPU, memory, or disk resource saturation (>= 90% for >= 3 intervals)."""

    def __init__(self, saturation_threshold: float = 90.0, consecutive_intervals: int = 3) -> None:
        self.saturation_threshold = saturation_threshold
        self.consecutive_intervals = consecutive_intervals

    def detect(
        self,
        points: List[NormalizedMetricPoint],
        baseline_points: Optional[List[NormalizedMetricPoint]] = None,
    ) -> List[Anomaly]:
        anomalies: List[Anomaly] = []
        series: Dict[str, List[NormalizedMetricPoint]] = {}

        for p in points:
            if p.missing or not any(k in p.metric_name for k in ("cpu", "memory", "disk")):
                continue
            series.setdefault(f"{p.service_id}:{p.metric_name}", []).append(p)

        for key, p_list in series.items():
            streak = 0
            for idx, p in enumerate(p_list):
                if p.value >= self.saturation_threshold:
                    streak += 1
                else:
                    streak = 0

                if streak >= self.consecutive_intervals:
                    anom_id = f"anom-sat-{hashlib.sha256(f'{p.service_id}:{p.metric_name}:{p.timestamp}'.encode()).hexdigest()[:8]}"
                    anomalies.append(
                        Anomaly(
                            anomaly_id=anom_id,
                            timestamp=p.timestamp,
                            affected_service=p.service_id,
                            metric=p.metric_name,
                            observed_value=p.value,
                            baseline_value=30.0,
                            deviation_percentage=round(p.value - 30.0, 2),
                            severity="critical" if p.value >= 95.0 else "high",
                            detection_method="resource_saturation",
                            evidence_references=[
                                {
                                    "type": "resource_saturation",
                                    "metric": p.metric_name,
                                    "observed_percent": p.value,
                                    "consecutive_samples": streak,
                                }
                            ],
                            confidence=0.96,
                            metadata={"consecutive_samples": streak},
                        )
                    )

        return anomalies

