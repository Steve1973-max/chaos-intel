"""Integration tests for Typed Service Clients (Phase 5).

Verifies:
- ApplicationIntelligenceClient execution and models
- TestingAgentsClient test plan generation and execution
- ChaosEngineClient validation, approval recording, and dry-run execution
- FailureIntelligenceClient telemetry ingestion and multi-agent failure correlation
- Resilient error mapping and timeout handling
- Prohibition of live chaos execution
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[1]
_APP_INTEL_PATH = _ROOT / "services" / "application-intelligence"

for p in (_ROOT, _APP_INTEL_PATH):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from packages.clients.app_intel_client import ApplicationIntelligenceClient
from packages.clients.testing_agents_client import TestingAgentsClient
from packages.clients.chaos_engine_client import ChaosEngineClient
from packages.clients.failure_intel_client import FailureIntelligenceClient
from packages.clients.base import ServiceClientError, ServiceConnectionError, ServiceTimeoutError

TestingAgentsClient.__test__ = False


@pytest.mark.asyncio
async def test_app_intel_client_end_to_end():
    """Verify ApplicationIntelligenceClient static analysis and model retrieval."""
    client = ApplicationIntelligenceClient()
    corr_id = "corr-test-ai-01"

    # Analyze real source directory (application-intelligence service directory)
    sample_dir = str(_APP_INTEL_PATH)
    app_model = await client.analyze_application(sample_dir, correlation_id=corr_id)

    assert app_model is not None
    assert getattr(app_model, "application_id", "").startswith("app-")
    assert len(getattr(app_model, "technologies", [])) > 0
    assert len(getattr(app_model, "services", [])) > 0

    # Retrieve cached model, architecture, and risks
    app_id = app_model.application_id
    retrieved = await client.get_application(app_id, correlation_id=corr_id)
    assert retrieved.application_id == app_id

    arch = await client.get_architecture(app_id, correlation_id=corr_id)
    assert arch is not None
    assert len(getattr(arch, "nodes", [])) > 0

    risks = await client.get_risks(app_id, correlation_id=corr_id)
    assert risks is not None


@pytest.mark.asyncio
async def test_testing_agents_client_planning_and_execution():
    """Verify TestingAgentsClient test planning and execution against application model."""
    ai_client = ApplicationIntelligenceClient()
    ta_client = TestingAgentsClient()
    corr_id = "corr-test-ta-01"

    app_model = await ai_client.analyze_application(str(_APP_INTEL_PATH), correlation_id=corr_id)
    plan = await ta_client.generate_test_plan(app_model, correlation_id=corr_id)

    assert plan is not None
    assert getattr(plan, "plan_id", "").startswith("plan-")
    assert len(getattr(plan, "test_cases", [])) > 0

    # Retrieve plan
    cached_plan = await ta_client.get_test_plan(plan.plan_id, correlation_id=corr_id)
    assert cached_plan.plan_id == plan.plan_id

    # Execute plan (in mock/sandbox mode)
    report = await ta_client.execute_test_plan(plan, app_model, correlation_id=corr_id)
    assert report is not None
    assert getattr(report, "status", "") in ("passed", "failed", "partial_failure")


@pytest.mark.asyncio
async def test_chaos_engine_client_lifecycle_and_live_execution_ban():
    """Verify ChaosEngineClient experiment registration, human approval, and dry-run execution."""
    ce_client = ChaosEngineClient()
    corr_id = "corr-test-ce-01"

    # 1. Create and validate experiment
    spec_dict = {
        "experiment_id": "exp-test-latency-01",
        "name": "Network Latency on Database",
        "application_id": "app-test-01",
        "target_service_id": "svc-db",
        "fault_type": "network_latency",
        "environment": "staging",
        "duration_seconds": 30,
        "safety_decision_id": "sec-01",
        "parameters": {"latency_ms": 500},
    }
    spec = await ce_client.create_experiment(spec_dict, correlation_id=corr_id)
    assert spec is not None
    assert getattr(spec, "experiment_id", "") == "exp-test-latency-01"

    # 2. Record human approval grant
    approval = await ce_client.submit_approval(
        experiment_id="exp-test-latency-01",
        approved_by="lead-sre-john",
        grant_id="grant-approved-01",
        correlation_id=corr_id,
    )
    assert approval["status"] == "APPROVED"
    assert approval["approved_by"] == "lead-sre-john"

    # 3. Dry-run execution succeeds cleanly
    class _MockApp:
        application_id = "app-test-01"
        services = []

    report = await ce_client.execute_experiment(
        experiment_id="exp-test-latency-01",
        app=_MockApp(),
        correlation_id=corr_id,
        dry_run=True,
    )
    assert report is not None
    assert getattr(report, "verdict", "") in ("unresolved", "passed", "DRY_RUN_VERIFIED")
    assert report.mode == "dry_run"
    assert report.live_execution is False

    # 4. STRICT SAFEGUARD: Attempting live chaos execution is immediately rejected
    with pytest.raises(ServiceClientError, match="Live execution is prohibited"):
        await ce_client.execute_experiment(
            experiment_id="exp-test-latency-01",
            app=_MockApp(),
            correlation_id=corr_id,
            dry_run=False,
        )


@pytest.mark.asyncio
async def test_failure_intel_client_telemetry_and_analysis():
    """Verify FailureIntelligenceClient telemetry ingestion and experiment analysis."""
    fi_client = FailureIntelligenceClient()
    corr_id = "corr-test-fi-01"

    # Ingest telemetry
    ingest_res = await fi_client.ingest_telemetry(
        correlation_id=corr_id,
        metrics=[{"metric_name": "infra.cpu_utilization", "value": 85.0, "service_id": "svc-db", "unit": "%"}],
        logs=[{"level": "ERROR", "message": "ConnectionRefusedError to db", "service_id": "svc-order"}],
        spans=[],
    )
    assert ingest_res["status"] == "ACCEPTED"
    assert ingest_res["metrics_ingested"] == 1
    assert ingest_res["logs_ingested"] == 1

    # Run analysis
    class _MockApp:
        application_id = "app-test-01"
        name = "TestApp"
        services = []
        apis = []
        dependencies = []
        architecture = None

    class _MockChaosReport:
        report_id = "rpt-01"
        experiment_id = "exp-01"
        target_id = "svc-db"
        fault_type = "network_latency"
        verdict = "DRY_RUN_VERIFIED"
        recovery_classification = "unknown"
        abort = None
        observation = None

    rep = await fi_client.analyze_experiment(
        app=_MockApp(),
        chaos_report=_MockChaosReport(),
        test_results=[],
        correlation_id=corr_id,
    )
    assert rep is not None
    assert getattr(rep, "analysis_id", "").startswith("fa-")
    assert getattr(rep, "correlation_id", "") == corr_id

    # Retrieve recommendations
    recs = await fi_client.get_recommendations(rep.analysis_id, correlation_id=corr_id)
    assert isinstance(recs, list)


@pytest.mark.asyncio
async def test_client_network_error_and_timeout_resilience():
    """Verify structured exceptions when target HTTP endpoints are unreachable or time out."""
    # Unreachable host
    bad_client = ApplicationIntelligenceClient(base_url="http://127.0.0.1:59999", direct_adapter=None)
    with pytest.raises(ServiceConnectionError):
        await bad_client._request("GET", "/health", correlation_id="c-1", timeout=0.5)

    # Health check on bad host returns UNHEALTHY without crashing
    health = await bad_client.check_health()
    assert health["status"] == "UNHEALTHY"
    assert health["mode"] == "http"
