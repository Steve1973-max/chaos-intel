"""Statistical deviation (Z-score and IQR) anomaly detection for CHAOS-INTEL Phase 4."""

from __future__ import annotations

import hashlib
import math
from typing import Dict, List, Optional
from anomaly.base import AnomalyDetector
from schemas.anomaly import Anomaly, AnomalySeverity
from schemas.telemetry import NormalizedMetricPoint


class StatisticalAnomalyDetector(AnomalyDetector):
    """Detects statistical anomalies using Z-scores and Interquartile Ranges (IQR)."""

    def __init__(
        self,
        z_threshold: float = 3.0,
        critical_z_threshold: float = 4.5,
        use_iqr: bool = False,
        min_samples: int = 4,
    ) -> None:
        self.z_threshold = z_threshold
        self.critical_z_threshold = critical_z_threshold
        self.use_iqr = use_iqr
        self.min_samples = min_samples

    @staticmethod
    def _mean_std(values: List[float]) -> tuple[float, float]:
        if not values:
            return 0.0, 0.0
        mean = sum(values) / len(values)
        if len(values) < 2:
            return mean, 0.0
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return mean, math.sqrt(variance)

    @staticmethod
    def _iqr_bounds(values: List[float]) -> tuple[float, float, float]:
        s = sorted(values)
        n = len(s)
        q1 = s[int(n * 0.25)]
        q3 = s[int(n * 0.75)]
        iqr = q3 - q1
        lower = q1 - (1.5 * iqr)
        upper = q3 + (1.5 * iqr)
        return lower, upper, (q1 + q3) / 2.0

    def detect(
        self,
        points: List[NormalizedMetricPoint],
        baseline_points: Optional[List[NormalizedMetricPoint]] = None,
    ) -> List[Anomaly]:
        anomalies: List[Anomaly] = []

        # Group points by service and metric
        series: Dict[str, List[NormalizedMetricPoint]] = {}
        for p in points:
            if not p.missing:
                series.setdefault(f"{p.service_id}:{p.metric_name}", []).append(p)

        baseline_vals: Dict[str, List[float]] = {}
        if baseline_points:
            for bp in baseline_points:
                if not bp.missing:
                    baseline_vals.setdefault(f"{bp.service_id}:{bp.metric_name}", []).append(bp.value)

        for key, p_list in series.items():
            ref_population = baseline_vals.get(key)
            if not ref_population or len(ref_population) < self.min_samples:
                ref_population = [p.value for p in p_list]

            if len(ref_population) < self.min_samples:
                continue

            if self.use_iqr:
                lower, upper, median = self._iqr_bounds(ref_population)
                for p in p_list:
                    if p.value < lower or p.value > upper:
                        dev_pct = 0.0
                        if median != 0.0:
                            dev_pct = round(((p.value - median) / abs(median)) * 100.0, 2)
                        anom_id = f"anom-iqr-{hashlib.sha256(f'{p.service_id}:{p.metric_name}:{p.timestamp}'.encode()).hexdigest()[:8]}"
                        anomalies.append(
                            Anomaly(
                                anomaly_id=anom_id,
                                timestamp=p.timestamp,
                                affected_service=p.service_id,
                                metric=p.metric_name,
                                observed_value=p.value,
                                baseline_value=round(median, 4),
                                deviation_percentage=dev_pct,
                                severity="high",
                                detection_method="statistical_iqr",
                                evidence_references=[
                                    {
                                        "type": "iqr_outlier",
                                        "metric": p.metric_name,
                                        "observed": p.value,
                                        "lower_bound": round(lower, 4),
                                        "upper_bound": round(upper, 4),
                                    }
                                ],
                                confidence=0.85,
                                metadata={"lower": lower, "upper": upper},
                            )
                        )
            else:
                mean, std = self._mean_std(ref_population)
                if std <= 1e-9:
                    continue

                for p in p_list:
                    z = (p.value - mean) / std
                    abs_z = abs(z)
                    if abs_z >= self.z_threshold:
                        severity: AnomalySeverity = "medium"
                        if abs_z >= self.critical_z_threshold:
                            severity = "critical"
                        elif abs_z >= self.z_threshold + 0.8:
                            severity = "high"

                        dev_pct = 0.0
                        if mean != 0.0:
                            dev_pct = round(((p.value - mean) / abs(mean)) * 100.0, 2)
                        else:
                            dev_pct = round(p.value * 100.0, 2)

                        conf = min(0.99, round(0.75 + min(0.24, (abs_z - self.z_threshold) * 0.08), 2))
                        anom_id = f"anom-z-{hashlib.sha256(f'{p.service_id}:{p.metric_name}:{p.timestamp}'.encode()).hexdigest()[:8]}"

                        anomalies.append(
                            Anomaly(
                                anomaly_id=anom_id,
                                timestamp=p.timestamp,
                                affected_service=p.service_id,
                                metric=p.metric_name,
                                observed_value=p.value,
                                baseline_value=round(mean, 4),
                                deviation_percentage=dev_pct,
                                severity=severity,
                                detection_method="statistical_zscore",
                                evidence_references=[
                                    {
                                        "type": "zscore_deviation",
                                        "metric": p.metric_name,
                                        "observed": p.value,
                                        "mean": round(mean, 4),
                                        "std": round(std, 4),
                                        "z_score": round(z, 2),
                                    }
                                ],
                                confidence=conf,
                                metadata={"z_score": round(z, 3), "mean": mean, "std": std},
                            )
                        )

        return anomalies

