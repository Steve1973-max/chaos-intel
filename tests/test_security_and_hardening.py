"""Security, Hardening, and Safeguard Integration Tests for Phase 7."""

import io
import time
import zipfile
import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.main import app
from apps.api.config import config
from workers.worker import redact_secrets


AUTH_OPERATOR = {"X-API-Key": "test-operator-key"}
AUTH_ADMIN = {"X-API-Key": "test-admin-key"}
AUTH_VIEWER = {"X-API-Key": "test-viewer-key"}


@pytest.mark.asyncio
async def test_security_headers_enforcement():
    """Verify security headers (nosniff, DENY, XSS-Protection, Referrer-Policy) on responses."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/api/v1/health")
        assert res.status_code == 200
        headers = res.headers
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("X-Frame-Options") == "DENY"
        assert headers.get("X-XSS-Protection") == "1; mode=block"
        assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


@pytest.mark.asyncio
async def test_cors_preflight_and_headers():
    """Verify CORS headers are returned for authorized origins."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Preflight OPTIONS request
        res = await client.options(
            "/api/v1/applications",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-Key,Content-Type",
            },
        )
        assert res.status_code == 200
        assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"
        assert "POST" in res.headers.get("access-control-allow-methods", "")


@pytest.mark.asyncio
async def test_zip_slip_path_traversal_rejection():
    """Verify malicious archives attempting path traversal (Zip Slip) are rejected with 400 Bad Request."""
    # Craft a malicious zip containing a directory traversal path ../../evil.txt
    malicious_buf = io.BytesIO()
    with zipfile.ZipFile(malicious_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../../etc/cron.d/malicious_job", "echo hacked")
    malicious_buf.seek(0)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/applications/upload",
            headers=AUTH_OPERATOR,
            files={"file": ("slip.zip", malicious_buf, "application/zip")},
        )
        assert res.status_code == 400
        assert "ZipSlip" in res.json()["message"] or "path traversal" in res.json()["message"].lower()


@pytest.mark.asyncio
async def test_filename_path_traversal_sanitization():
    """Verify directory traversal in upload filename parameter is sanitized."""
    valid_buf = io.BytesIO()
    with zipfile.ZipFile(valid_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("safe.py", "print('hello world')")
    valid_buf.seek(0)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/applications/upload",
            headers=AUTH_OPERATOR,
            files={"file": ("../../../../etc/passwd.zip", valid_buf, "application/zip")},
        )
        assert res.status_code == 201
        data = res.json()
        # Filename must be sanitized and not contain directory traversal slashes
        assert ".." not in data["source_location"]
        assert "passwd" in data["name"]


@pytest.mark.asyncio
async def test_rate_limiting_enforcement():
    """Verify rate limiter blocks excessive requests with 429 Too Many Requests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Rapidly fire requests exceeding limit
        hit_429 = False
        for _ in range(config.rate_limit_requests_per_minute + 10):
            res = await client.get("/api/v1/applications", headers=AUTH_VIEWER)
            if res.status_code == 429:
                hit_429 = True
                assert res.json()["error_code"] == "RATE_LIMIT_EXCEEDED"
                assert "Retry-After" in res.headers
                break
        assert hit_429, "Rate limiter did not trigger 429 under flood request traffic"


def test_log_credential_redaction():
    """Verify redaction of sensitive tokens and passwords from log strings."""
    raw_log = 'User authenticated with token="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" and password: mysecretpassword123'
    redacted = redact_secrets(raw_log)
    assert "mysecretpassword123" not in redacted
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in redacted
    assert "[REDACTED]" in redacted
