"""Moving-average divergence anomaly detection for CHAOS-INTEL Phase 4."""

from __future__ import annotations

import hashlib
from typing import Dict, List, Optional
from anomaly.base import AnomalyDetector
from schemas.anomaly import Anomaly, AnomalySeverity
from schemas.telemetry import NormalizedMetricPoint


class MovingAverageAnomalyDetector(AnomalyDetector):
    """Detects anomalies when metrics diverge from rolling moving averages (SMA or EMA)."""

    def __init__(
        self,
        window_size: int = 5,
        divergence_threshold_ratio: float = 0.50,  # 50% divergence from moving average
        use_ema: bool = False,
        ema_alpha: float = 0.3,
    ) -> None:
        self.window_size = window_size
        self.divergence_threshold_ratio = divergence_threshold_ratio
        self.use_ema = use_ema
        self.ema_alpha = ema_alpha

    def detect(
        self,
        points: List[NormalizedMetricPoint],
        baseline_points: Optional[List[NormalizedMetricPoint]] = None,
    ) -> List[Anomaly]:
        anomalies: List[Anomaly] = []

        # Group by series key
        series: Dict[str, List[NormalizedMetricPoint]] = {}
        for p in points:
            if not p.missing:
                series.setdefault(f"{p.service_id}:{p.metric_name}", []).append(p)

        for key, p_list in series.items():
            if len(p_list) < self.window_size:
                continue

            window_vals: List[float] = []
            ema_val: Optional[float] = None

            for idx, p in enumerate(p_list):
                window_vals.append(p.value)
                if len(window_vals) > self.window_size:
                    window_vals.pop(0)

                if self.use_ema:
                    if ema_val is None:
                        ema_val = p.value
                    else:
                        ema_val = (self.ema_alpha * p.value) + ((1 - self.ema_alpha) * ema_val)
                    ref_val = ema_val
                else:
                    ref_val = sum(window_vals) / len(window_vals)

                if idx < self.window_size - 1:
                    continue

                diff = abs(p.value - ref_val)
                denom = max(abs(ref_val), 1.0)
                div_ratio = diff / denom

                if div_ratio >= self.divergence_threshold_ratio:
                    severity: AnomalySeverity = "medium"
                    if div_ratio >= 1.5:  # 150% divergence
                        severity = "critical"
                    elif div_ratio >= 1.0:  # 100% divergence
                        severity = "high"

                    dev_pct = round(div_ratio * 100.0, 2)
                    conf = min(0.95, round(0.70 + (div_ratio * 0.15), 2))
                    anom_id = f"anom-ma-{hashlib.sha256(f'{p.service_id}:{p.metric_name}:{p.timestamp}'.encode()).hexdigest()[:8]}"

                    anomalies.append(
                        Anomaly(
                            anomaly_id=anom_id,
                            timestamp=p.timestamp,
                            affected_service=p.service_id,
                            metric=p.metric_name,
                            observed_value=p.value,
                            baseline_value=round(ref_val, 4),
                            deviation_percentage=dev_pct,
                            severity=severity,
                            detection_method="moving_average",
                            evidence_references=[
                                {
                                    "type": "moving_average_divergence",
                                    "metric": p.metric_name,
                                    "observed": p.value,
                                    "moving_average": round(ref_val, 4),
                                    "divergence_ratio": round(div_ratio, 4),
                                    "timestamp": p.timestamp,
                                }
                            ],
                            confidence=conf,
                            metadata={"window_size": self.window_size, "use_ema": self.use_ema},
                        )
                    )

        return anomalies

