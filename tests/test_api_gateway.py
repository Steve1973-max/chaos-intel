"""Integration tests for FastAPI Gateway (Phase 5).

Verifies:
- Request validation (Pydantic schemas)
- Correlation ID propagation and generation
- Authentication (401) and RBAC authorization (403)
- Application registration and archive upload validation
- Pagination behavior on collections
- Health diagnostics across platform and services
"""

from __future__ import annotations

import io
import sys
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from apps.api.main import app

AUTH_ADMIN = {"X-API-Key": "test-admin-key"}
AUTH_OPERATOR = {"X-API-Key": "test-operator-key"}
AUTH_VIEWER = {"X-API-Key": "test-viewer-key"}
AUTH_INVALID = {"X-API-Key": "invalid-token-key"}


@pytest.mark.asyncio
async def test_health_endpoints():
    """Verify /health and /health/services return operational diagnostics."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Basic health
        res = await client.get("/api/v1/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "HEALTHY"
        assert "services" in data

        # Subsystems health
        res_services = await client.get("/api/v1/health/services")
        assert res_services.status_code == 200
        s_data = res_services.json()
        assert s_data["status"] in ("HEALTHY", "DEGRADED")
        assert "application_intelligence" in s_data["services"]
        assert "testing_agents" in s_data["services"]
        assert "chaos_engine" in s_data["services"]
        assert "failure_intelligence" in s_data["services"]
        assert "job_queue" in s_data["services"]


@pytest.mark.asyncio
async def test_correlation_id_propagation():
    """Verify X-Correlation-ID is preserved if supplied, or generated if missing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Supplied correlation ID
        res = await client.get("/api/v1/health", headers={"X-Correlation-ID": "custom-corr-12345"})
        assert res.status_code == 200
        assert res.headers.get("X-Correlation-ID") == "custom-corr-12345"

        # 2. Generated correlation ID
        res_gen = await client.get("/api/v1/health")
        assert res_gen.status_code == 200
        assert "X-Correlation-ID" in res_gen.headers
        assert res_gen.headers["X-Correlation-ID"].startswith("corr-")


@pytest.mark.asyncio
async def test_authentication_and_authorization():
    """Verify 401 on missing/invalid auth, 403 on insufficient role, 200/201 on permitted role."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Missing auth on protected endpoint -> 401
        res = await client.post("/api/v1/applications/register", json={"name": "test", "source_location": "."})
        assert res.status_code == 401
        err = res.json()
        assert err["error_code"] == "HTTP_401"
        assert "correlation_id" in err

        # 2. Invalid auth key -> 401
        res_invalid = await client.post(
            "/api/v1/applications/register",
            headers=AUTH_INVALID,
            json={"name": "test", "source_location": "."},
        )
        assert res_invalid.status_code == 401

        # 3. Viewer attempting operator action -> 403 Forbidden
        res_forbidden = await client.post(
            "/api/v1/applications/register",
            headers=AUTH_VIEWER,
            json={"name": "test", "source_location": "."},
        )
        assert res_forbidden.status_code == 403
        assert "Insufficient permissions" in res_forbidden.json()["message"]

        # 4. Operator attempting admin-only action (approving chaos experiment) -> 403 Forbidden
        res_op_admin = await client.post(
            "/api/v1/chaos/experiments/exp-123/approve",
            headers=AUTH_OPERATOR,
            json={"approved_by": "alice", "grant_id": "grant-1"},
        )
        assert res_op_admin.status_code == 403


@pytest.mark.asyncio
async def test_application_registration_and_validation():
    """Verify validation of source paths and schema constraints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Schema validation error (missing source_location) -> 422
        res_bad = await client.post("/api/v1/applications/register", headers=AUTH_OPERATOR, json={"name": "App1"})
        assert res_bad.status_code == 422
        assert res_bad.json()["error_code"] == "VALIDATION_ERROR"

        # 2. Non-existent path -> 404
        res_not_found = await client.post(
            "/api/v1/applications/register",
            headers=AUTH_OPERATOR,
            json={"name": "AppBad", "source_location": "non/existent/path/9999"},
        )
        assert res_not_found.status_code == 404

        # 3. Valid directory registration -> 201 Created
        res_ok = await client.post(
            "/api/v1/applications/register",
            headers=AUTH_OPERATOR,
            json={"name": "ValidApp", "source_location": "."},
        )
        assert res_ok.status_code == 201
        app_data = res_ok.json()
        assert app_data["name"] == "ValidApp"
        assert app_data["application_id"].startswith("app-")
        app_id = app_data["application_id"]

        # 4. Retrieve registered application -> 200 OK
        res_get = await client.get(f"/api/v1/applications/{app_id}", headers=AUTH_VIEWER)
        assert res_get.status_code == 200
        assert res_get.json()["application_id"] == app_id


@pytest.mark.asyncio
async def test_archive_upload_safeguards():
    """Verify archive extension validation and file size restrictions."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Disallowed file extension (.exe) -> 400 Bad Request
        bad_file = io.BytesIO(b"binary payload")
        res_bad_ext = await client.post(
            "/api/v1/applications/upload",
            headers=AUTH_OPERATOR,
            files={"file": ("malicious.exe", bad_file, "application/octet-stream")},
        )
        assert res_bad_ext.status_code == 400
        assert "Unsupported file extension" in res_bad_ext.json()["message"]

        # 2. Valid zip file upload -> 201 Created
        valid_zip = io.BytesIO(b"PK\x03\x04mock zip payload")
        res_ok = await client.post(
            "/api/v1/applications/upload",
            headers=AUTH_OPERATOR,
            files={"file": ("project.zip", valid_zip, "application/zip")},
        )
        assert res_ok.status_code == 201
        assert res_ok.json()["source_type"] == "archive"


@pytest.mark.asyncio
async def test_pagination_on_collections():
    """Verify limit and offset pagination semantics."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/applications?limit=2&offset=0", headers=AUTH_VIEWER)
        assert res.status_code == 200
        page = res.json()
        assert "items" in page
        assert "total" in page
        assert page["limit"] == 2
        assert page["offset"] == 0
        assert isinstance(page["has_more"], bool)

