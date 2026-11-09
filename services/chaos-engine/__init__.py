"""CHAOS-INTEL Phase 3C: Controlled Chaos Experiment Engine.

Provides safe, controlled, declarative fault-injection experimentation with
strict safety guardrails, continuous observation, emergency aborts, and
zero-replay durable lifecycle integration.
"""

from __future__ import annotations

from adapters.base import ChaosFaultAdapter, DeclarativeSpecTranslator, UncertainFaultOperationError
from adapters.dry_run import ChaosDryRunAdapter, MockFaultAdapter
from adapters.lifecycle_proxy import LifecycleAdapterProxy
from blast_radius import BlastRadiusAnalyzer, BlastRadiusAssessment
from engine_models import (
    LIVE_EXECUTION_ENABLED,
    RESERVED_NON_HUMAN_APPROVERS,
    AbortRecord,
    AdapterNotPermittedError,
    ApprovalGrant,
    ChaosEngineError,
    ChaosEngineSettings,
    ChaosExperimentReport,
    ExperimentCancellationToken,
    LiveAuthorizationRequiredError,
    LiveExecutionAuthorization,
    LiveExecutionDisabledError,
    TargetNotAuthorizedError,
)
from experiment_observer import (
    ExperimentObservationRecord,
    ExperimentObserver,
    OpenTelemetryMetricPoint,
    OpenTelemetrySpanRecord,
    TelemetryDelta,
)
from experiment_registry import ExperimentRegistry
from experiment_scheduler import ExperimentScheduler
from experiment_validator import ExperimentValidator, ValidationReport
from fault_catalog import (
    DEFAULT_FAULT_CATALOG,
    FaultCatalog,
    FaultDefinition,
    FaultParameterSpec,
    FaultRecoveryStrategy,
    FaultTargetScope,
)
from fault_injector import FaultInjectionOutcome, FaultInjector
from rollback_manager import RollbackManager, RollbackOutcome
from steady_state import SteadyStateEvaluator, SteadyStateSnapshot, TriggeredAbortCondition

__all__ = [
    # Settings & Constants
    "LIVE_EXECUTION_ENABLED",
    "RESERVED_NON_HUMAN_APPROVERS",
    "ChaosEngineSettings",
    "LiveExecutionAuthorization",
    "ApprovalGrant",
    "ExperimentCancellationToken",
    "AbortRecord",
    "ChaosExperimentReport",
    # Errors
    "ChaosEngineError",
    "LiveExecutionDisabledError",
    "LiveAuthorizationRequiredError",
    "AdapterNotPermittedError",
    "TargetNotAuthorizedError",
    "UncertainFaultOperationError",
    # Fault Catalog
    "FaultCatalog",
    "FaultDefinition",
    "FaultParameterSpec",
    "FaultTargetScope",
    "FaultRecoveryStrategy",
    "DEFAULT_FAULT_CATALOG",
    # Blast Radius
    "BlastRadiusAnalyzer",
    "BlastRadiusAssessment",
    # Steady State
    "SteadyStateEvaluator",
    "SteadyStateSnapshot",
    "TriggeredAbortCondition",
    # Validator & Registry
    "ExperimentValidator",
    "ValidationReport",
    "ExperimentRegistry",
    # Adapters
    "ChaosFaultAdapter",
    "DeclarativeSpecTranslator",
    "ChaosDryRunAdapter",
    "MockFaultAdapter",
    "LifecycleAdapterProxy",
    # Observer
    "ExperimentObserver",
    "OpenTelemetryMetricPoint",
    "OpenTelemetrySpanRecord",
    "TelemetryDelta",
    "ExperimentObservationRecord",
    # Injector, Rollback & Scheduler
    "FaultInjector",
    "FaultInjectionOutcome",
    "RollbackManager",
    "RollbackOutcome",
    "ExperimentScheduler",
]

