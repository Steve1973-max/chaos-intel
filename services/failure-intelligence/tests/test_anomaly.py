"""Tests for Anomaly Detection Engine and all detection algorithms."""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

_FI_ROOT = Path(__file__).resolve().parents[1]
if str(_FI_ROOT) not in sys.path:
    sys.path.insert(0, str(_FI_ROOT))

from anomaly.engine import AnomalyDetectionEngine
from anomaly.moving_average import MovingAverageAnomalyDetector
from anomaly.pattern_detectors import (
    AvailabilityDegradationDetector,
    ErrorRateIncreaseDetector,
    LatencySpikeDetector,
    ResourceSaturationDetector,
)
from anomaly.statistical import StatisticalAnomalyDetector
from anomaly.threshold import MetricThresholdRule, ThresholdAnomalyDetector
from schemas.telemetry import NormalizedMetricPoint


def test_threshold_anomaly_detection():
    detector = ThresholdAnomalyDetector()

    # Normal points: no anomaly
    normal_pts = [
        NormalizedMetricPoint(
            metric_name="infra.cpu_utilization",
            category="infrastructure",
            service_id="srv-web",
            timestamp="2026-11-05T12:00:00Z",
            value=45.0,
            unit="%",
        ),
        NormalizedMetricPoint(
            metric_name="app.error_rate",
            category="application",
            service_id="srv-web",
            timestamp="2026-11-05T12:00:00Z",
            value=0.01,
            unit="1",
        ),
    ]
    assert len(detector.detect(normal_pts)) == 0

    # Breaching points: CPU 96% (critical), error_rate 0.08 (high)
    breaching_pts = [
        NormalizedMetricPoint(
            metric_name="infra.cpu_utilization",
            category="infrastructure",
            service_id="srv-web",
            timestamp="2026-11-05T12:00:01Z",
            value=96.0,
            unit="%",
        ),
        NormalizedMetricPoint(
            metric_name="app.error_rate",
            category="application",
            service_id="srv-web",
            timestamp="2026-11-05T12:00:01Z",
            value=0.08,
            unit="1",
        ),
    ]
    anomalies = detector.detect(breaching_pts)
    assert len(anomalies) == 2

    cpu_anom = next(a for a in anomalies if a.metric == "infra.cpu_utilization")
    assert cpu_anom.severity == "critical"
    assert cpu_anom.observed_value == 96.0
    assert cpu_anom.detection_method == "threshold"
    assert cpu_anom.confidence >= 0.90


def test_moving_average_anomaly_detection():
    # 5 normal values around 100, then a sudden surge to 250
    pts = [
        NormalizedMetricPoint(
            metric_name="app.latency",
            category="application",
            service_id="srv-order",
            timestamp=f"2026-11-05T12:00:0{i}Z",
            value=100.0 + (i * 2),
            unit="ms",
        )
        for i in range(5)
    ]
    pts.append(
        NormalizedMetricPoint(
            metric_name="app.latency",
            category="application",
            service_id="srv-order",
            timestamp="2026-11-05T12:00:05Z",
            value=260.0,
            unit="ms",
        )
    )

    sma_detector = MovingAverageAnomalyDetector(window_size=5, divergence_threshold_ratio=0.50, use_ema=False)
    anomalies = sma_detector.detect(pts)
    assert len(anomalies) >= 1
    anom = anomalies[0]
    assert anom.detection_method == "moving_average"
    assert anom.observed_value == 260.0
    assert anom.deviation_percentage >= 50.0

    # EMA detector
    ema_detector = MovingAverageAnomalyDetector(window_size=5, divergence_threshold_ratio=0.50, use_ema=True)
    ema_anomalies = ema_detector.detect(pts)
    assert len(ema_anomalies) >= 1


def test_statistical_zscore_and_iqr_anomaly_detection():
    # Stable baseline around 50 (std ~ 2), then outlier at 95
    baseline = [
        NormalizedMetricPoint(
            metric_name="infra.cpu_utilization",
            category="infrastructure",
            service_id="srv-db",
            timestamp=f"2026-11-05T12:00:0{i}Z",
            value=50.0 + (i % 3),
            unit="%",
        )
        for i in range(10)
    ]
    test_pt = [
        NormalizedMetricPoint(
            metric_name="infra.cpu_utilization",
            category="infrastructure",
            service_id="srv-db",
            timestamp="2026-11-05T12:00:10Z",
            value=95.0,
            unit="%",
        )
    ]

    z_detector = StatisticalAnomalyDetector(z_threshold=3.0, use_iqr=False)
    z_anomalies = z_detector.detect(test_pt, baseline_points=baseline)
    assert len(z_anomalies) == 1
    assert z_anomalies[0].detection_method == "statistical_zscore"
    assert z_anomalies[0].severity in ("high", "critical")
    assert z_anomalies[0].confidence >= 0.85

    # IQR detector
    iqr_detector = StatisticalAnomalyDetector(use_iqr=True)
    iqr_anomalies = iqr_detector.detect(test_pt, baseline_points=baseline)
    assert len(iqr_anomalies) == 1
    assert iqr_anomalies[0].detection_method == "statistical_iqr"


def test_pattern_detectors():
    # 1. Latency spike: jump from 100ms baseline to 800ms
    base_lat = [
        NormalizedMetricPoint(
            metric_name="app.response_latency_p95_ms",
            category="application",
            service_id="srv-pay",
            timestamp="2026-11-05T12:00:00Z",
            value=100.0,
            unit="ms",
        )
    ]
    spike_pt = [
        NormalizedMetricPoint(
            metric_name="app.response_latency_p95_ms",
            category="application",
            service_id="srv-pay",
            timestamp="2026-11-05T12:00:01Z",
            value=850.0,
            unit="ms",
        )
    ]
    spike_detector = LatencySpikeDetector(spike_multiplier=2.0)
    spike_anoms = spike_detector.detect(spike_pt, baseline_points=base_lat)
    assert len(spike_anoms) == 1
    assert spike_anoms[0].detection_method == "latency_spike"
    assert spike_anoms[0].observed_value == 850.0

    # 2. Error rate increase: jumps to 0.30
    err_detector = ErrorRateIncreaseDetector()
    err_pt = [
        NormalizedMetricPoint(
            metric_name="app.error_rate",
            category="application",
            service_id="srv-pay",
            timestamp="2026-11-05T12:00:01Z",
            value=0.30,
            unit="1",
        )
    ]
    err_anoms = err_detector.detect(err_pt)
    assert len(err_anoms) == 1
    assert err_anoms[0].detection_method == "error_rate_increase"
    assert err_anoms[0].severity == "critical"

    # 3. Availability degradation: drops to 0.82
    avail_detector = AvailabilityDegradationDetector(availability_threshold=0.95)
    avail_pt = [
        NormalizedMetricPoint(
            metric_name="app.service_availability",
            category="application",
            service_id="srv-pay",
            timestamp="2026-11-05T12:00:01Z",
            value=0.82,
            unit="1",
        )
    ]
    avail_anoms = avail_detector.detect(avail_pt)
    assert len(avail_anoms) == 1
    assert avail_anoms[0].detection_method == "availability_degradation"
    assert avail_anoms[0].severity == "critical"

    # 4. Resource saturation: 3 consecutive values >= 90%
    sat_detector = ResourceSaturationDetector(saturation_threshold=90.0, consecutive_intervals=3)
    sat_pts = [
        NormalizedMetricPoint(
            metric_name="infra.cpu_utilization",
            category="infrastructure",
            service_id="srv-db",
            timestamp=f"2026-11-05T12:00:0{i}Z",
            value=92.0 + i,
            unit="%",
        )
        for i in range(3)
    ]
    sat_anoms = sat_detector.detect(sat_pts)
    assert len(sat_anoms) == 1
    assert sat_anoms[0].detection_method == "resource_saturation"


def test_anomaly_detection_engine_orchestration_and_deduplication():
    engine = AnomalyDetectionEngine()

    # Point that triggers both threshold and error-rate increase
    test_points = [
        NormalizedMetricPoint(
            metric_name="app.error_rate",
            category="application",
            service_id="srv-order",
            timestamp="2026-11-05T12:00:00Z",
            value=0.40,
            unit="1",
        )
    ]

    anomalies = engine.detect_anomalies(test_points)
    # Deduplication must merge multiple detector hits on the same metric/service/timestamp into 1 anomaly
    assert len(anomalies) == 1
    anom = anomalies[0]
    assert anom.affected_service == "srv-order"
    assert anom.observed_value == 0.40
    # Merged evidence references from multiple detectors
    assert len(anom.evidence_references) >= 2
    assert anom.severity == "critical"

