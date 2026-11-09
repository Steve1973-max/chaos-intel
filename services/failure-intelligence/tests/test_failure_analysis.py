"""Tests for Failure Intelligence Analysis Engine components."""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

_FI_ROOT = Path(__file__).resolve().parents[1]
_APP_INTEL_ROOT = Path(__file__).resolve().parents[2] / "application-intelligence"

for p in (_FI_ROOT, _APP_INTEL_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from src.models.application import ApplicationModel
from src.models.architecture import ArchitectureGraph, GraphEdge, GraphNode
from src.models.dependency import Dependency
from src.models.service import Service
from src.models.api import Api

from analysis.dependency_impact_analyzer import DependencyImpactAnalyzer
from analysis.evidence_ranker import EvidenceRanker
from analysis.failure_classifier import FailureClassifier
from analysis.failure_correlator import FailureCorrelator
from analysis.recommendation_engine import RecommendationEngine
from analysis.root_cause_analyzer import RootCauseAnalyzer
from schemas.anomaly import Anomaly
from schemas.finding import CorrelatedFailureCluster, DependencyImpact, RootCauseHypothesis
from schemas.telemetry import StructuredLogEntry, TraceSpan


@pytest.fixture
def sample_microservice_app() -> ApplicationModel:
    return ApplicationModel(
        application_id="app-store-01",
        name="Store Application",
        services=[
            Service(service_id="srv-web", application_id="app-store-01", name="web", type="frontend", source_path="apps/web"),
            Service(service_id="srv-order", application_id="app-store-01", name="order", type="backend", source_path="apps/order"),
            Service(service_id="srv-payment", application_id="app-store-01", name="payment", type="backend", source_path="apps/payment"),
            Service(service_id="srv-db", application_id="app-store-01", name="db", type="database", source_path="apps/db"),
        ],
        architecture=ArchitectureGraph(
            nodes=[
                GraphNode(node_id="n-web", service_id="srv-web", name="web", node_type="frontend"),
                GraphNode(node_id="n-order", service_id="srv-order", name="order", node_type="service"),
                GraphNode(node_id="n-payment", service_id="srv-payment", name="payment", node_type="service"),
                GraphNode(node_id="n-db", service_id="srv-db", name="database", node_type="database"),
            ],
            edges=[
                GraphEdge(edge_id="e1", source_node_id="n-web", target_node_id="n-order", edge_type="calls"),
                GraphEdge(edge_id="e2", source_node_id="n-order", target_node_id="n-payment", edge_type="calls"),
                GraphEdge(edge_id="e3", source_node_id="n-order", target_node_id="n-db", edge_type="calls"),
            ],
        ),
        apis=[
            Api(api_id="api-checkout", path="/checkout", method="POST", service_id="srv-order"),
            Api(api_id="api-pay", path="/charge", method="POST", service_id="srv-payment"),
        ],
    )


def test_failure_correlator():
    correlator = FailureCorrelator()
    anomalies = [
        Anomaly(
            anomaly_id="a-1",
            timestamp="2026-11-05T12:00:01Z",
            affected_service="srv-db",
            metric="infra.cpu_utilization",
            observed_value=98.0,
            baseline_value=25.0,
            severity="critical",
            detection_method="threshold",
            confidence=0.95,
        )
    ]
    logs = [
        StructuredLogEntry(
            log_id="l-1",
            timestamp="2026-11-05T12:00:02Z",
            service_id="srv-db",
            level="ERROR",
            message="Database connection pool exhausted",
            correlation_id="corr-123",
            error_type="PoolExhaustedError",
        )
    ]
    spans = [
        TraceSpan(
            trace_id="tr-1",
            span_id="sp-1",
            service_id="srv-order",
            operation_name="SQL INSERT",
            start_time="2026-11-05T12:00:03Z",
            end_time="2026-11-05T12:00:06Z",
            duration_ms=3000.0,
            status_code="ERROR",
        )
    ]
    test_failures = [
        {"execution_id": "exec-1", "test_case_id": "tc-order", "service_id": "srv-order", "status": "failed"}
    ]
    chaos_events = [
        {"fault_type": "cpu_stress", "target_id": "srv-db", "verdict": "passed", "timestamp": "2026-11-05T12:00:00Z"}
    ]

    clusters = correlator.correlate(
        correlation_id="corr-123",
        anomalies=anomalies,
        error_logs=logs,
        error_spans=spans,
        test_failures=test_failures,
        chaos_events=chaos_events,
    )

    assert len(clusters) == 1
    c = clusters[0]
    assert c.correlation_id == "corr-123"
    assert c.primary_affected_service == "srv-db"  # Target of chaos and earliest error
    assert "srv-order" in c.affected_services
    assert "srv-db" in c.affected_services
    assert len(c.anomalies) == 1
    assert len(c.error_logs) == 1
    assert len(c.error_spans) == 1


def test_dependency_impact_analyzer(sample_microservice_app):
    analyzer = DependencyImpactAnalyzer()

    # If srv-db fails: srv-order calls srv-db; srv-web calls srv-order
    impact = analyzer.analyze(
        root_service_id="srv-db",
        app=sample_microservice_app,
        observed_failing_services=["srv-db", "srv-order"],
    )

    assert impact.root_service_id == "srv-db"
    assert "srv-order" in impact.downstream_impacted_services
    assert "srv-web" in impact.downstream_impacted_services
    assert impact.cascading_failure is True  # srv-order was also failing
    assert "POST /checkout" in impact.impacted_apis
    assert impact.blast_radius_score >= 0.5


def test_failure_classifier_categories():
    classifier = FailureClassifier()

    # Database error cluster
    db_cluster = CorrelatedFailureCluster(
        cluster_id="c-db",
        correlation_id="corr-1",
        time_window_start="2026-11-05T12:00:00Z",
        time_window_end="2026-11-05T12:00:10Z",
        primary_affected_service="srv-db",
        error_logs=[
            StructuredLogEntry(
                log_id="l-1",
                timestamp="2026-11-05T12:00:01Z",
                service_id="srv-db",
                level="ERROR",
                message="PostgreSQL query execution failed: deadlock detected",
                error_type="DeadlockError",
            )
        ],
    )
    res_db = classifier.classify(db_cluster)
    assert res_db.category == "Database"
    assert res_db.confidence >= 0.70

    # Resource exhaustion cluster
    res_cluster = CorrelatedFailureCluster(
        cluster_id="c-res",
        correlation_id="corr-2",
        time_window_start="2026-11-05T12:00:00Z",
        time_window_end="2026-11-05T12:00:10Z",
        primary_affected_service="srv-order",
        chaos_events=[{"fault_type": "memory_pressure", "target_id": "srv-order"}],
        anomalies=[
            Anomaly(
                anomaly_id="a-1",
                timestamp="2026-11-05T12:00:01Z",
                affected_service="srv-order",
                metric="infra.memory_utilization",
                observed_value=96.0,
                baseline_value=30.0,
                severity="critical",
                detection_method="resource_saturation",
                confidence=0.95,
            )
        ],
    )
    res_res = classifier.classify(res_cluster)
    assert res_res.category == "ResourceExhaustion"
    assert res_res.confidence >= 0.55


def test_root_cause_analyzer_competing_hypotheses_and_causation_invariant(sample_microservice_app):
    impact_analyzer = DependencyImpactAnalyzer()
    rc_analyzer = RootCauseAnalyzer()

    # DB failed first at T=0; order service threw errors at T=2; web frontend threw 500s at T=4
    cluster = CorrelatedFailureCluster(
        cluster_id="c-e2e",
        correlation_id="corr-e2e",
        time_window_start="2026-11-05T12:00:00Z",
        time_window_end="2026-11-05T12:00:10Z",
        primary_affected_service="srv-db",
        affected_services=["srv-db", "srv-order", "srv-web"],
        chaos_events=[{"fault_type": "disk_io_pressure", "target_id": "srv-db"}],
        anomalies=[
            Anomaly(
                anomaly_id="a-db",
                timestamp="2026-11-05T12:00:00Z",
                affected_service="srv-db",
                metric="infra.disk_utilization",
                observed_value=99.0,
                baseline_value=30.0,
                severity="critical",
                detection_method="threshold",
                confidence=0.95,
            ),
            Anomaly(
                anomaly_id="a-order",
                timestamp="2026-11-05T12:00:02Z",
                affected_service="srv-order",
                metric="app.error_rate",
                observed_value=0.25,
                baseline_value=0.01,
                severity="high",
                detection_method="threshold",
                confidence=0.90,
            ),
        ],
        error_logs=[
            StructuredLogEntry(
                log_id="l-order",
                timestamp="2026-11-05T12:00:03Z",
                service_id="srv-order",
                level="ERROR",
                message="Timeout calling database srv-db",
            )
        ],
    )

    impact = impact_analyzer.analyze("srv-db", sample_microservice_app, ["srv-db", "srv-order"])
    hypotheses = rc_analyzer.analyze_root_causes(cluster, dependency_impact=impact)

    assert len(hypotheses) >= 2  # Multiple competing hypotheses
    top = hypotheses[0]
    # Primary hypothesis must point to srv-db (temporal earliest + chaos injection target)
    assert top.probable_root_cause_service == "srv-db"
    assert top.rank == 1
    assert top.confidence > hypotheses[1].confidence

    # STRICT INVARIANT: Correlation is never claimed as proven physical causation
    for h in hypotheses:
        assert h.is_causation_proven is False

    # Second hypothesis (e.g. srv-order) must include conflicting temporal evidence
    assert len(hypotheses[1].conflicting_evidence) > 0


def test_evidence_ranker():
    ranker = EvidenceRanker()
    raw = [
        {"type": "circumstantial", "detail": "User report of slow page", "source": "user"},
        {"type": "chaos_injection_target", "detail": "Fault injected against srv-db", "source": "chaos"},
        {"type": "metric_threshold_breach", "detail": "CPU breached 95%", "source": "metrics"},
    ]
    ranked = ranker.rank_evidence(raw)
    assert len(ranked) == 3
    # Chaos injection (0.95) and metric breach (0.90) rank higher than circumstantial (0.50)
    assert ranked[0].evidence_type == "chaos_injection_target"
    assert ranked[1].evidence_type == "metric_threshold_breach"
    assert ranked[2].evidence_type == "circumstantial"


def test_recommendation_engine():
    engine = RecommendationEngine()
    impact = DependencyImpact(
        root_service_id="srv-payment",
        directly_affected_services=["srv-payment"],
        downstream_impacted_services=["srv-order", "srv-web"],
        cascading_failure=True,
    )
    from schemas.finding import RootCauseHypothesis
    root_cause = RootCauseHypothesis(
        hypothesis_id="hyp-1",
        probable_root_cause_service="srv-payment",
        failure_category="Network",
        title="Network partition on payment gateway",
        explanation="Payment gateway timed out during peak load.",
        confidence=0.88,
        rank=1,
        is_causation_proven=False,
        supporting_evidence=[{"type": "metric", "detail": "latency > 4s"}],
    )

    recs = engine.generate_recommendations([root_cause], dependency_impact=impact)
    assert len(recs) >= 2  # Circuit breaker recommendation + SPOF/redundancy recommendation

    cb_rec = next(r for r in recs if r.category == "circuit_breaker")
    assert cb_rec.target_service == "srv-payment"
    assert len(cb_rec.remediation_steps) >= 3
    assert cb_rec.confidence == 0.88
    assert len(cb_rec.supporting_evidence_ids) > 0

    spof_rec = next(r for r in recs if r.category == "redundancy")
    assert spof_rec.priority == "critical"  # Cascading failure marked as critical priority
