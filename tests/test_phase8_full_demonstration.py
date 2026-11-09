"""Phase 8 Full 12-Step Demonstration against Realistic Sample Application (`examples/sample-ecommerce-app`)."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.dependencies import get_background_worker
from apps.api.main import app


def _build_sample_app_zip() -> bytes:
    """Create an in-memory ZIP archive of `examples/sample-ecommerce-app`."""
    repo_root = Path(__file__).resolve().parent.parent
    sample_dir = repo_root / "examples" / "sample-ecommerce-app"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sample_dir.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(sample_dir).as_posix()
                zf.write(file_path, arcname=rel_path)
    return buf.getvalue()


@pytest.mark.anyio
async def test_phase8_full_12_step_demonstration():
    """Execute and verify all 12 steps of the Phase 8 platform demonstration."""
    worker = get_background_worker()
    # Drain any leftover queued jobs from prior tests sharing the singleton queue
    while await worker.process_next_job() is not None:
        pass
    admin_headers = {
        "X-API-Key": "test-admin-key",
        "X-Correlation-ID": "corr-phase8-demo-001",
    }

    zip_bytes = _build_sample_app_zip()
    assert len(zip_bytes) > 200

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # ------------------------------------------------------------------
        # Step 1: Upload application archive
        # ------------------------------------------------------------------
        upload_resp = await client.post(
            "/api/v1/applications/upload",
            data={"name": "sample-ecommerce-platform"},
            files={"file": ("sample-ecommerce-app.zip", zip_bytes, "application/zip")},
            headers=admin_headers,
        )
        assert upload_resp.status_code == 201, upload_resp.text
        app_record = upload_resp.json()
        app_id = app_record["application_id"]
        assert app_record["name"] == "sample-ecommerce-app"
        assert app_record["source_type"] == "archive"
        assert app_record["status"] == "registered"

        # ------------------------------------------------------------------
        # Step 2: Analyze source code
        # ------------------------------------------------------------------
        analyze_resp = await client.post(
            f"/api/v1/applications/{app_id}/analyze",
            headers=admin_headers,
        )
        assert analyze_resp.status_code == 202
        analyze_job_id = analyze_resp.json()["job_id"]
        job_analyze = await worker.process_next_job()
        assert job_analyze is not None
        assert job_analyze.job_id == analyze_job_id
        assert job_analyze.status == "completed"
        assert job_analyze.result["services_count"] >= 3
        assert job_analyze.result["apis_count"] >= 6

        # Verify application status updated to 'analyzed'
        app_get_resp = await client.get(f"/api/v1/applications/{app_id}", headers=admin_headers)
        assert app_get_resp.status_code == 200
        assert app_get_resp.json()["status"] == "analyzed"

        # ------------------------------------------------------------------
        # Step 3: Generate & retrieve architecture graph
        # ------------------------------------------------------------------
        arch_resp = await client.get(
            f"/api/v1/applications/{app_id}/architecture",
            headers=admin_headers,
        )
        assert arch_resp.status_code == 200
        arch_data = arch_resp.json()
        assert arch_data["node_count"] >= 3
        assert len(arch_data["nodes"]) >= 3

        # ------------------------------------------------------------------
        # Step 4: Calculate risk assessment
        # ------------------------------------------------------------------
        risk_resp = await client.get(
            f"/api/v1/applications/{app_id}/risks",
            headers=admin_headers,
        )
        assert risk_resp.status_code == 200
        risk_data = risk_resp.json()
        assert risk_data["application_id"] == app_id
        assert risk_data["risk_score"] > 0
        assert risk_data["findings_count"] >= 1
        assert len(risk_data["findings"]) >= 1

        # ------------------------------------------------------------------
        # Step 5: Generate test plans
        # ------------------------------------------------------------------
        plan_resp = await client.post(
            "/api/v1/testing/plans/generate",
            json={"application_id": app_id, "target_environment": "staging"},
            headers=admin_headers,
        )
        assert plan_resp.status_code == 201
        plan_data = plan_resp.json()
        plan_id = plan_data["plan_id"]
        assert plan_data["test_cases_count"] > 0

        # ------------------------------------------------------------------
        # Step 6: Execute approved tests
        # ------------------------------------------------------------------
        exec_resp = await client.post(
            "/api/v1/testing/executions",
            json={"plan_id": plan_id, "application_id": app_id, "approved": True},
            headers=admin_headers,
        )
        assert exec_resp.status_code == 202
        job_test = await worker.process_next_job()
        assert job_test is not None
        assert job_test.status == "completed"
        test_exec_id = job_test.result["execution_id"]

        exec_status_resp = await client.get(
            f"/api/v1/testing/executions/{test_exec_id}",
            headers=admin_headers,
        )
        assert exec_status_resp.status_code == 200
        assert exec_status_resp.json()["status"] in ("passed", "completed", "partial_failure", "failed")

        # ------------------------------------------------------------------
        # Step 7: Prepare a chaos experiment
        # ------------------------------------------------------------------
        chaos_create_resp = await client.post(
            "/api/v1/chaos/experiments",
            json={
                "name": "Order Service Downstream Network Latency Spike",
                "application_id": app_id,
                "target_service_id": "order-service",
                "fault_type": "network_latency",
                "environment": "staging",
                "duration_seconds": 30,
                "parameters": {"delay_ms": 800, "jitter_ms": 100},
            },
            headers=admin_headers,
        )
        assert chaos_create_resp.status_code == 201
        chaos_exp = chaos_create_resp.json()
        exp_id = chaos_exp["experiment_id"]
        assert chaos_exp["status"] == "validated"

        # ------------------------------------------------------------------
        # Step 8: Validate safety and approval
        # ------------------------------------------------------------------
        # Verify live chaos execution is hard-blocked even for admin
        live_block_resp = await client.post(
            "/api/v1/chaos/executions",
            json={"experiment_id": exp_id, "application_id": app_id, "dry_run": False},
            headers=admin_headers,
        )
        assert live_block_resp.status_code == 400
        assert "disabled" in live_block_resp.json()["message"].lower()

        approve_resp = await client.post(
            f"/api/v1/chaos/experiments/{exp_id}/approve",
            json={
                "approved_by": "principal-sre-reviewer",
                "grant_id": "grant-phase8-001",
                "notes": "Approved for controlled dry-run simulation only",
            },
            headers=admin_headers,
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"].lower() == "approved"

        # ------------------------------------------------------------------
        # Step 9: Execute dry-run simulation
        # ------------------------------------------------------------------
        chaos_exec_resp = await client.post(
            "/api/v1/chaos/executions",
            json={"experiment_id": exp_id, "application_id": app_id, "dry_run": True},
            headers=admin_headers,
        )
        assert chaos_exec_resp.status_code == 202
        job_chaos = await worker.process_next_job()
        assert job_chaos is not None
        assert job_chaos.status == "completed"
        chaos_run_id = job_chaos.result["run_id"]
        assert job_chaos.result["verdict"] in ("DRY_RUN_VERIFIED", "unresolved")

        chaos_status_resp = await client.get(
            f"/api/v1/chaos/executions/{chaos_run_id}",
            headers=admin_headers,
        )
        assert chaos_status_resp.status_code == 200
        chaos_report = chaos_status_resp.json()
        assert chaos_report["dry_run"] is True
        assert chaos_report["live_execution"] is False
        assert chaos_report["verdict"] in ("DRY_RUN_VERIFIED", "unresolved")

        # ------------------------------------------------------------------
        # Step 10: Ingest telemetry
        # ------------------------------------------------------------------
        telem_resp = await client.post(
            "/api/v1/telemetry/ingest",
            json={
                "application_id": app_id,
                "experiment_id": exp_id,
                "metrics": [
                    {
                        "service_id": "order-service",
                        "metric_name": "response_latency_ms",
                        "value": 980.0,
                        "unit": "ms",
                        "timestamp": "2026-11-09T12:00:05Z",
                    },
                    {
                        "service_id": "order-service",
                        "metric_name": "error_rate",
                        "value": 0.18,
                        "unit": "ratio",
                        "timestamp": "2026-11-09T12:00:06Z",
                    },
                    {
                        "service_id": "api-gateway",
                        "metric_name": "response_latency_ms",
                        "value": 1120.0,
                        "unit": "ms",
                        "timestamp": "2026-11-09T12:00:07Z",
                    },
                ],
                "logs": [
                    {
                        "service_id": "order-service",
                        "level": "ERROR",
                        "message": "Downstream inventory-service and orders-db connection pool timeout after 800ms",
                        "timestamp": "2026-11-09T12:00:06Z",
                    }
                ],
                "spans": [
                    {
                        "trace_id": "trace-demo-001",
                        "span_id": "span-demo-001",
                        "service_id": "order-service",
                        "operation_name": "POST /orders",
                        "duration_ms": 980.0,
                        "status": "ERROR",
                    }
                ],
            },
            headers=admin_headers,
        )
        assert telem_resp.status_code == 202
        telem_data = telem_resp.json()
        assert telem_data["metrics_count"] == 3
        assert telem_data["logs_count"] == 1
        assert telem_data["spans_count"] == 1

        # ------------------------------------------------------------------
        # Step 11: Generate failure hypotheses
        # ------------------------------------------------------------------
        intel_resp = await client.post(
            "/api/v1/intelligence/analyze",
            json={
                "application_id": app_id,
                "chaos_report_id": chaos_run_id,
            },
            headers=admin_headers,
        )
        assert intel_resp.status_code == 202
        intel_data = intel_resp.json()
        analysis_id = intel_data["analysis_id"]
        for hypo in intel_data["probable_root_causes"]:
            assert hypo["is_causation_proven"] is False

        # ------------------------------------------------------------------
        # Step 12: Produce consolidated report
        # ------------------------------------------------------------------
        report_resp = await client.get(
            f"/api/v1/intelligence/reports/{analysis_id}",
            headers=admin_headers,
        )
        assert report_resp.status_code == 200
        consolidated_report = report_resp.json()
        assert consolidated_report["analysis_id"] == analysis_id

        summary_dump = {
            "step1_upload_app_id": app_id,
            "step2_analysis": job_analyze.result,
            "step3_architecture": {
                "node_count": arch_data["node_count"],
                "edge_count": arch_data["edge_count"],
                "nodes": [n["name"] for n in arch_data["nodes"]],
            },
            "step4_risk": {
                "risk_score": risk_data["risk_score"],
                "findings_count": risk_data["findings_count"],
            },
            "step5_test_plan": {
                "plan_id": plan_id,
                "test_cases_count": plan_data["test_cases_count"],
            },
            "step6_test_execution": {
                "execution_id": test_exec_id,
                "status": exec_status_resp.json()["status"],
            },
            "step7_chaos_experiment": {
                "experiment_id": exp_id,
                "fault_type": chaos_exp["fault_type"],
                "status": chaos_exp["status"],
            },
            "step8_approval": {
                "status": approve_resp.json()["status"],
                "live_execution_blocked": live_block_resp.status_code == 400,
            },
            "step9_dry_run_execution": {
                "run_id": chaos_run_id,
                "verdict": chaos_report["verdict"],
                "dry_run": chaos_report["dry_run"],
                "live_execution": chaos_report["live_execution"],
            },
            "step10_telemetry": telem_data,
            "step11_failure_intelligence": {
                "analysis_id": analysis_id,
                "anomalies_count": intel_data["anomalies_count"],
                "hypotheses_count": len(intel_data["probable_root_causes"]),
                "recommendations_count": intel_data["recommendations_count"],
                "causation_proven_flags": [
                    h["is_causation_proven"] for h in intel_data["probable_root_causes"]
                ],
            },
            "step12_consolidated_report_id": consolidated_report["analysis_id"],
        }
        print("\n=== PHASE 8 FULL 12-STEP DEMONSTRATION SUMMARY ===")
        print(json.dumps(summary_dump, indent=2))
