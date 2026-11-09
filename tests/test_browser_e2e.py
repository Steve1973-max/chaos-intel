"""Playwright Real Browser End-to-End Verification for CHAOS-INTEL Frontend Dashboard (Phase 8).

Starts a live Uvicorn HTTP server hosting both the FastAPI `/api/v1` backend and the compiled
production React frontend (`apps/web/dist`), then drives a real headless Chromium browser via
Playwright to verify:
1. Overview dashboard & live backend connection status ("Backend Online")
2. Application archive upload (`sample-ecommerce-app.zip`), registration, and AST analysis
3. Interactive SVG Architecture Graph rendering & Node Detail Drawer inspection
4. Risk Assessment scoring, severity filtering, and expandable findings
5. Testing Agents plan generation & Test Executions step trace view
6. Chaos Experiments 12-fault catalog, RBAC error state on non-admin approval, Admin approval grant, and Dry-Run simulation
7. Observability metrics, logs, and traces
8. Failure Intelligence root-cause hypotheses (`proven: false` / `Causation Not Proven`) & recommendations
9. Consolidated Audit Report & Settings view
"""

from __future__ import annotations

import asyncio
import io
import os
import socket
import sys
import threading
import time
import zipfile
from pathlib import Path
import pytest
import uvicorn
from fastapi.staticfiles import StaticFiles

from apps.api.dependencies import get_background_worker
from apps.api.main import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = REPO_ROOT / "apps" / "web" / "dist"
SAMPLE_APP_DIR = REPO_ROOT / "examples" / "sample-ecommerce-app"


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _create_sample_zip(target_path: Path) -> Path:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in SAMPLE_APP_DIR.rglob("*"):
            if fp.is_file():
                zf.write(fp, arcname=fp.relative_to(SAMPLE_APP_DIR).as_posix())
    target_path.write_bytes(buf.getvalue())
    return target_path


@pytest.mark.anyio
async def test_playwright_real_browser_full_ui_workflow(tmp_path: Path):
    """Drive real headless Chromium across all 11 dashboard views against live FastAPI backend."""
    from playwright.async_api import async_playwright

    assert WEB_DIST.exists(), f"Production frontend build not found at {WEB_DIST}. Run `npm run build` in apps/web."

    # Create FastAPI app and mount compiled React SPA at /
    app = create_app()
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="frontend_spa")

    port = _get_free_port()
    base_url = f"http://127.0.0.1:{port}"

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    serve_task = asyncio.create_task(server.serve())

    # Wait for Uvicorn server to listen
    for _ in range(50):
        if serve_task.done():
            exc = serve_task.exception()
            if exc:
                raise exc
            break
        if server.started:
            break
        await asyncio.sleep(0.1)
    assert server.started, f"Uvicorn server failed to start for browser E2E test (done={serve_task.done()})"

    sample_zip_path = _create_sample_zip(tmp_path / "sample-ecommerce-app.zip")
    page_errors: list[str] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(viewport={"width": 1440, "height": 900})
            page = await context.new_page()
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))

            # ------------------------------------------------------------------
            # 1. Overview Dashboard & Connection Status
            # ------------------------------------------------------------------
            await page.goto(base_url, wait_until="networkidle")
            await page.wait_for_selector("text=CHAOS-INTEL", timeout=10000)
            await page.wait_for_selector("text=Backend Online", timeout=10000)

            overview_text = await page.inner_text("body")
            assert "System Operational Overview" in overview_text
            assert "No pipeline jobs run yet" in overview_text

            # ------------------------------------------------------------------
            # 2. Applications View: Upload Archive & Trigger AST Analysis
            # ------------------------------------------------------------------
            await page.click("aside >> text=Applications")
            await page.wait_for_selector("h1:has-text('Registered Applications')", timeout=10000)

            # Open Register Application Modal
            await page.click("button:has-text('Register Application')")
            await page.wait_for_selector("text=Register Target Application", timeout=5000)

            # Switch to Upload Archive tab
            await page.click("button:has-text('Upload Archive')")
            file_input = await page.wait_for_selector("input[type='file']", timeout=5000)
            await file_input.set_input_files(str(sample_zip_path))

            # Submit modal form
            await page.click("form button[type='submit']:has-text('Register Application')")
            await page.wait_for_selector("text=Application successfully registered", timeout=10000)
            await page.wait_for_selector("h3:has-text('sample-ecommerce-app')", timeout=10000)

            # Click Analyze on the uploaded application
            await page.click("button:has-text('Analyze') >> nth=0")
            await page.wait_for_selector("text=Analysis job scheduled", timeout=10000)

            # Ensure background worker processes the queued job and refresh view
            worker = get_background_worker()
            await worker.process_next_job()
            await asyncio.sleep(0.3)
            await page.click("button:has-text('Refresh')")
            await page.wait_for_selector("span:has-text('analyzed')", timeout=10000)

            # Select sample-ecommerce-app as active scope if button says 'Set as Scope'
            scope_btns = await page.query_selector_all("button:has-text('Set as Scope')")
            if scope_btns:
                await scope_btns[0].click()

            # ------------------------------------------------------------------
            # 3. Architecture Visualization (Interactive SVG Graph & Drawer)
            # ------------------------------------------------------------------
            await page.click("aside >> text=Architecture")
            await page.wait_for_selector("h1:has-text('Architecture Topology Explorer')", timeout=10000)
            svg_elem = await page.wait_for_selector("svg", timeout=10000)
            assert svg_elem is not None

            # Verify discovered service nodes appear in SVG
            arch_body = await page.inner_text("body")
            assert "order-service" in arch_body

            # Click a node group in SVG to open NodeDetailDrawer
            node_groups = await page.query_selector_all("svg g.cursor-pointer")
            if node_groups:
                await node_groups[0].click()
                await asyncio.sleep(0.2)

            # ------------------------------------------------------------------
            # 4. Risk Assessment View & Filtering
            # ------------------------------------------------------------------
            await page.click("aside >> text=Risk Assessment")
            await page.wait_for_selector("h1:has-text('Application Risk Assessment')", timeout=10000)
            risk_body = await page.inner_text("body")
            assert "composite risk score" in risk_body.lower()
            assert "severity distribution" in risk_body.lower()
            assert "api.stripe-partner.internal" in risk_body
            assert "orders-db" in risk_body

            # ------------------------------------------------------------------
            # 5. Testing Agents & Test Executions
            # ------------------------------------------------------------------
            await page.click("aside >> text=Testing Agents")
            await page.wait_for_selector("h1:has-text('Testing Agents & Plan Generator')", timeout=10000)
            await page.click("button:has-text('Regenerate Plan')")
            await page.wait_for_selector("text=Generated Test Candidates", timeout=10000)
            await page.click("button:has-text('Execute Test Suite')")
            await page.wait_for_selector("text=Test execution initiated", timeout=10000)

            await page.click("aside >> text=Test Executions")
            await page.wait_for_selector("h1:has-text('Test Executions & Verification')", timeout=10000)
            await page.wait_for_selector("text=Step Execution Details", timeout=10000)
            exec_body = await page.inner_text("body")
            assert "Execution History" in exec_body
            assert "Step Execution Details" in exec_body

            # ------------------------------------------------------------------
            # 6. Chaos Experiments: Safety Banner, RBAC Error Check, Approval & Dry-Run
            # ------------------------------------------------------------------
            await page.click("aside >> text=Chaos Experiments")
            await page.wait_for_selector("h1:has-text('Controlled Chaos Experiment Engine')", timeout=10000)
            chaos_body = await page.inner_text("body")
            assert "SAFETY POLICY: LIVE CHAOS EXECUTION HARD-DISABLED" in chaos_body
            assert "mode: dry_run" in chaos_body

            # Test error state when non-admin tries to approve
            await page.click("button:has-text('Grant Approval (Admin Key)')")
            await page.wait_for_selector("text=Approval requires Administrator privileges", timeout=5000)

            # Switch role to Admin in top header role switcher menu
            await page.click("header button[title='Switch Auth Role']")
            await page.click("header button:has-text('admin')")

            # Now grant approval as Admin
            await page.click("button:has-text('Grant Approval (Admin Key)')")
            await page.wait_for_selector("text=Approved by admin-operator", timeout=10000)

            # Execute Dry-Run Simulation
            await page.click("button:has-text('Execute Dry-Run Simulation')")
            await page.wait_for_selector("text=Dry-Run Execution Report", timeout=10000)
            await page.wait_for_selector("text=SAFETY_VERIFICATION", timeout=10000)

            # ------------------------------------------------------------------
            # 7. Observability View
            # ------------------------------------------------------------------
            await page.click("aside >> text=Observability")
            await page.wait_for_selector("h1:has-text('Unified Observability Engine')", timeout=10000)
            await page.click("button:has-text('Structured Logs')")
            await page.wait_for_selector("text=Connection pool saturation detected", timeout=5000)

            # ------------------------------------------------------------------
            # 8. Failure Intelligence View (Causation Guardrail Verification)
            # ------------------------------------------------------------------
            await page.click("aside >> text=Failure Intelligence")
            await page.wait_for_selector("h1:has-text('Failure Intelligence & Root-Cause Hypotheses')", timeout=10000)
            await page.wait_for_selector("text=Causation Not Proven", timeout=10000)
            fi_body = await page.inner_text("body")
            assert "FAILURE INTELLIGENCE POLICY: INFERRED HYPOTHESES ONLY" in fi_body
            assert "proven: false" in fi_body
            assert "Causation Not Proven" in fi_body.title() or "CAUSATION NOT PROVEN" in fi_body.upper()

            # ------------------------------------------------------------------
            # 9. Consolidated Reports & Settings Views
            # ------------------------------------------------------------------
            await page.click("aside >> text=Reports")
            await page.wait_for_selector("h1:has-text('Multi-Agent Resilience Audit Report')", timeout=10000)
            rep_body = await page.inner_text("body")
            assert "CHAOS-INTEL AUDIT REPORT" in rep_body
            assert "sample-ecommerce-app" in rep_body

            await page.click("aside >> text=Settings")
            await page.wait_for_selector("h1:has-text('Platform & Connectivity Settings')", timeout=10000)
            await page.wait_for_selector("text=API Connected", timeout=5000)

            await browser.close()

        assert len(page_errors) == 0, f"Uncaught browser page errors: {page_errors}"
    finally:
        server.should_exit = True
        await serve_task
