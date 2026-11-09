"""Typed client for Chaos Engine service."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from .base import BaseServiceClient, ServiceClientError
from .loader import get_chaos_engine_classes

FaultCatalog, ExperimentValidator, ChaosDryRunAdapter, ChaosExperimentReport, Target = get_chaos_engine_classes()


class ChaosEngineClient(BaseServiceClient):
    """Client for creating, validating, approving, and executing controlled chaos experiments."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: float = 60.0,
        direct_adapter: Optional[Any] = None,
    ) -> None:
        super().__init__(
            service_name="chaos-engine",
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            direct_adapter=direct_adapter or FaultCatalog,
        )
        self._catalog = FaultCatalog() if FaultCatalog else None
        self._validator = ExperimentValidator() if ExperimentValidator else None
        self._experiments: Dict[str, Any] = {}
        self._approvals: Dict[str, Dict[str, Any]] = {}
        self._reports: Dict[str, Any] = {}

    async def create_experiment(
        self,
        spec_dict: Dict[str, Any],
        correlation_id: str,
    ) -> Any:
        """Register and validate a new chaos experiment specification."""
        if self._catalog is not None and Target is not None:
            try:
                target_id = spec_dict.get("target_service_id") or spec_dict.get("target_id") or "svc-default"
                fault_type = spec_dict.get("fault_type", "network_latency")
                target = Target(id=target_id, name=target_id, type="service")

                spec = self._catalog.create_experiment_specification(
                    application_id=spec_dict.get("application_id", "app-01"),
                    target=target,
                    fault_type=fault_type,
                    parameters=spec_dict.get("parameters", {}),
                    duration_seconds=spec_dict.get("duration_seconds", 30),
                    environment=spec_dict.get("environment", "staging"),
                    experiment_id=spec_dict.get("experiment_id"),
                    name=spec_dict.get("name"),
                )
                self._experiments[spec.experiment_id] = spec
                return spec
            except Exception as exc:
                raise ServiceClientError(
                    f"Chaos experiment creation failed: {exc}",
                    self.service_name,
                    correlation_id=correlation_id,
                ) from exc

        # HTTP transport
        return await self._request("POST", "/api/v1/experiments", correlation_id=correlation_id, json_payload=spec_dict)

    async def submit_approval(
        self,
        experiment_id: str,
        approved_by: str,
        grant_id: str,
        correlation_id: str,
    ) -> Dict[str, Any]:
        """Record human safety approval grant for experiment."""
        if not approved_by or not grant_id:
            raise ServiceClientError("Both approved_by and grant_id are required", self.service_name, correlation_id=correlation_id)

        approval_record = {
            "experiment_id": experiment_id,
            "status": "APPROVED",
            "approved_by": approved_by,
            "grant_id": grant_id,
            "correlation_id": correlation_id,
        }
        self._approvals[experiment_id] = approval_record
        return approval_record

    async def execute_experiment(
        self,
        experiment_id: str,
        app: Any,
        correlation_id: str,
        dry_run: bool = True,
    ) -> Any:
        """Execute controlled experiment. Live execution is strictly prohibited; dry_run must be True."""
        if not dry_run:
            raise ServiceClientError("Live execution is prohibited in this phase", self.service_name, correlation_id=correlation_id)

        if ChaosDryRunAdapter is not None and ChaosExperimentReport is not None:
            spec = self._experiments.get(experiment_id)
            adapter = ChaosDryRunAdapter()
            manifests = adapter.build_declarative_manifests(spec) if spec else {}
            f_type = getattr(getattr(spec, "fault", None), "type", "network_latency") if hasattr(spec, "fault") else str(getattr(spec, "fault", "network_latency"))
            target_str = getattr(getattr(spec, "target", None), "id", "svc-default") if hasattr(spec, "target") else str(getattr(spec, "target", "svc-default"))

            report = ChaosExperimentReport(
                report_id=f"rpt-{uuid.uuid4().hex[:8]}",
                run_id=f"run-{experiment_id[:8]}",
                experiment_id=experiment_id,
                application_id=getattr(app, "application_id", "app-01"),
                correlation_id=correlation_id,
                mode="dry_run",
                live_execution=False,
                adapter_id="chaos-dry-run-adapter",
                verdict="unresolved",
                final_lifecycle_state="COMPLETED",
                recovery_classification="unknown",
                fault_type=f_type,
                target_id=target_str,
                duration_seconds=getattr(spec, "duration_seconds", 30) or 30,
                safety_decision_id=getattr(spec, "safety_decision_id", "sec-01") or "sec-01",
                safety_decision="approved",
                declarative_manifests={k: m.model_dump() for k, m in manifests.items()} if manifests else {},
            )
            self._reports[report.run_id] = report
            return report

        # HTTP transport
        payload = {"experiment_id": experiment_id, "dry_run": True}
        return await self._request("POST", "/api/v1/executions", correlation_id=correlation_id, json_payload=payload)

    async def get_experiment_report(self, run_id: str, correlation_id: str) -> Optional[Any]:
        """Retrieve execution report by run ID."""
        if run_id in self._reports:
            return self._reports[run_id]
        if self.base_url:
            return await self._request("GET", f"/api/v1/executions/{run_id}", correlation_id=correlation_id)
        return None
