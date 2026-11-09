"""DryRunAdapter and MockFaultAdapter for CHAOS-INTEL Phase 3C.

Provides:
- `ChaosDryRunAdapter` (`DryRunAdapter`): Default no-side-effect adapter that
  produces declarative Pumba / tc-netem / Chaos Mesh / LitmusChaos manifests
  and preserves the `RecoveryResultVariant.INCONCLUSIVE` reconciliation invariant.
- `MockFaultAdapter`: Configurable in-memory fault adapter for isolated lifecycle,
  abort, rollback, recovery, and uncertain-outcome testing without real fault execution.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_APP_INTEL_ROOT = Path(__file__).resolve().parents[2] / "application-intelligence"
if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

from src.execution.adapters.capabilities import AdapterCapabilities
from src.execution.adapters.context import ExecutionContext
from src.execution.adapters.result import ExecutionResult
from src.execution.recovery import RecoveryResult, RecoveryResultVariant
from src.models.experiment import ExperimentSpecification

from adapters.base import (
    ChaosFaultAdapter,
    DeclarativeFaultManifest,
    DeclarativeSpecTranslator,
)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChaosDryRunAdapter(ChaosFaultAdapter):
    """Default dry-run chaos adapter with zero infrastructure side effects."""

    supports_live_execution: bool = False

    @classmethod
    def capabilities(cls) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id="chaos-dry-run-adapter",
            adapter_name="Chaos Dry Run Adapter",
            supported_fault_types=cls.supported_all_fault_types(),
            supported_target_types=[
                "service",
                "api",
                "dependency",
                "external_dependency",
                "infrastructure",
                "database",
                "queue",
            ],
            required_capabilities=[],
            version="1.0.0",
        )

    def build_declarative_manifests(
        self, spec: ExperimentSpecification
    ) -> Dict[str, DeclarativeFaultManifest]:
        return {
            "pumba": DeclarativeSpecTranslator.to_pumba_spec(spec),
            "tc_netem": DeclarativeSpecTranslator.to_tc_netem_spec(spec),
            "chaos_mesh": DeclarativeSpecTranslator.to_chaos_mesh_crd(spec),
            "litmus_chaos": DeclarativeSpecTranslator.to_litmus_chaos_engine(spec),
        }

    def _make_result(
        self, context: ExecutionContext, status: str, extra_meta: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        manifests = {
            k: v.model_dump(mode="json")
            for k, v in self.build_declarative_manifests(context.experiment).items()
        }
        now = utcnow_iso()
        return ExecutionResult(
            result_id=str(uuid.uuid4()),
            run_id=context.run.run_id,
            plan_id=f"dry-run-plan-{context.experiment.experiment_id}",
            adapter_id=self.capabilities().adapter_id,
            status=status,
            mode="dry_run",
            started_at=now,
            completed_at=now,
            steps=[
                {
                    "phase": status,
                    "simulated": True,
                    "target_id": context.experiment.target.id,
                    "fault_type": context.experiment.fault.type,
                    "timestamp": now,
                }
            ],
            metadata={
                "simulated": True,
                "live_execution": False,
                "declarative_manifests": manifests,
                **(extra_meta or {}),
            },
        )

    def prepare(self, context: ExecutionContext) -> ExecutionResult:
        return self._make_result(context, "prepared")

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        return self._make_result(context, "executed")

    def observe(self, context: ExecutionContext) -> ExecutionResult:
        return self._make_result(
            context,
            "observed",
            extra_meta={
                "telemetry": {
                    "cpu_percent": 24.0,
                    "memory_percent": 46.0,
                    "latency_p95_ms": 50.0,
                    "error_rate": 0.002,
                    "availability_ratio": 0.999,
                }
            },
        )

    def abort(self, context: ExecutionContext) -> ExecutionResult:
        return self._make_result(context, "aborted")

    def rollback(self, context: ExecutionContext) -> ExecutionResult:
        return self._make_result(context, "rolled_back")

    def verify_recovery(self, context: ExecutionContext) -> RecoveryResult:
        # DryRunAdapter cannot reconcile remote infrastructure state; always returns INCONCLUSIVE
        return RecoveryResult(
            variant=RecoveryResultVariant.INCONCLUSIVE,
            run_id=context.run.run_id,
            message="Dry run adapter cannot perform read-only remote reconciliation.",
        )

    def cleanup(self, context: ExecutionContext) -> ExecutionResult:
        return self._make_result(context, "completed")


# Standard alias matching prompt module requirement
DryRunAdapter = ChaosDryRunAdapter


class MockFaultAdapter(ChaosFaultAdapter):
    """Configurable in-memory fault adapter for isolated lifecycle and failure-mode tests."""

    supports_live_execution: bool = False

    def __init__(
        self,
        *,
        simulated_observation_metrics: Optional[Dict[str, float]] = None,
        simulated_post_recovery_metrics: Optional[Dict[str, float]] = None,
        fail_on_prepare: Optional[Exception] = None,
        fail_on_execute: Optional[Exception] = None,
        fail_on_rollback: Optional[Exception] = None,
        fail_on_verify_recovery: Optional[Exception] = None,
        recovery_variant: RecoveryResultVariant = RecoveryResultVariant.CONFIRMED_SUCCESS,
        recovery_message: str = "Mock target recovery verified against steady-state probes.",
    ) -> None:
        self.simulated_observation_metrics: Dict[str, float] = dict(
            simulated_observation_metrics
            or {
                "cpu_percent": 68.0,
                "memory_percent": 62.0,
                "latency_p95_ms": 145.0,
                "error_rate": 0.015,
                "availability_ratio": 0.992,
            }
        )
        self.simulated_post_recovery_metrics: Dict[str, float] = dict(
            simulated_post_recovery_metrics
            or {
                "cpu_percent": 22.0,
                "memory_percent": 45.0,
                "latency_p95_ms": 48.0,
                "error_rate": 0.002,
                "availability_ratio": 0.999,
            }
        )
        self.fail_on_prepare = fail_on_prepare
        self.fail_on_execute = fail_on_execute
        self.fail_on_rollback = fail_on_rollback
        self.fail_on_verify_recovery = fail_on_verify_recovery
        self.recovery_variant = recovery_variant
        self.recovery_message = recovery_message

        # Call counters to prove zero automatic replay on uncertain operations
        self.prepare_calls: int = 0
        self.execute_calls: int = 0
        self.observe_calls: int = 0
        self.abort_calls: int = 0
        self.rollback_calls: int = 0
        self.verify_recovery_calls: int = 0
        self.cleanup_calls: int = 0
        self.call_history: List[str] = []

    @classmethod
    def capabilities(cls) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id="mock-fault-adapter",
            adapter_name="Mock Fault Adapter (Isolated Test)",
            supported_fault_types=cls.supported_all_fault_types(),
            supported_target_types=[
                "service",
                "api",
                "dependency",
                "external_dependency",
                "infrastructure",
                "database",
                "queue",
            ],
            required_capabilities=[],
            version="1.0.0",
        )

    def build_declarative_manifests(
        self, spec: ExperimentSpecification
    ) -> Dict[str, DeclarativeFaultManifest]:
        return {
            "pumba": DeclarativeSpecTranslator.to_pumba_spec(spec),
            "tc_netem": DeclarativeSpecTranslator.to_tc_netem_spec(spec),
            "chaos_mesh": DeclarativeSpecTranslator.to_chaos_mesh_crd(spec),
            "litmus_chaos": DeclarativeSpecTranslator.to_litmus_chaos_engine(spec),
        }

    def _make_result(
        self, context: ExecutionContext, status: str, extra_meta: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        now = utcnow_iso()
        return ExecutionResult(
            result_id=str(uuid.uuid4()),
            run_id=context.run.run_id,
            plan_id=f"mock-plan-{context.experiment.experiment_id}",
            adapter_id=self.capabilities().adapter_id,
            status=status,
            mode="dry_run",
            started_at=now,
            completed_at=now,
            steps=[
                {
                    "phase": status,
                    "mock_isolated": True,
                    "target_id": context.experiment.target.id,
                    "fault_type": context.experiment.fault.type,
                    "timestamp": now,
                }
            ],
            metadata={"mock_isolated": True, "live_execution": False, **(extra_meta or {})},
        )

    def prepare(self, context: ExecutionContext) -> ExecutionResult:
        self.prepare_calls += 1
        self.call_history.append("prepare")
        if self.fail_on_prepare is not None:
            raise self.fail_on_prepare
        return self._make_result(context, "prepared")

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        self.execute_calls += 1
        self.call_history.append("execute")
        if self.fail_on_execute is not None:
            raise self.fail_on_execute
        return self._make_result(context, "executed")

    def observe(self, context: ExecutionContext) -> ExecutionResult:
        self.observe_calls += 1
        self.call_history.append("observe")
        return self._make_result(
            context,
            "observed",
            extra_meta={"telemetry": dict(self.simulated_observation_metrics)},
        )

    def abort(self, context: ExecutionContext) -> ExecutionResult:
        self.abort_calls += 1
        self.call_history.append("abort")
        return self._make_result(context, "aborted")

    def rollback(self, context: ExecutionContext) -> ExecutionResult:
        self.rollback_calls += 1
        self.call_history.append("rollback")
        if self.fail_on_rollback is not None:
            raise self.fail_on_rollback
        return self._make_result(context, "rolled_back")

    def verify_recovery(self, context: ExecutionContext) -> RecoveryResult:
        self.verify_recovery_calls += 1
        self.call_history.append("verify_recovery")
        if self.fail_on_verify_recovery is not None:
            raise self.fail_on_verify_recovery
        return RecoveryResult(
            variant=self.recovery_variant,
            run_id=context.run.run_id,
            message=self.recovery_message,
        )

    def cleanup(self, context: ExecutionContext) -> ExecutionResult:
        self.cleanup_calls += 1
        self.call_history.append("cleanup")
        return self._make_result(context, "completed")

