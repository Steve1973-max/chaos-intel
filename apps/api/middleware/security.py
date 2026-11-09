"""Security middleware: Security headers and in-memory rate limiting."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Dict, List
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette import status

from apps.api.config import config


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Enforces enterprise security headers on all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        return response


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Sliding-window in-memory rate limiter per client IP."""

    def __init__(self, app: Any, requests_per_minute: int = 180) -> None:
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self._history: Dict[str, List[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Exclude health check from rate limiting
        if request.url.path.endswith("/health") or request.url.path.endswith("/health/services"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        window_start = now - 60.0

        # Purge timestamps older than 60 seconds
        timestamps = [t for t in self._history[client_ip] if t > window_start]
        if len(timestamps) >= self.requests_per_minute:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "message": f"Rate limit of {self.requests_per_minute} requests per minute exceeded.",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
                headers={"Retry-After": "60"},
            )

        timestamps.append(now)
        self._history[client_ip] = timestamps

        return await call_next(request)

