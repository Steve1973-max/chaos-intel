"""Typed client for Application Intelligence service."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

from .base import BaseServiceClient, ServiceClientError

_APP_INTEL_PATH = Path(__file__).resolve().parents[2] / "services" / "application-intelligence"
if str(_APP_INTEL_PATH) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_PATH))

try:
    from src.models.application import ApplicationModel
    from src.models.architecture import ArchitectureGraph
    from src.main import analyze_application as direct_analyze
except ImportError:
    ApplicationModel = Any  # type: ignore
    ArchitectureGraph = Any  # type: ignore
    direct_analyze = None  # type: ignore


class ApplicationIntelligenceClient(BaseServiceClient):
    """Client for interacting with Application Intelligence subsystem."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: float = 60.0,
        direct_adapter: Optional[Any] = None,
    ) -> None:
        super().__init__(
            service_name="application-intelligence",
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            direct_adapter=direct_adapter or direct_analyze,
        )
        self._cache: Dict[str, Any] = {}

    async def analyze_application(
        self,
        source_path: str,
        correlation_id: str,
    ) -> Any:
        """Run full static discovery, architecture extraction, and risk assessment."""
        if not source_path:
            raise ServiceClientError("source_path cannot be empty", self.service_name, correlation_id=correlation_id)

        # In-process direct execution
        if self.direct_adapter is not None:
            try:
                model = self.direct_adapter(source_path)
                self._cache[model.application_id] = model
                return model
            except Exception as exc:
                raise ServiceClientError(
                    f"Application analysis failed: {exc}",
                    self.service_name,
                    correlation_id=correlation_id,
                ) from exc

        # HTTP transport
        payload = {"source_path": source_path}
        res = await self._request("POST", "/api/v1/analyze", correlation_id=correlation_id, json_payload=payload)
        model = ApplicationModel.model_validate(res)
        self._cache[model.application_id] = model
        return model

    async def get_application(
        self,
        application_id: str,
        correlation_id: str,
    ) -> Optional[Any]:
        """Retrieve previously analyzed application model."""
        if application_id in self._cache:
            return self._cache[application_id]

        for m in self._cache.values():
            if getattr(m, "application_id", "") == application_id:
                return m

        try:
            from workers.db_persistence import is_postgres_enabled, pg_get_application
            if is_postgres_enabled():
                meta = pg_get_application(application_id)
                if meta:
                    analyzed_dump = meta.get("analyzed_model")
                    if analyzed_dump and hasattr(ApplicationModel, "model_validate"):
                        model = ApplicationModel.model_validate(analyzed_dump)
                        model.application_id = application_id
                        self._cache[application_id] = model
                        return model
                    src_loc = meta.get("source_location")
                    if src_loc and self.direct_adapter is not None:
                        model = self.direct_adapter(src_loc)
                        model.application_id = application_id
                        self._cache[application_id] = model
                        return model
        except Exception:
            pass

        if len(self._cache) == 1:
            return next(iter(self._cache.values()))

        if self.base_url:
            res = await self._request("GET", f"/api/v1/applications/{application_id}", correlation_id=correlation_id)
            model = ApplicationModel.model_validate(res)
            self._cache[application_id] = model
            return model
        return None

    async def get_architecture(
        self,
        application_id: str,
        correlation_id: str,
    ) -> Optional[Any]:
        """Retrieve architecture graph for application."""
        app = await self.get_application(application_id, correlation_id)
        if app and getattr(app, "architecture", None):
            return app.architecture
        return None

    async def get_risks(
        self,
        application_id: str,
        correlation_id: str,
    ) -> Optional[Any]:
        """Retrieve risk findings for application."""
        app = await self.get_application(application_id, correlation_id)
        if app and getattr(app, "risks", None) is not None:
            return app.risks
        return None

