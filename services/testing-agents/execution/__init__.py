"""Execution subsystem for CHAOS-INTEL Phase 3B."""

from .engine import TestExecutionEngine
from .execution_context import CancellationToken, IsolatedExecutionContext, StructuredLogEntry, utcnow_iso
from .execution_registry import ExecutionAdapterRegistry
from .result_collector import (
    EvidenceType,
    ExecutionErrorDetail,
    ExecutionEvidenceReference,
    ExecutionStatus,
    PlanExecutionReport,
    PlanExecutionSummary,
    ResultCollector,
    StepExecutionResult,
    StepStage,
    TestExecutionResult,
)
from .sandbox import (
    DestructiveActionBlockedError,
    ExecutionApproval,
    ExecutionCancelledError,
    ExecutionSafetyError,
    PrivateNetworkTargetBlockedError,
    SandboxPolicy,
    SecretRedactor,
    TargetOutOfScopeError,
    TargetSandbox,
    UnauthorizedPlanError,
)

__all__ = [
    "CancellationToken",
    "DestructiveActionBlockedError",
    "EvidenceType",
    "ExecutionAdapterRegistry",
    "ExecutionApproval",
    "ExecutionCancelledError",
    "ExecutionErrorDetail",
    "ExecutionEvidenceReference",
    "ExecutionSafetyError",
    "ExecutionStatus",
    "IsolatedExecutionContext",
    "PlanExecutionReport",
    "PlanExecutionSummary",
    "PrivateNetworkTargetBlockedError",
    "ResultCollector",
    "SandboxPolicy",
    "SecretRedactor",
    "StepExecutionResult",
    "StepStage",
    "StructuredLogEntry",
    "TargetOutOfScopeError",
    "TargetSandbox",
    "TestExecutionEngine",
    "TestExecutionResult",
    "UnauthorizedPlanError",
    "utcnow_iso",
]

