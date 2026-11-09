"""Correlation ID Middleware for distributed tracing and request tracking."""

from __future__ import annotations

import contextvars
import uuid
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_CORRELATION_ID_CTX: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="corr-unknown"
)


def get_current_correlation_id() -> str:
    """Return the correlation ID active for the current request context."""
    return _CORRELATION_ID_CTX.get()


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Ensures every incoming request carries a correlation ID across the request lifecycle."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        corr_id = request.headers.get("X-Correlation-ID") or request.headers.get("x-correlation-id")
        if not corr_id:
            corr_id = f"corr-{uuid.uuid4().hex[:12]}"

        token = _CORRELATION_ID_CTX.set(corr_id)
        request.state.correlation_id = corr_id

        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = corr_id
            return response
        finally:
            _CORRELATION_ID_CTX.reset(token)

