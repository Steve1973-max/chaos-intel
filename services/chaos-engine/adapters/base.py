"""Model-Independent Fault-Injection Adapter Interface for CHAOS-INTEL Phase 3C.

Extends `ExecutionAdapter` from `services/application-intelligence` and provides
declarative specification translators for future fault-injection engines:
- Pumba
- Linux `tc/netem`
- Chaos Mesh
- LitmusChaos

Live fault execution is strictly disabled in Phase 3C (`supports_live_execution = False`).
"""

from __future__ import annotations

import sys
from abc import abstractmethod
from pathlib import Path
from typing import Any, Dict, List
from pydantic import BaseModel, Field

_APP_INTEL_ROOT = Path(__file__).resolve().parents[2] / "application-intelligence"
if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

from src.execution.adapters.base import ExecutionAdapter
from src.execution.adapters.capabilities import AdapterCapabilities
from src.execution.adapters.context import ExecutionContext
from src.execution.adapters.result import ExecutionResult
from src.execution.recovery import RecoveryResult
from src.models.experiment import ExperimentSpecification


class UncertainFaultOperationError(RuntimeError):
    """Raised when an external fault injection or rollback operation has an uncertain outcome.

    Operations raising this error must NEVER be automatically replayed.
    """


class DeclarativeFaultManifest(BaseModel):
    """Declarative representation of a fault for future backend engines (non-executable in Phase 3C)."""

    engine_family: str = Field(min_length=1)  # pumba, tc_netem, chaos_mesh, litmus_chaos, dry_run
    experiment_id: str = Field(min_length=1)
    fault_type: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    duration_seconds: int = Field(ge=1)
    live_execution_enabled: bool = False
    manifest_payload: Dict[str, Any] = Field(default_factory=dict)
    rollback_payload: Dict[str, Any] = Field(default_factory=dict)


class DeclarativeSpecTranslator:
    """Translates model-independent `ExperimentSpecification` into declarative specs for future engines."""

    @staticmethod
    def to_pumba_spec(spec: ExperimentSpecification) -> DeclarativeFaultManifest:
        return DeclarativeFaultManifest(
            engine_family="pumba",
            experiment_id=spec.experiment_id,
            fault_type=spec.fault.type,
            target_id=spec.target.id,
            duration_seconds=spec.duration_seconds,
            live_execution_enabled=False,
            manifest_payload={
                "tool": "pumba",
                "mode": "dry_run_only",
                "target_container": spec.target.id,
                "fault_method": spec.fault.method,
                "duration": f"{spec.duration_seconds}s",
                "parameters": dict(spec.fault.parameters),
            },
            rollback_payload={
                "strategy": spec.rollback.strategy,
                "action": "stop_pumba_container_and_restore_target",
            },
        )

    @staticmethod
    def to_tc_netem_spec(spec: ExperimentSpecification) -> DeclarativeFaultManifest:
        return DeclarativeFaultManifest(
            engine_family="tc_netem",
            experiment_id=spec.experiment_id,
            fault_type=spec.fault.type,
            target_id=spec.target.id,
            duration_seconds=spec.duration_seconds,
            live_execution_enabled=False,
            manifest_payload={
                "subsystem": "linux_tc_netem",
                "mode": "dry_run_only",
                "interface": "eth0",
                "qdisc_action": "add",
                "netem_parameters": dict(spec.fault.parameters),
                "duration_seconds": spec.duration_seconds,
            },
            rollback_payload={
                "subsystem": "linux_tc_netem",
                "qdisc_action": "del",
                "interface": "eth0",
                "strategy": spec.rollback.strategy,
            },
        )

    @staticmethod
    def to_chaos_mesh_crd(spec: ExperimentSpecification) -> DeclarativeFaultManifest:
        return DeclarativeFaultManifest(
            engine_family="chaos_mesh",
            experiment_id=spec.experiment_id,
            fault_type=spec.fault.type,
            target_id=spec.target.id,
            duration_seconds=spec.duration_seconds,
            live_execution_enabled=False,
            manifest_payload={
                "apiVersion": "chaos-mesh.org/v1alpha1",
                "kind": "SimulatedChaosResource",
                "metadata": {
                    "name": spec.experiment_id,
                    "annotations": {"chaos-intel.io/mode": "dry-run-only"},
                },
                "spec": {
                    "action": spec.fault.method,
                    "mode": "one",
                    "selector": {"labelSelectors": {"app": spec.target.id}},
                    "duration": f"{spec.duration_seconds}s",
                    "parameters": dict(spec.fault.parameters),
                },
            },
            rollback_payload={
                "action": "delete_crd_resource",
                "name": spec.experiment_id,
                "strategy": spec.rollback.strategy,
            },
        )

    @staticmethod
    def to_litmus_chaos_engine(spec: ExperimentSpecification) -> DeclarativeFaultManifest:
        return DeclarativeFaultManifest(
            engine_family="litmus_chaos",
            experiment_id=spec.experiment_id,
            fault_type=spec.fault.type,
            target_id=spec.target.id,
            duration_seconds=spec.duration_seconds,
            live_execution_enabled=False,
            manifest_payload={
                "apiVersion": "litmuschaos.io/v1alpha1",
                "kind": "ChaosEngine",
                "metadata": {
                    "name": spec.experiment_id,
                    "annotations": {"chaos-intel.io/mode": "dry-run-only"},
                },
                "spec": {
                    "engineState": "stop",
                    "appinfo": {"applabel": f"app={spec.target.id}"},
                    "experiments": [
                        {
                            "name": spec.fault.type,
                            "spec": {
                                "components": {
                                    "env": [
                                        {"name": "TOTAL_CHAOS_DURATION", "value": str(spec.duration_seconds)},
                                        *[
                                            {"name": str(k).upper(), "value": str(v)}
                                            for k, v in (spec.fault.parameters or {}).items()
                                        ],
                                    ]
                                }
                            },
                        }
                    ],
                },
            },
            rollback_payload={
                "engineState": "stop",
                "strategy": spec.rollback.strategy,
            },
        )


class ChaosFaultAdapter(ExecutionAdapter):
    """Model-independent base class for chaos fault-injection adapters."""

    supports_live_execution: bool = False

    @classmethod
    def supported_all_fault_types(cls) -> List[str]:
        return [
            # Phase 3C canonical fault types
            "cpu_stress",
            "memory_pressure",
            "disk_io_pressure",
            "network_latency",
            "packet_loss",
            "network_disconnection",
            "service_unavailability",
            "process_termination_simulation",
            "dependency_unavailability",
            "api_latency",
            "http_error_injection",
            "connection_failures",
            # Phase 2 policy aliases
            "availability",
            "latency",
            "network_partition",
            "connection_exhaustion",
            "resource_cpu",
            "resource_memory",
            "dependency_unavailable",
            "dependency_slow",
            "queue_backlog",
        ]

    @abstractmethod
    def build_declarative_manifests(
        self, spec: ExperimentSpecification
    ) -> Dict[str, DeclarativeFaultManifest]:
        """Generate declarative manifests for future fault engines without executing them."""
        raise NotImplementedError

