"""End-to-End 14-Step Workflow Integration Test for CHAOS-INTEL Phase 7.

Validates the complete integrated workflow across:
1. Application registration / upload
2. Application Intelligence static discovery & dependency detection
3. Architecture graph generation & retrieval
4. Risk assessment & vulnerability scoring
5. Testing Agents test plan generation
6. Approved test suite execution
7. Chaos Engine experiment creation from 12-fault catalog
8. Safety validation & human approval boundary enforcement (Admin key)
9. Controlled dry-run experiment execution (live chaos strictly disabled)
10. Telemetry ingestion (metrics, logs, traces)
11. Multi-signal failure intelligence correlation
12. Ranked root-cause hypotheses (with is_causation_proven = false) & recommendations
13. Consolidated report synthesis
14. End-to-end orchestration pipeline with idempotency guarantees
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from apps.api.dependencies import get_job_queue, get_background_worker

_ROOT = Path(__file__).resolve().parents[1]
_APP_INTEL_PATH = _ROOT / "services" / "application-intelligence"

AUTH_ADMIN = {"X-API-Key": "test-admin-key"}
AUTH_OPERATOR = {"X-API-Key": "test-operator-key"}
AUTH_VIEWER = {"X-API-Key": "test-viewer-key"}


@pytest.mark.asyncio
async def test_complete_14_step_platform_workflow():
    """Execute and validate all 14 integration steps end-to-end."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        corr_id = "corr-e2e-workflow-test-001"
        headers_op = {**AUTH_OPERATOR, "X-Correlation-ID": corr_id}
        headers_adm = {**AUTH_ADMIN, "X-Correlation-ID": corr_id}
        headers_vw = {**AUTH_VIEWER, "X-Correlation-ID": corr_id}

        # -------------------------------------------------------------
        # STEP 1: Application Registration
        # -------------------------------------------------------------
        res_reg = await client.post(
            "/api/v1/applications/register",
            headers=headers_op,
            json={
                "name": "E2ETestService",
                "source_location": str(_APP_INTEL_PATH),
                "source_type": "directory",
            },
        )
        assert res_reg.status_code == 201, f"Step 1 failed: {res_reg.text}"
        app_data = res_reg.json()
        app_id = app_data["application_id"]
        assert app_id.startswith("app-")
        assert app_data["name"] == "E2ETestService"

        # -------------------------------------------------------------
        # STEP 2: Application Intelligence Static Analysis
        # -------------------------------------------------------------
        res_analyze = await client.post(
            f"/api/v1/applications/{app_id}/analyze",
            headers=headers_op,
        )
        assert res_analyze.status_code == 202, f"Step 2 failed: {res_analyze.text}"
        job_id = res_analyze.json()["job_id"]

        # Process job via background worker
        worker = get_background_worker()
        processed_job = await worker.process_next_job()
        assert processed_job is not None
        assert processed_job.status == "completed"

        # Verify application status transitioned to analyzed
        res_app_check = await client.get(f"/api/v1/applications/{app_id}", headers=headers_vw)
        assert res_app_check.status_code == 200
        assert res_app_check.json()["status"] == "analyzed"
        assert res_app_check.json()["services_count"] > 0

        # -------------------------------------------------------------
        # STEP 3: Architecture Graph Retrieval
        # -------------------------------------------------------------
        res_arch = await client.get(f"/api/v1/applications/{app_id}/architecture", headers=headers_vw)
        assert res_arch.status_code == 200, f"Step 3 failed: {res_arch.text}"
        arch_data = res_arch.json()
        assert arch_data["application_id"] == app_id
        assert arch_data["node_count"] > 0
        assert isinstance(arch_data["nodes"], list)

        # -------------------------------------------------------------
        # STEP 4: Risk Assessment Calculation
        # -------------------------------------------------------------
        res_risks = await client.get(f"/api/v1/applications/{app_id}/risks", headers=headers_vw)
        assert res_risks.status_code == 200, f"Step 4 failed: {res_risks.text}"
        risk_data = res_risks.json()
        assert risk_data["application_id"] == app_id
        assert 0 <= risk_data["risk_score"] <= 100
        assert isinstance(risk_data["findings"], list)

        # -------------------------------------------------------------
        # STEP 5: Testing Agents Plan Generation
        # -------------------------------------------------------------
        res_plan = await client.post(
            "/api/v1/testing/plans/generate",
            headers=headers_op,
            json={"application_id": app_id, "options": {"focus": "all"}},
        )
        assert res_plan.status_code == 201, f"Step 5 failed: {res_plan.text}"
        plan_data = res_plan.json()
        plan_id = plan_data["plan_id"]
        assert plan_id.startswith("plan-")
        assert plan_data["test_cases_count"] > 0

        # -------------------------------------------------------------
        # STEP 6: Approved Test Execution
        # -------------------------------------------------------------
        res_exec = await client.post(
            "/api/v1/testing/executions",
            headers=headers_op,
            json={"plan_id": plan_id, "application_id": app_id},
        )
        assert res_exec.status_code == 202, f"Step 6 failed: {res_exec.text}"
        exec_id = res_exec.json()["execution_id"]
        assert exec_id.startswith("exec-")

        # -------------------------------------------------------------
        # STEP 7: Chaos Experiment Preparation
        # -------------------------------------------------------------
        target_service = arch_data["nodes"][0]["service_id"] if arch_data["nodes"] else "default-service"
        res_chaos_create = await client.post(
            "/api/v1/chaos/experiments",
            headers=headers_op,
            json={
                "name": f"Latency injection on {target_service}",
                "application_id": app_id,
                "target_service_id": target_service,
                "fault_type": "network_latency",
                "environment": "staging",
                "duration_seconds": 30,
                "safety_decision_id": "sec-grant-01",
                "parameters": {"latency_ms": 500, "jitter_ms": 50},
            },
        )
        assert res_chaos_create.status_code == 201, f"Step 7 failed: {res_chaos_create.text}"
        exp_data = res_chaos_create.json()
        exp_id = exp_data["experiment_id"]
        assert exp_data["requires_approval"] is True

        # -------------------------------------------------------------
        # STEP 8: Safety Validation & Approval (Admin role required)
        # -------------------------------------------------------------
        # Operator cannot approve -> 403 Forbidden
        res_unauth_appr = await client.post(
            f"/api/v1/chaos/experiments/{exp_id}/approve",
            headers=headers_op,
            json={"approved_by": "operator-bob", "grant_id": "grant-bob"},
        )
        assert res_unauth_appr.status_code == 403

        # Admin approves -> 200 OK
        res_appr = await client.post(
            f"/api/v1/chaos/experiments/{exp_id}/approve",
            headers=headers_adm,
            json={"approved_by": "admin-alice", "grant_id": "grant-alice-01"},
        )
        assert res_appr.status_code == 200

        # -------------------------------------------------------------
        # STEP 9: Controlled Dry-Run Experiment Execution
        # -------------------------------------------------------------
        # Live execution attempt is blocked with 400
        res_live_blocked = await client.post(
            "/api/v1/chaos/executions",
            headers=headers_op,
            json={"experiment_id": exp_id, "application_id": app_id, "dry_run": False},
        )
        assert res_live_blocked.status_code == 400
        assert "Live chaos execution is disabled" in res_live_blocked.json()["message"]

        # Dry-run succeeds -> 202 Accepted
        res_chaos_exec = await client.post(
            "/api/v1/chaos/executions",
            headers=headers_op,
            json={"experiment_id": exp_id, "application_id": app_id, "dry_run": True},
        )
        assert res_chaos_exec.status_code == 202
        run_id = res_chaos_exec.json()["run_id"]
        assert res_chaos_exec.json()["dry_run"] is True
        assert res_chaos_exec.json()["live_execution"] is False

        # -------------------------------------------------------------
        # STEP 10: Telemetry Ingestion
        # -------------------------------------------------------------
        res_telemetry = await client.post(
            "/api/v1/telemetry/ingest",
            headers=headers_op,
            json={
                "metrics": [{"metric_name": "http_p95_latency", "value": 520.0, "unit": "ms"}],
                "logs": [{"level": "WARN", "service": target_service, "message": "High latency detected"}],
                "spans": [{"span_id": "span-1", "service": target_service, "duration_ms": 510}],
            },
        )
        assert res_telemetry.status_code == 202
        assert res_telemetry.json()["metrics_count"] == 1

        # -------------------------------------------------------------
        # STEP 11 & 12: Failure Intelligence & Causation Guardrail
        # -------------------------------------------------------------
        res_fail = await client.post(
            "/api/v1/intelligence/analyze",
            headers=headers_op,
            json={"application_id": app_id, "chaos_report_id": run_id},
        )
        assert res_fail.status_code == 202
        fail_data = res_fail.json()
        analysis_id = fail_data["analysis_id"]

        # INVARIANT CHECK: Inferred causes must NEVER be presented as proven fact
        for hypo in fail_data["probable_root_causes"]:
            assert hypo["is_causation_proven"] is False, "Violation: Hypothesis claimed proven causation!"
            assert 0.0 <= hypo["confidence"] <= 1.0

        # Retrieve recommendations
        res_recs = await client.get("/api/v1/intelligence/recommendations", headers=headers_vw)
        assert res_recs.status_code == 200
        assert "recommendations" in res_recs.json()

        # -------------------------------------------------------------
        # STEP 13: Consolidated Report Retrieval
        # -------------------------------------------------------------
        res_rep = await client.get(f"/api/v1/intelligence/reports/{analysis_id}", headers=headers_vw)
        assert res_rep.status_code == 200
        assert res_rep.json()["analysis_id"] == analysis_id

        # -------------------------------------------------------------
        # STEP 14: Distributed Orchestration Pipeline with Idempotency
        # -------------------------------------------------------------
        idemp_key = "idemp-workflow-e2e-unique-01"
        res_pipe1 = await client.post(
            "/api/v1/orchestration/pipeline",
            headers=headers_op,
            json={
                "source_path": str(_APP_INTEL_PATH),
                "application_name": "OrchestratedApp",
                "idempotency_key": idemp_key,
                "approved_by": "lead-operator",
            },
        )
        assert res_pipe1.status_code == 202
        pipe_job_id = res_pipe1.json()["job_id"]

        # Worker processes pipeline job
        pipe_job = await worker.process_next_job()
        assert pipe_job is not None
        assert pipe_job.status == "completed"
        assert pipe_job.result["status"] == "COMPLETED"
        assert len(pipe_job.result["timeline"]) == 10

        # Verify idempotency deduplication on second trigger
        res_pipe2 = await client.post(
            "/api/v1/orchestration/pipeline",
            headers=headers_op,
            json={
                "source_path": str(_APP_INTEL_PATH),
                "application_name": "OrchestratedApp",
                "idempotency_key": idemp_key,
                "approved_by": "lead-operator",
            },
        )
        assert res_pipe2.status_code == 202
        pipe_job2 = await worker.process_next_job()
        assert pipe_job2 is not None
        # Must return existing completed result immediately
        assert pipe_job2.result["pipeline_id"] == pipe_job.result["pipeline_id"]

