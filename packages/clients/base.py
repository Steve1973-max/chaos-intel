"""Base client for internal service communication in CHAOS-INTEL Phase 5."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional
import httpx

logger = logging.getLogger(__name__)


class ServiceClientError(Exception):
    """Base exception for all service client errors."""

    def __init__(
        self,
        message: str,
        service_name: str,
        status_code: Optional[int] = None,
        correlation_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.service_name = service_name
        self.status_code = status_code
        self.correlation_id = correlation_id
        self.details = details or {}


class ServiceConnectionError(ServiceClientError):
    """Raised when unable to connect to the target service."""
    pass


class ServiceTimeoutError(ServiceClientError):
    """Raised when a request to the target service times out."""
    pass


class ServiceResponseError(ServiceClientError):
    """Raised when the service returns an error HTTP status (4xx, 5xx)."""
    pass


def _is_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.ConnectError, ConnectionRefusedError, ConnectionResetError, NotImplementedError)):
        return True
    if hasattr(exc, "exceptions"):
        return any(_is_connection_error(e) for e in getattr(exc, "exceptions", []))
    err_str = (str(exc) + " " + repr(exc)).lower()
    return "connect" in err_str or "notimplemented" in err_str or "taskgroup" in err_str


def _is_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, TimeoutError, asyncio.TimeoutError)):
        return True
    if hasattr(exc, "exceptions"):
        return any(_is_timeout_error(e) for e in exc.exceptions)
    err_str = (str(exc) + " " + repr(exc)).lower()
    return "timeout" in err_str


class BaseServiceClient:
    """Base client supporting both HTTP transport and in-process direct delegation."""

    def __init__(
        self,
        service_name: str,
        base_url: Optional[str] = None,
        timeout_seconds: float = 30.0,
        direct_adapter: Optional[Any] = None,
    ) -> None:
        self.service_name = service_name
        self.base_url = (base_url or "").rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.direct_adapter = direct_adapter

    async def _request(
        self,
        method: str,
        path: str,
        correlation_id: str,
        json_payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute HTTP request with correlation propagation and structured error mapping."""
        url = f"{self.base_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Correlation-ID": correlation_id,
        }
        req_timeout = timeout or self.timeout_seconds

        try:
            async with httpx.AsyncClient(timeout=req_timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_payload,
                    params=params,
                )
                if response.status_code >= 400:
                    try:
                        err_data = response.json()
                    except Exception:
                        err_data = {"raw_text": response.text}
                    raise ServiceResponseError(
                        message=f"{self.service_name} returned error {response.status_code}: {response.text[:200]}",
                        service_name=self.service_name,
                        status_code=response.status_code,
                        correlation_id=correlation_id,
                        details=err_data if isinstance(err_data, dict) else {"details": err_data},
                    )
                return response.json()
        except httpx.TimeoutException as exc:
            raise ServiceTimeoutError(
                message=f"Request to {self.service_name} timed out after {req_timeout}s: {exc}",
                service_name=self.service_name,
                correlation_id=correlation_id,
            ) from exc
        except httpx.ConnectError as exc:
            raise ServiceConnectionError(
                message=f"Failed to connect to {self.service_name} at {url}: {exc}",
                service_name=self.service_name,
                correlation_id=correlation_id,
            ) from exc
        except ServiceClientError:
            raise
        except Exception as exc:
            if _is_connection_error(exc):
                raise ServiceConnectionError(
                    message=f"Failed to connect to {self.service_name} at {url}: {exc}",
                    service_name=self.service_name,
                    correlation_id=correlation_id,
                ) from exc
            if _is_timeout_error(exc):
                raise ServiceTimeoutError(
                    message=f"Request to {self.service_name} timed out after {req_timeout}s: {exc}",
                    service_name=self.service_name,
                    correlation_id=correlation_id,
                ) from exc
            raise ServiceClientError(
                message=f"Unexpected error communicating with {self.service_name}: {exc}",
                service_name=self.service_name,
                correlation_id=correlation_id,
            ) from exc

    async def check_health(self) -> Dict[str, Any]:
        """Check target service health."""
        if self.base_url:
            try:
                res = await self._request("GET", "/health", correlation_id="health-check", timeout=2.0)
                return {
                    "service": self.service_name,
                    "status": res.get("status", "HEALTHY"),
                    "mode": "http",
                    "details": res,
                }
            except Exception as exc:
                return {
                    "service": self.service_name,
                    "status": "UNHEALTHY",
                    "mode": "http",
                    "error": str(exc),
                }
        return {
            "service": self.service_name,
            "status": "HEALTHY",
            "mode": "in_process",
        }
