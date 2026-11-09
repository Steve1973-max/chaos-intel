"""CHAOS-INTEL Phase 4: Observability & Failure Intelligence.

Provides unified telemetry ingestion, normalization, multi-algorithm anomaly detection,
temporal-topological failure correlation, probable root-cause analysis with competing
hypotheses, dependency impact tracing, and evidence-backed recommendations.
"""

from __future__ import annotations

from analysis.dependency_impact_analyzer import DependencyImpactAnalyzer
from analysis.evidence_ranker import EvidenceRanker, RankedEvidence
from analysis.failure_classifier import FailureClassificationResult, FailureClassifier
from analysis.failure_correlator import FailureCorrelator
from analysis.recommendation_engine import RecommendationEngine
from analysis.root_cause_analyzer import RootCauseAnalyzer
from anomaly.base import AnomalyDetector
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
from schemas.anomaly import Anomaly, AnomalyMethod, AnomalySeverity
from schemas.finding import (
    CorrelatedFailureCluster,
    DependencyImpact,
    FailureCategory,
    RootCauseHypothesis,
)
from schemas.recommendation import (
    ActionableRecommendation,
    RecommendationCategory,
    RecommendationPriority,
)
from schemas.report import UnifiedExperimentAnalysis
from schemas.telemetry import (
    ApplicationMetrics,
    InfrastructureMetrics,
    LogLevel,
    MetricCategory,
    MetricType,
    NormalizedMetricPoint,
    ResilienceMetrics,
    SpanStatus,
    StructuredLogEntry,
    TraceSpan,
)
from telemetry.collector import TelemetryCollector
from telemetry.exporters import TelemetryExporters
from telemetry.health_monitor import DependencyHealthSnapshot, HealthMonitor, ServiceHealthSnapshot
from telemetry.ingestor import TelemetryIngestor
from telemetry.logs import LogProcessor
from telemetry.timeseries import TimeSeriesProcessor
from telemetry.tracing import TraceProcessor, TraceTree
from unified_analyzer import UnifiedFailureAnalyzer

__all__ = [
    # Schemas
    "MetricCategory",
    "MetricType",
    "LogLevel",
    "SpanStatus",
    "NormalizedMetricPoint",
    "InfrastructureMetrics",
    "ApplicationMetrics",
    "ResilienceMetrics",
    "StructuredLogEntry",
    "TraceSpan",
    "AnomalySeverity",
    "AnomalyMethod",
    "Anomaly",
    "FailureCategory",
    "CorrelatedFailureCluster",
    "DependencyImpact",
    "RootCauseHypothesis",
    "RecommendationPriority",
    "RecommendationCategory",
    "ActionableRecommendation",
    "UnifiedExperimentAnalysis",
    # Telemetry
    "TelemetryCollector",
    "TelemetryExporters",
    "HealthMonitor",
    "ServiceHealthSnapshot",
    "DependencyHealthSnapshot",
    "TelemetryIngestor",
    "LogProcessor",
    "TimeSeriesProcessor",
    "TraceProcessor",
    "TraceTree",
    # Anomaly Detection
    "AnomalyDetector",
    "AnomalyDetectionEngine",
    "MetricThresholdRule",
    "ThresholdAnomalyDetector",
    "MovingAverageAnomalyDetector",
    "StatisticalAnomalyDetector",
    "LatencySpikeDetector",
    "ErrorRateIncreaseDetector",
    "AvailabilityDegradationDetector",
    "ResourceSaturationDetector",
    # Failure Intelligence Analysis
    "FailureCorrelator",
    "DependencyImpactAnalyzer",
    "FailureClassifier",
    "FailureClassificationResult",
    "RootCauseAnalyzer",
    "EvidenceRanker",
    "RankedEvidence",
    "RecommendationEngine",
    # Unified Analyzer
    "UnifiedFailureAnalyzer",
]

