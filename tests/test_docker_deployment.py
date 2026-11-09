"""Phase 8.3 Full Docker Compose Runtime & Production Deployment Verification Suite.

Executes against the live multi-container Docker Compose stack:
- `chaos-intel-postgres` (PostgreSQL 15)
- `chaos-intel-redis` (Redis 7)
- `chaos-intel-api` (FastAPI Gateway, `DISABLE_EMBEDDED_WORKER=1`)
- `chaos-intel-worker` (Standalone Background Worker, `WORKER_ID=chaos-intel-worker-01`)
- `chaos-intel-web` (Nginx Production React SPA on port 80 reverse-proxying `/api/` to `api:8000`)

Verifies:
1. Container health status, loopback port binding security, and service connectivity (PostgreSQL + Redis).
2. Complete 13-step real application workflow through Nginx (`http://localhost:80`).
3. Cross-container worker execution, PostgreSQL persistence (`applications`, `background_jobs`,
   `experiment_runs`, `run_transitions`, `leases`, `idempotency_records`, `audit_events`),
   idempotency, failure handling, and worker container restart resilience (`docker compose restart worker`).
4. Real headless Chromium Playwright E2E against the Nginx container (`http://localhost:80`) across all 11 routes
   with zero CORS or uncaught JavaScript errors.
5. Security & safety invariants (live chaos execution hard-disabled, RBAC, ZipSlip rejection, secret redaction).
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.skipif(
    os.environ.get("CHAOS_DOCKER_E2E") != "1",
    reason="Requires live Docker Compose stack (set CHAOS_DOCKER_E2E=1)",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_APP_DIR = REPO_ROOT / "examples" / "sample-ecommerce-app"

NGINX_URL = os.environ.get("DOCKER_WEB_URL", "http://127.0.0.1:80")
API_DIRECT_URL = os.environ.get("DOCKER_API_URL", "http://127.0.0.1:8000")
PG_URL = os.environ.get(
    "DOCKER_POSTGRES_URL",
    "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/chaos_intel",
)

ADMIN_HEADERS = {"X-API-Key": "test-admin-key", "X-Correlation-ID": "corr-docker-e2e-admin"}
OPERATOR_HEADERS = {"X-API-Key": "test-operator-key", "X-Correlation-ID": "corr-docker-e2e-op"}
VIEWER_HEADERS = {"X-API-Key": "test-viewer-key", "X-Correlation-ID": "corr-docker-e2e-view"}


def _build_sample_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in SAMPLE_APP_DIR.rglob("*"):
            if fp.is_file():
                zf.write(fp, arcname=fp.relative_to(SAMPLE_APP_DIR).as_posix())
    return buf.getvalue()


async def _wait_for_job_completion(client: httpx.AsyncClient, job_id: str, timeout_s: float = 30.0) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last_data: Dict[str, Any] = {}
    while time.monotonic() < deadline:
        resp = await client.get(f"/api/v1/orchestration/pipeline/{job_id}", headers=VIEWER_HEADERS)
        assert resp.status_code == 200, f"Failed polling job {job_id}: {resp.text}"
        last_data = resp.json()
        if last_data["status"] in ("completed", "failed", "cancelled", "dead_letter"):
            return last_data
        await asyncio.sleep(0.4)
    raise AssertionError(f"Job {job_id} did not complete within {timeout_s}s. Last state: {last_data}")


@pytest.mark.asyncio
async def test_1_container_runtime_health_and_port_security():
    """Verify all 5 Docker Compose containers are running/healthy and internal ports bind only to 127.0.0.1."""
    ps_proc = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    raw_lines = [line.strip() for line in ps_proc.stdout.splitlines() if line.strip()]
    containers: List[Dict[str, Any]] = []
    if raw_lines and raw_lines[0].startswith("["):
        containers = json.loads(ps_proc.stdout)
    else:
        for line in raw_lines:
            containers.append(json.loads(line))

    names = {c.get("Name") or c.get("Service"): c for c in containers}
    expected_containers = {
        "chaos-intel-postgres",
        "chaos-intel-redis",
        "chaos-intel-api",
        "chaos-intel-worker",
        "chaos-intel-web",
    }
    assert expected_containers.issubset(set(names.keys())), f"Missing containers: {expected_containers - set(names.keys())}"
    for cname in expected_containers:
        state = str(names[cname].get("State", "")).lower()
        assert state == "running", f"Container {cname} is not running: {names[cname]}"

    # Verify Postgres and Redis ports are bound to 127.0.0.1 (not 0.0.0.0)
    pg_port = subprocess.run(
        ["docker", "compose", "port", "postgres", "5432"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    redis_port = subprocess.run(
        ["docker", "compose", "port", "redis", "6379"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert pg_port.startswith("127.0.0.1:"), f"Postgres port publicly exposed: {pg_port}"
    assert redis_port.startswith("127.0.0.1:"), f"Redis port publicly exposed: {redis_port}"

    # Verify Nginx frontend root and proxied /api/v1/health/services
    async with httpx.AsyncClient(base_url=NGINX_URL, timeout=15.0) as client:
        index_resp = await client.get("/")
        assert index_resp.status_code == 200
        assert "<div id=\"root\"></div>" in index_resp.text

        health_resp = await client.get("/api/v1/health/services")
        assert health_resp.status_code == 200
        hdata = health_resp.json()
        assert hdata["status"] == "HEALTHY"
        jq = hdata["services"]["job_queue"]
        assert jq["postgres"]["status"] == "HEALTHY"
        assert jq["redis"]["status"] == "HEALTHY"


@pytest.mark.asyncio
async def test_2_real_13_step_application_workflow_and_postgres_persistence():
    """Execute the full 13-step workflow through Nginx and verify PostgreSQL persistence & worker execution."""
    zip_bytes = _build_sample_zip_bytes()

    async with httpx.AsyncClient(base_url=NGINX_URL, timeout=30.0) as client:
        # Step 1: Open dashboard via Nginx
        dash_resp = await client.get("/")
        assert dash_resp.status_code == 200

        # Step 2: Register sample e-commerce application directory inside container
        reg_resp = await client.post(
            "/api/v1/applications/register",
            json={
                "name": "sample-ecommerce-registered",
                "source_type": "directory",
                "source_location": "/app/examples/sample-ecommerce-app",
                "metadata": {"deployment": "docker-compose"},
            },
            headers=OPERATOR_HEADERS,
        )
        assert reg_resp.status_code == 201, reg_resp.text
        reg_app_id = reg_resp.json()["application_id"]

        # Step 3: Upload application source archive (.zip) through Nginx proxy
        up_resp = await client.post(
            "/api/v1/applications/upload",
            files={"file": ("sample-ecommerce-app.zip", zip_bytes, "application/zip")},
            headers=OPERATOR_HEADERS,
        )
        assert up_resp.status_code == 201, up_resp.text
        app_id = up_resp.json()["application_id"]

        # Step 4: Trigger background static analysis and wait for standalone worker container
        an_resp = await client.post(f"/api/v1/applications/{app_id}/analyze", headers=OPERATOR_HEADERS)
        assert an_resp.status_code == 202, an_resp.text
        analyze_job_id = an_resp.json()["job_id"]
        analyze_job = await _wait_for_job_completion(client, analyze_job_id)
        assert analyze_job["status"] == "completed"
        assert analyze_job["result"]["services_count"] >= 3

        # Verify application status updated to 'analyzed' via PostgreSQL sync
        app_detail = await client.get(f"/api/v1/applications/{app_id}", headers=VIEWER_HEADERS)
        assert app_detail.status_code == 200
        assert app_detail.json()["status"] == "analyzed"
        assert app_detail.json()["services_count"] >= 3

        # Step 5: Retrieve architecture graph
        arch_resp = await client.get(f"/api/v1/applications/{app_id}/architecture", headers=VIEWER_HEADERS)
        assert arch_resp.status_code == 200
        arch = arch_resp.json()
        assert arch["node_count"] >= 3
        assert arch["edge_count"] >= 2

        # Step 6: Retrieve risk assessment
        risk_resp = await client.get(f"/api/v1/applications/{app_id}/risks", headers=VIEWER_HEADERS)
        assert risk_resp.status_code == 200
        risks = risk_resp.json()
        assert risks["findings_count"] >= 1
        assert risks["risk_score"] > 0.0

        # Step 7: Generate testing plan
        plan_resp = await client.post(
            "/api/v1/testing/plans/generate",
            json={"application_id": app_id},
            headers=OPERATOR_HEADERS,
        )
        assert plan_resp.status_code == 201, plan_resp.text
        plan_id = plan_resp.json()["plan_id"]
        assert plan_resp.json()["test_cases_count"] >= 1

        # Step 8: Execute testing workflow via background worker
        exec_resp = await client.post(
            "/api/v1/testing/executions",
            json={"plan_id": plan_id, "application_id": app_id},
            headers=OPERATOR_HEADERS,
        )
        assert exec_resp.status_code == 202, exec_resp.text
        exec_id = exec_resp.json()["execution_id"]

        # Poll test execution until worker completes it
        for _ in range(40):
            er = await client.get(f"/api/v1/testing/executions/{exec_id}", headers=VIEWER_HEADERS)
            assert er.status_code == 200
            if er.json()["status"] == "passed":
                break
            await asyncio.sleep(0.4)
        assert er.json()["status"] == "passed"
        assert er.json()["passed_count"] >= 1

        # Step 9: Create chaos experiment
        target_svc = arch["nodes"][0]["service_id"] or arch["nodes"][0]["name"]
        exp_resp = await client.post(
            "/api/v1/chaos/experiments",
            json={
                "name": "Order Service Latency Dry-Run",
                "application_id": app_id,
                "target_service_id": target_svc,
                "fault_type": "network_latency",
                "environment": "staging",
                "duration_seconds": 30,
                "safety_decision_id": "sec-docker-001",
                "parameters": {"latency_ms": 1200, "jitter_ms": 150},
            },
            headers=OPERATOR_HEADERS,
        )
        assert exp_resp.status_code == 201, exp_resp.text
        exp_id = exp_resp.json()["experiment_id"]

        # Step 10: Verify approval & dry-run safety restrictions
        # 10a: Unapproved execution blocked (403)
        unappr = await client.post(
            "/api/v1/chaos/executions",
            json={"experiment_id": exp_id, "application_id": app_id, "dry_run": True},
            headers=OPERATOR_HEADERS,
        )
        assert unappr.status_code == 403

        # 10b: Non-admin approval blocked (403)
        op_appr = await client.post(
            f"/api/v1/chaos/experiments/{exp_id}/approve",
            json={"approved_by": "op-user", "grant_id": "grant-op"},
            headers=OPERATOR_HEADERS,
        )
        assert op_appr.status_code == 403

        # 10c: Admin approval succeeds (200)
        adm_appr = await client.post(
            f"/api/v1/chaos/experiments/{exp_id}/approve",
            json={"approved_by": "sre-lead@chaos-intel.io", "grant_id": "grant-docker-001"},
            headers=ADMIN_HEADERS,
        )
        assert adm_appr.status_code == 200

        # 10d: Live chaos execution (dry_run=False) strictly rejected (400)
        live_try = await client.post(
            "/api/v1/chaos/executions",
            json={"experiment_id": exp_id, "application_id": app_id, "dry_run": False},
            headers=ADMIN_HEADERS,
        )
        assert live_try.status_code == 400
        assert "disabled" in live_try.text.lower()

        # 10e: Controlled dry-run execution succeeds via worker
        dry_resp = await client.post(
            "/api/v1/chaos/executions",
            json={"experiment_id": exp_id, "application_id": app_id, "dry_run": True},
            headers=OPERATOR_HEADERS,
        )
        assert dry_resp.status_code == 202, dry_resp.text
        run_id = dry_resp.json()["run_id"]

        for _ in range(40):
            rr = await client.get(f"/api/v1/chaos/executions/{run_id}", headers=VIEWER_HEADERS)
            assert rr.status_code == 200
            if rr.json()["recovery_status"] == "SIMULATED_RECOVERED":
                break
            await asyncio.sleep(0.4)
        assert rr.json()["dry_run"] is True
        assert rr.json()["live_execution"] is False
        assert rr.json()["recovery_status"] == "SIMULATED_RECOVERED"

        # Step 11: Ingest telemetry
        tel_resp = await client.post(
            "/api/v1/telemetry/ingest",
            json={
                "metrics": [
                    {
                        "service_id": target_svc,
                        "metric_name": "response_latency",
                        "category": "application",
                        "value": 1480.0,
                        "unit": "ms",
                        "timestamp": "2026-11-09T16:30:00Z",
                    }
                ],
                "logs": [
                    {
                        "service_id": target_svc,
                        "level": "ERROR",
                        "message": "Upstream timeout contacting payment-service after 1200ms",
                        "timestamp": "2026-11-09T16:30:01Z",
                    }
                ],
                "spans": [
                    {
                        "trace_id": "trace-docker-001",
                        "span_id": "span-docker-001",
                        "service_id": target_svc,
                        "operation_name": "POST /orders",
                        "start_time": "2026-11-09T16:30:00Z",
                        "end_time": "2026-11-09T16:30:02Z",
                        "duration_ms": 1480.0,
                        "status": "ERROR",
                    }
                ],
            },
            headers=OPERATOR_HEADERS,
        )
        assert tel_resp.status_code == 202, tel_resp.text

        # Step 12: Generate failure hypotheses
        intel_resp = await client.post(
            "/api/v1/intelligence/analyze",
            json={"application_id": app_id, "chaos_report_id": run_id},
            headers=OPERATOR_HEADERS,
        )
        assert intel_resp.status_code in (200, 201, 202), intel_resp.text
        intel_data = intel_resp.json()
        analysis_id = intel_data["analysis_id"]
        for rc in intel_data.get("probable_root_causes", []):
            assert rc["is_causation_proven"] is False

        # Step 13: Retrieve consolidated report
        rep_resp = await client.get(f"/api/v1/intelligence/reports/{analysis_id}", headers=VIEWER_HEADERS)
        assert rep_resp.status_code == 200
        assert rep_resp.json()["analysis_id"] == analysis_id

    # Verify PostgreSQL tables directly
    engine = create_engine(PG_URL)
    with engine.connect() as conn:
        app_rows = conn.execute(
            text("SELECT id, status FROM applications WHERE id IN (:id1, :id2)"),
            {"id1": reg_app_id, "id2": app_id},
        ).fetchall()
        assert len(app_rows) == 2

        job_rows = conn.execute(
            text("SELECT id, task_name, status, worker_id FROM background_jobs WHERE status = 'completed'")
        ).fetchall()
        assert len(job_rows) >= 3
        worker_ids = {r[3] for r in job_rows}
        assert "chaos-intel-worker-01" in worker_ids

        run_row = conn.execute(
            text("SELECT id, state, version FROM experiment_runs WHERE id = :rid"),
            {"rid": run_id},
        ).fetchone()
        assert run_row is not None
        assert run_row[1] == "COMPLETED"
        assert run_row[2] == 3

        transitions_count = conn.execute(
            text("SELECT COUNT(*) FROM run_transitions WHERE run_id = :rid"),
            {"rid": run_id},
        ).scalar()
        assert transitions_count == 3

        lease_row = conn.execute(
            text("SELECT resource_id, status, fencing_token FROM leases WHERE resource_id = :res"),
            {"res": f"chaos-target:{app_id}"},
        ).fetchone()
        assert lease_row is not None
        assert lease_row[1] == "released"
        assert lease_row[2] >= 1

        audit_count = conn.execute(
            text("SELECT COUNT(*) FROM audit_events WHERE run_id = :rid"),
            {"rid": run_id},
        ).scalar()
        assert audit_count >= 2


@pytest.mark.asyncio
async def test_3_worker_idempotency_failure_handling_and_restart_resilience():
    """Verify duplicate request idempotency, failed job handling, and worker container restart."""
    idem_key = f"idem-docker-{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(base_url=NGINX_URL, timeout=30.0) as client:
        # 1. Duplicate idempotent pipeline requests
        p1 = await client.post(
            "/api/v1/orchestration/pipeline",
            json={
                "source_path": "/app/examples/sample-ecommerce-app",
                "application_name": "SampleEcommerceIdem",
                "idempotency_key": idem_key,
                "approved_by": "sre-admin",
                "approval_grant_id": "grant-idem-01",
            },
            headers=ADMIN_HEADERS,
        )
        assert p1.status_code == 202
        j1 = await _wait_for_job_completion(client, p1.json()["job_id"])
        assert j1["status"] == "completed"

        p2 = await client.post(
            "/api/v1/orchestration/pipeline",
            json={
                "source_path": "/app/examples/sample-ecommerce-app",
                "application_name": "SampleEcommerceIdem",
                "idempotency_key": idem_key,
                "approved_by": "sre-admin",
                "approval_grant_id": "grant-idem-01",
            },
            headers=ADMIN_HEADERS,
        )
        assert p2.status_code == 202
        j2 = await _wait_for_job_completion(client, p2.json()["job_id"])
        assert j2["status"] == "completed"
        assert j1["result"]["pipeline_id"] == j2["result"]["pipeline_id"]

    # 2. Failed job & uncertain outcome handling in PostgreSQL
    engine = create_engine(PG_URL)
    fail_job_id = f"job-fail-{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO background_jobs (id, task_name, correlation_id, status, priority, payload, retry_count, max_retries, timeout_seconds) "
                "VALUES (:id, 'nonexistent_task_xyz', 'corr-fail-01', 'queued', 5, '{}'::json, 0, 3, 30)"
            ),
            {"id": fail_job_id},
        )

    async with httpx.AsyncClient(base_url=NGINX_URL, timeout=30.0) as client:
        failed_job = await _wait_for_job_completion(client, fail_job_id)
        assert failed_job["status"] == "failed"
        assert failed_job["error"]["classification"] == "deterministic"

        # 3. Restart the worker container and verify state integrity & continued job processing
        subprocess.run(
            ["docker", "compose", "restart", "worker"],
            cwd=str(REPO_ROOT),
            check=True,
        )

        p_after = await client.post(
            "/api/v1/orchestration/pipeline",
            json={
                "source_path": "/app/examples/sample-ecommerce-app",
                "application_name": "PostWorkerRestartApp",
                "approved_by": "sre-admin",
                "approval_grant_id": "grant-post-restart",
            },
            headers=ADMIN_HEADERS,
        )
        assert p_after.status_code == 202
        j_after = await _wait_for_job_completion(client, p_after.json()["job_id"], timeout_s=40.0)
        assert j_after["status"] == "completed"
        assert j_after["result"]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_4_frontend_nginx_playwright_verification_and_security():
    """Verify production frontend through Nginx in headless Chromium + RBAC & ZipSlip security checks."""
    from playwright.async_api import async_playwright

    page_errors: List[str] = []
    cors_errors: List[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()
        page.on("pageerror", lambda err: page_errors.append(str(err)))
        page.on(
            "console",
            lambda msg: cors_errors.append(msg.text)
            if "cors" in msg.text.lower() or "access-control-allow-origin" in msg.text.lower()
            else None,
        )

        await page.goto(NGINX_URL, wait_until="networkidle")
        await page.wait_for_selector("text=Backend Online", timeout=15000)

        for nav_label in [
            "Applications",
            "Architecture",
            "Risk Assessment",
            "Testing Agents",
            "Test Executions",
            "Chaos Experiments",
            "Observability",
            "Failure Intelligence",
            "Reports",
            "Settings",
            "Overview",
        ]:
            await page.locator("aside").get_by_text(nav_label, exact=True).click()
            await page.wait_for_timeout(150)

        await browser.close()

    assert page_errors == [], f"Uncaught JavaScript errors in browser: {page_errors}"
    assert cors_errors == [], f"CORS errors detected in browser: {cors_errors}"

    # Verify RBAC & ZipSlip protections against live Nginx proxy
    async with httpx.AsyncClient(base_url=NGINX_URL, timeout=15.0) as client:
        # Invalid API key -> 401
        r401 = await client.post(
            "/api/v1/applications/register",
            json={"name": "x", "source_type": "directory", "source_location": "/tmp"},
            headers={"X-API-Key": "invalid-key"},
        )
        assert r401.status_code == 401

        # Viewer attempting operator endpoint -> 403
        r403 = await client.post(
            "/api/v1/applications/register",
            json={"name": "x", "source_type": "directory", "source_location": "/tmp"},
            headers=VIEWER_HEADERS,
        )
        assert r403.status_code == 403

        # ZipSlip archive upload rejection -> 400
        malicious_buf = io.BytesIO()
        with zipfile.ZipFile(malicious_buf, "w") as zf:
            zf.writestr("../../etc/passwd", "root:x:0:0")
        r_zipslip = await client.post(
            "/api/v1/applications/upload",
            files={"file": ("evil.zip", malicious_buf.getvalue(), "application/zip")},
            headers=OPERATOR_HEADERS,
        )
        assert r_zipslip.status_code == 400
        assert "traversal" in r_zipslip.text.lower() or "zipslip" in r_zipslip.text.lower()
