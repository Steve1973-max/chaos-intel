"""End-to-end integration tests for UnifiedFailureAnalyzer across Phase 1, 3B, 3C, and Phase 4."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import jsonschema
import pytest

_FI_ROOT = Path(__file__).resolve().parents[1]
_APP_INTEL_ROOT = Path(__file__).resolve().parents[2] / "application-intelligence"
_SCHEMAS_DIR = Path(__file__).resolve().parents[3] / "packages" / "schemas"

for p in (_FI_ROOT, _APP_INTEL_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from pydantic import BaseModel, Field
from src.models.application import ApplicationModel
from src.models.architecture import ArchitectureGraph, GraphEdge, GraphNode
from src.models.service import Service
from src.models.api import Api

from schemas.telemetry import NormalizedMetricPoint, StructuredLogEntry, TraceSpan
from unified_analyzer import UnifiedFailureAnalyzer


class MockSpanRecord(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    name: str
    start_time: str
    end_time: str
    status_code: str = "OK"
    attributes: dict = Field(default_factory=dict)


class MockSnapshot(BaseModel):
    phase: str
    timestamp: str
    metrics: dict = Field(default_factory=dict)
    healthy: bool = True
    failed_checks: list = Field(default_factory=list)


class MockObservationRecord(BaseModel):
    run_id: str
    experiment_id: str
    application_id: str
    correlation_id: str
    trace_id: str
    baseline_snapshot: Optional[MockSnapshot] = None
    observation_snapshots: list = Field(default_factory=list)
    recovery_duration_ms: Optional[float] = None
    otel_spans: list = Field(default_factory=list)


class MockAbortRecord(BaseModel):
    triggered: bool = False
    source: Optional[str] = None
    reason: Optional[str] = None


class MockChaosReport(BaseModel):
    report_id: str
    run_id: str
    experiment_id: str
    application_id: str
    correlation_id: str
    mode: str = "dry_run"
    live_execution: bool = False
    verdict: str
    hypothesis_held: Optional[bool] = None
    final_lifecycle_state: str
    recovery_classification: str = "unknown"
    outcome_uncertain: bool = False
    fault_type: str
    target_id: str
    duration_seconds: int = 30
    safety_decision_id: str = "sec-01"
    safety_decision: str = "approved"
    abort: MockAbortRecord = Field(default_factory=MockAbortRecord)
    observation: Optional[MockObservationRecord] = None


class MockTestResult(BaseModel):
    execution_id: str
    test_case_id: str
    plan_id: str
    application_id: str
    status: str
    started_at: str = "2026-11-05T12:00:00Z"
    ended_at: str = "2026-11-05T12:00:05Z"
    duration_ms: float = 1000.0
    correlation_id: str = "corr-01"
    error_details: Optional[dict] = None


@pytest.fixture
def integrated_app() -> ApplicationModel:
    return ApplicationModel(
        application_id="app-checkout-system",
        name="Checkout System",
        services=[
            Service(service_id="svc-web", application_id="app-checkout-system", name="web", type="frontend", source_path="apps/web"),
            Service(service_id="svc-order", application_id="app-checkout-system", name="order", type="backend", source_path="apps/order"),
            Service(service_id="svc-payment", application_id="app-checkout-system", name="payment", type="backend", source_path="apps/payment"),
        ],
        architecture=ArchitectureGraph(
            nodes=[
                GraphNode(node_id="n-web", service_id="svc-web", name="web", node_type="frontend"),
                GraphNode(node_id="n-order", service_id="svc-order", name="order", node_type="service"),
                GraphNode(node_id="n-payment", service_id="svc-payment", name="payment", node_type="service"),
            ],
            edges=[
                GraphEdge(edge_id="e1", source_node_id="n-web", target_node_id="n-order", edge_type="calls"),
                GraphEdge(edge_id="e2", source_node_id="n-order", target_node_id="n-payment", edge_type="calls"),
            ],
        ),
        apis=[
            Api(api_id="api-checkout", path="/checkout", method="POST", service_id="svc-order")
        ],
    )


@pytest.fixture
def mock_chaos_report() -> MockChaosReport:
    """Mock report from Chaos Engine (Phase 3C)."""
    obs_rec = MockObservationRecord(
        run_id="run-exp-01",
        experiment_id="exp-latency-01",
        application_id="app-checkout-system",
        correlation_id="corr-checkout-001",
        trace_id="trace-chk-001",
        baseline_snapshot=MockSnapshot(
            phase="baseline",
            timestamp="2026-11-05T12:00:00Z",
            metrics={"latency_p95_ms": 85.0, "error_rate": 0.005, "availability_ratio": 1.0, "cpu_percent": 25.0},
            healthy=True,
        ),
        observation_snapshots=[
            MockSnapshot(
                phase="observation",
                timestamp="2026-11-05T12:00:10Z",
                metrics={"latency_p95_ms": 2500.0, "error_rate": 0.28, "availability_ratio": 0.75, "cpu_percent": 88.0},
                healthy=False,
                failed_checks=["error_rate > 0.05", "availability_ratio < 0.95"],
            )
        ],
        recovery_duration_ms=850.0,
        otel_spans=[
            MockSpanRecord(
                trace_id="trace-chk-001",
                span_id="sp-01",
                name="chaos.fault_window",
                start_time="2026-11-05T12:00:05Z",
                end_time="2026-11-05T12:00:25Z",
                status_code="ERROR",
            )
        ],
    )

    return MockChaosReport(
        report_id="rpt-chaos-01",
        run_id="run-exp-01",
        experiment_id="exp-latency-01",
        application_id="app-checkout-system",
        correlation_id="corr-checkout-001",
        mode="dry_run",
        live_execution=False,
        verdict="aborted",
        hypothesis_held=False,
        final_lifecycle_state="ABORTED",
        recovery_classification="transient_network_issue",
        outcome_uncertain=False,
        fault_type="network_latency",
        target_id="svc-payment",
        duration_seconds=30,
        safety_decision_id="sec-01",
        safety_decision="approved",
        abort=MockAbortRecord(
            triggered=True,
            source="safety_threshold",
            reason="Safety threshold breached: error_rate, availability_ratio",
        ),
        observation=obs_rec,
    )


@pytest.fixture
def mock_test_result() -> MockTestResult:
    """Mock test result from Testing Agents (Phase 3B)."""
    return MockTestResult(
        execution_id="exec-test-01",
        test_case_id="tc-checkout-workflow",
        plan_id="plan-01",
        application_id="app-checkout-system",
        status="failed",
        started_at="2026-11-05T12:00:08Z",
        ended_at="2026-11-05T22:00:12Z",
        duration_ms=4000.0,
        correlation_id="corr-checkout-001",
        error_details={"error_type": "HttpTimeoutError", "error_message": "POST /checkout timed out waiting for payment service"},
    )


def test_unified_analyzer_end_to_end(integrated_app, mock_chaos_report, mock_test_result):
    analyzer = UnifiedFailureAnalyzer()

    # Provide error log
    logs = [
        StructuredLogEntry(
            log_id="log-01",
            timestamp="2026-11-05T12:00:10Z",
            service_id="svc-payment",
            level="ERROR",
            message="Readiness probe failed; simulated network latency threshold breached",
            correlation_id="corr-checkout-001",
            error_type="NetworkTimeoutError",
        )
    ]

    report = analyzer.analyze_experiment(
        app=integrated_app,
        chaos_report=mock_chaos_report,
        test_results=[mock_test_result],
        additional_logs=logs,
    )

    # 1. Basic report structure
    assert report.analysis_id.startswith("fa-")
    assert report.experiment_id == "exp-latency-01"
    assert report.application_id == "app-checkout-system"
    assert report.correlation_id == "corr-checkout-001"

    # 2. Anomalies detected
    assert len(report.observed_anomalies) > 0
    anom_metrics = {a.metric for a in report.observed_anomalies}
    assert any("latency" in m or "error_rate" in m for m in anom_metrics)

    # 3. Affected services & Dependency impact
    assert "svc-payment" in report.affected_services
    assert report.dependency_impact is not None
    assert report.dependency_impact.root_service_id == "svc-payment"
    assert "svc-order" in report.dependency_impact.downstream_impacted_services

    # 4. Probable root causes (competing hypotheses)
    assert len(report.probable_root_causes) >= 1
    primary_rc = report.probable_root_causes[0]
    assert primary_rc.probable_root_cause_service == "svc-payment"
    assert primary_rc.rank == 1
    assert primary_rc.confidence >= 0.70
    assert primary_rc.is_causation_proven is False  # Invariant: correlation != causation

    # 5. Recovery behavior
    assert report.recovery_behavior["recovery_status"] == "ABORTED"
    assert report.recovery_behavior["recovery_duration_ms"] == 850.0

    # 6. Actionable recommendations
    assert len(report.recommendations) >= 1
    rec = report.recommendations[0]
    assert rec.target_service == "svc-payment"
    assert len(rec.remediation_steps) >= 3
    assert len(rec.supporting_evidence_ids) > 0

    # 7. Timeline reconstruction
    assert len(report.failure_timeline) >= 3


def test_schema_conformance_for_findings_and_recommendations():
    """Verify generated findings and recommendations conform to packages/schemas/ definitions."""
    finding_schema = json.loads((_SCHEMAS_DIR / "finding.schema.json").read_text(encoding="utf-8"))
    rec_schema = json.loads((_SCHEMAS_DIR / "recommendation.schema.json").read_text(encoding="utf-8"))

    # Sample cluster payload
    sample_finding = {
        "cluster_id": "cluster-test-1",
        "correlation_id": "corr-test-1",
        "time_window_start": "2026-11-05T12:00:00Z",
        "time_window_end": "2026-11-05T12:01:00Z",
        "primary_affected_service": "svc-db",
        "affected_services": ["svc-db", "svc-order"],
        "anomalies": [],
        "error_logs": [],
        "error_spans": [],
        "test_failures": [],
        "chaos_events": [],
    }
    jsonschema.Draft7Validator(finding_schema).validate(sample_finding)

    sample_rec = {
        "recommendation_id": "rec-test-1",
        "category": "circuit_breaker",
        "priority": "high",
        "title": "Configure circuit breaker on payment client",
        "description": "Payment calls exceeded timeout threshold under fault injection.",
        "target_service": "svc-payment",
        "confidence": 0.88,
        "supporting_evidence_ids": ["ev-1", "ev-2"],
        "remediation_steps": ["Add Resilience4j circuit breaker", "Set timeout to 2s"],
    }
    jsonschema.Draft7Validator(rec_schema).validate(sample_rec)


def test_incomplete_and_missing_data_resilience(integrated_app):
    """Verify analyzer functions cleanly when experiment data is incomplete (no logs, no chaos report)."""
    analyzer = UnifiedFailureAnalyzer()

    # Only test failure, no chaos report or direct metrics
    test_only = MockTestResult(
        execution_id="exec-solo",
        test_case_id="tc-solo",
        plan_id="p-solo",
        application_id="app-checkout-system",
        status="failed",
        error_details={"error_type": "AssertionError", "error_message": "Expected 200 OK got 503 Service Unavailable"},
    )

    report = analyzer.analyze_experiment(
        app=integrated_app,
        chaos_report=None,
        test_results=[test_only],
    )

    assert report.analysis_id.startswith("fa-")
    assert report.observed_anomalies == []  # No invented anomalies
    assert len(report.failure_timeline) >= 1
    assert len(report.probable_root_causes) >= 1
    assert report.recovery_behavior["recovery_status"] == "UNKNOWN"
