"""Unified Anomaly Detection Engine for CHAOS-INTEL Phase 4."""

from __future__ import annotations

from typing import Dict, List, Optional
from anomaly.base import AnomalyDetector
from anomaly.moving_average import MovingAverageAnomalyDetector
from anomaly.pattern_detectors import (
    AvailabilityDegradationDetector,
    ErrorRateIncreaseDetector,
    LatencySpikeDetector,
    ResourceSaturationDetector,
)
from anomaly.statistical import StatisticalAnomalyDetector
from anomaly.threshold import ThresholdAnomalyDetector
from schemas.anomaly import Anomaly, AnomalySeverity
from schemas.telemetry import NormalizedMetricPoint


class AnomalyDetectionEngine:
    """Orchestrates deterministic baseline anomaly detection across multiple algorithms."""

    def __init__(self, detectors: Optional[List[AnomalyDetector]] = None) -> None:
        self.detectors: List[AnomalyDetector] = (
            detectors
            if detectors is not None
            else [
                ThresholdAnomalyDetector(),
                MovingAverageAnomalyDetector(),
                StatisticalAnomalyDetector(),
                LatencySpikeDetector(),
                ErrorRateIncreaseDetector(),
                AvailabilityDegradationDetector(),
                ResourceSaturationDetector(),
            ]
        )

    def register_detector(self, detector: AnomalyDetector) -> None:
        """Register a custom or model-agnostic detector (e.g. future ML detector)."""
        self.detectors.append(detector)

    def detect_anomalies(
        self,
        points: List[NormalizedMetricPoint],
        baseline_points: Optional[List[NormalizedMetricPoint]] = None,
        min_severity: Optional[AnomalySeverity] = None,
    ) -> List[Anomaly]:
        """Run all detectors, deduplicate results, and return prioritized anomalies."""
        raw_anomalies: List[Anomaly] = []
        for d in self.detectors:
            try:
                detected = d.detect(points, baseline_points=baseline_points)
                raw_anomalies.extend(detected)
            except Exception:
                # Resilience: one failing detector does not crash the entire engine
                continue

        # Deduplicate anomalies occurring on same service, metric, and timestamp
        deduped: Dict[str, Anomaly] = {}
        severity_order: Dict[str, int] = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}

        for anom in raw_anomalies:
            dedup_key = f"{anom.affected_service}:{anom.metric}:{anom.timestamp}"
            existing = deduped.get(dedup_key)
            if existing is None:
                deduped[dedup_key] = anom
            else:
                # Merge evidence references
                existing.evidence_references.extend(anom.evidence_references)
                # Elevate severity if higher
                if severity_order.get(anom.severity, 0) > severity_order.get(existing.severity, 0):
                    existing.severity = anom.severity
                # Average/max confidence
                existing.confidence = max(existing.confidence, anom.confidence)

        results = list(deduped.values())

        if min_severity:
            min_rank = severity_order.get(min_severity, 1)
            results = [a for a in results if severity_order.get(a.severity, 1) >= min_rank]

        # Sort by timestamp, then severity descending
        results.sort(
            key=lambda a: (a.timestamp, severity_order.get(a.severity, 1)),
            reverse=True,
        )
        return results

