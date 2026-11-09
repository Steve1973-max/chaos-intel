"""Structured request logging middleware with credential redaction."""

from __future__ import annotations

import logging
import time
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from workers.worker import redact_secrets

logger = logging.getLogger("chaos_intel.api")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs incoming requests and outgoing responses with latency and redaction."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start_time = time.perf_counter()
        corr_id = getattr(request.state, "correlation_id", "unknown")

        logger.info(
            redact_secrets(
                f"--> {request.method} {request.url.path} [corr={corr_id}]"
            )
        )

        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.info(
                f"<-- {request.method} {request.url.path} {response.status_code} ({duration_ms}ms) [corr={corr_id}]"
            )
            return response
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(
                redact_secrets(
                    f"<-- {request.method} {request.url.path} EXCEPTION: {exc} ({duration_ms}ms) [corr={corr_id}]"
                )
            )
            raise

