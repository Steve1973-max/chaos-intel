"""Model-agnostic Anomaly Detector interfaces for CHAOS-INTEL Phase 4."""

from __future__ import annotations

import abc
from typing import List, Optional
from schemas.anomaly import Anomaly
from schemas.telemetry import NormalizedMetricPoint


class AnomalyDetector(abc.ABC):
    """Abstract, model-agnostic anomaly detector interface.

    Supports deterministic rules, statistical algorithms, and future ML model implementations.
    """

    @abc.abstractmethod
    def detect(
        self,
        points: List[NormalizedMetricPoint],
        baseline_points: Optional[List[NormalizedMetricPoint]] = None,
    ) -> List[Anomaly]:
        """Detect anomalies from a stream or batch of normalized metric points."""
        raise NotImplementedError

