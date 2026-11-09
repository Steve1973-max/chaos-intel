"""Fault Injector for CHAOS-INTEL Phase 3C.

Coordinates execution preparation, fault injection, and continuous observation
strictly through the `LifecycleController` state machine and `ExecutionAdapter`.

Enforces:
- Hard prohibition of live execution (Phase 3C safety invariant).
- Cooperative cancellation / emergency abort via `ExperimentCancellationToken`.
- Continuous telemetry observation with safety-threshold abort triggers.
- Zero automatic replay of uncertain fault operations (`UncertainFaultOperationError`).
- Comprehensive audit logging for all lifecycle actions.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

_APP_INTEL_ROOT = Path(__file__).resolve().parents[1] / "application-intelligence"
if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

from src.execution.adapters.base import ExecutionAdapter
from src.execution.lifecycle import LifecycleController
from src.execution.reliability.audit import AuditEvent, AuditLogger
from src.execution.states import LifecycleState

from adapters.base import UncertainFaultOperationError
from adapters.dry_run import ChaosDryRunAdapter, MockFaultAdapter
from adapters.lifecycle_proxy import LifecycleAdapterProxy
from engine_models import (
    LIVE_EXECUTION_ENABLED,
    ExperimentCancellationToken,
    LiveExecutionDisabledError,
)
from experiment_observer import ExperimentObserver


class FaultInjectionOutcome(BaseModel):
    """Structured outcome of the fault injection and observation phase."""

    run_id: str
    experiment_id: str
    success: bool
    aborted: bool = False
    cancelled: bool = False
    outcome_uncertain: bool = False
    abort_reason: Optional[str] = None
    abort_source: Optional[str] = None
    triggered_abort_conditions: List[Dict[str, Any]] = Field(default_factory=list)
    injection_attempts: int = 0
    error: Optional[str] = None


class FaultInjector:
    """Coordinates setup, fault injection, and observation window."""

    def __init__(
        self,
        observer: Optional[ExperimentObserver] = None,
        audit_logger: Optional[AuditLogger] = None,
    ) -> None:
        self.observer = observer or ExperimentObserver()
        self.audit_logger = audit_logger or AuditLogger()

    def _audit(
        self,
        controller: LifecycleController,
        event_type: str,
        previous_state: str,
        outcome: str,
        reason: str,
        correlation_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.audit_logger.log(
            AuditEvent(
                run_id=controller.run.run_id,
                application_id=controller.app.application_id,
                experiment_id=controller.spec.experiment_id,
                event_type=event_type,
                previous_state=previous_state,
                current_state=str(getattr(controller.run.state, "value", controller.run.state)),
                outcome=outcome,
                reason=reason,
                correlation_id=correlation_id,
                metadata=metadata or {},
            )
        )

    @staticmethod
    def _state(run: Any) -> str:
        return str(getattr(run.state, "value", run.state))

    def execute_injection_and_observation(
        self,
        controller: LifecycleController,
        adapter: ExecutionAdapter,
        cancellation_token: Optional[ExperimentCancellationToken] = None,
        observation_metrics: Optional[List[Dict[str, float]]] = None,
        max_windows: int = 1,
        correlation_id: Optional[str] = None,
    ) -> FaultInjectionOutcome:
        """Execute setup, injection, and observation through `LifecycleController`."""
        proxy = adapter if isinstance(adapter, LifecycleAdapterProxy) else LifecycleAdapterProxy(adapter)
        run = controller.run
        spec = controller.spec
        corr_id = correlation_id or run.run_id

        # Hard invariant: live execution is strictly disabled in Phase 3C
        if proxy.supports_live_execution or not isinstance(proxy.inner, (ChaosDryRunAdapter, MockFaultAdapter)):
            if not LIVE_EXECUTION_ENABLED:
                raise LiveExecutionDisabledError("Live fault injection is strictly disabled in Phase 3C.")

        # ---- Step 1: Pre-execution cancellation check
        if cancellation_token and cancellation_token.is_cancelled:
            proxy.abort_was_requested = True
            prev = self._state(run)
            if run.state == LifecycleState.AUTHORIZED:
                try:
                    controller.setup(adapter=proxy)
                except BaseException:
                    pass
            controller.fail(
                error_type="CancellationError",
                message=cancellation_token.reason or "Experiment cancelled prior to setup.",
            )
            self._audit(
                controller,
                "execution_cancelled_preflight",
                prev,
                "cancelled",
                cancellation_token.reason or "Experiment cancelled before execution.",
                corr_id,
                {"emergency": cancellation_token.is_emergency},
            )
            return FaultInjectionOutcome(
                run_id=run.run_id,
                experiment_id=spec.experiment_id,
                success=False,
                aborted=False,
                cancelled=True,
                abort_reason=cancellation_token.reason,
                abort_source="cancellation",
            )

        # ---- Step 2: Setup (AUTHORIZED -> SETUP)
        prev = self._state(run)
        try:
            controller.setup(adapter=proxy)
            self._audit(
                controller,
                "setup_completed",
                prev,
                "success",
                f"Execution adapter '{proxy.capabilities().adapter_id}' prepared.",
                corr_id,
                {"adapter_id": proxy.capabilities().adapter_id},
            )
        except BaseException as exc:
            self._audit(
                controller,
                "setup_failed",
                prev,
                "failed",
                str(exc),
                corr_id,
                {"error_type": type(exc).__name__},
            )
            controller.fail(error_type=type(exc).__name__, message=str(exc))
            return FaultInjectionOutcome(
                run_id=run.run_id,
                experiment_id=spec.experiment_id,
                success=False,
                error=f"Setup failed: {exc}",
            )

        # Check cancellation right after setup
        if cancellation_token and cancellation_token.is_cancelled:
            prev = self._state(run)
            controller.fail(
                error_type="CancellationError",
                message=cancellation_token.reason or "Experiment cancelled during setup.",
            )
            self._audit(
                controller,
                "execution_cancelled_setup",
                prev,
                "cancelled",
                cancellation_token.reason or "Cancelled after setup.",
                corr_id,
                {"emergency": cancellation_token.is_emergency},
            )
            return FaultInjectionOutcome(
                run_id=run.run_id,
                experiment_id=spec.experiment_id,
                success=False,
                aborted=False,
                cancelled=True,
                abort_reason=cancellation_token.reason,
                abort_source="cancellation",
            )

        # ---- Step 3: Fault Injection (SETUP -> RUNNING)
        prev = self._state(run)
        self.observer.mark_fault_start(run.run_id)
        try:
            controller.run_experiment(adapter=proxy)
            attempts = proxy.invocations.get("execute", 1)
            self._audit(
                controller,
                "fault_injected",
                prev,
                "success",
                f"Fault '{spec.fault.type}' injected against target '{spec.target.id}'.",
                corr_id,
                {
                    "fault_type": spec.fault.type,
                    "target_id": spec.target.id,
                    "injection_attempts": attempts,
                },
            )
        except UncertainFaultOperationError as exc:
            self.observer.mark_fault_end(run.run_id)
            proxy.abort_was_requested = True
            attempts = proxy.invocations.get("execute", 1)
            # ZERO automatic replay: uncertain operation outcome must not be re-executed
            self._audit(
                controller,
                "fault_injection_uncertain",
                prev,
                "uncertain_no_replay",
                str(exc),
                corr_id,
                {
                    "automatic_replay": False,
                    "outcome_uncertain": True,
                    "injection_attempts": attempts,
                    "error_type": type(exc).__name__,
                },
            )
            controller.request_abort(
                reason=f"Uncertain fault operation outcome: {exc}", source="uncertain_injection"
            )
            return FaultInjectionOutcome(
                run_id=run.run_id,
                experiment_id=spec.experiment_id,
                success=False,
                aborted=True,
                outcome_uncertain=True,
                abort_reason=str(exc),
                abort_source="uncertain_injection",
                injection_attempts=attempts,
                error=str(exc),
            )
        except BaseException as exc:
            self.observer.mark_fault_end(run.run_id)
            proxy.abort_was_requested = True
            attempts = proxy.invocations.get("execute", 1)
            self._audit(
                controller,
                "fault_injection_failed",
                prev,
                "failed",
                str(exc),
                corr_id,
                {"injection_attempts": attempts, "error_type": type(exc).__name__},
            )
            controller.request_abort(reason=f"Fault injection error: {exc}", source="injection_error")
            return FaultInjectionOutcome(
                run_id=run.run_id,
                experiment_id=spec.experiment_id,
                success=False,
                aborted=True,
                abort_reason=str(exc),
                abort_source="injection_error",
                injection_attempts=attempts,
                error=str(exc),
            )

        # ---- Step 4: Observation (RUNNING -> OBSERVING)
        prev = self._state(run)
        try:
            controller.observe(adapter=proxy)
            self._audit(
                controller,
                "observation_started",
                prev,
                "success",
                "Continuous observation window active.",
                corr_id,
            )
        except BaseException as exc:
            self.observer.mark_fault_end(run.run_id)
            self._audit(
                controller,
                "observation_transition_failed",
                prev,
                "failed",
                str(exc),
                corr_id,
                {"error_type": type(exc).__name__},
            )
            controller.fail(error_type=type(exc).__name__, message=str(exc))
            return FaultInjectionOutcome(
                run_id=run.run_id,
                experiment_id=spec.experiment_id,
                success=False,
                error=f"Observation transition failed: {exc}",
            )

        # ---- Step 5: Continuous Observation Loop & Threshold Checking
        windows: List[Optional[Dict[str, float]]]
        if observation_metrics is not None and len(observation_metrics) > 0:
            windows = list(observation_metrics)
        else:
            windows = [None] * max(1, max_windows)

        for win_idx, win_metrics in enumerate(windows):
            # Check cooperative cancellation / operator emergency abort
            if cancellation_token and cancellation_token.is_cancelled:
                self.observer.mark_fault_end(run.run_id)
                proxy.abort_was_requested = True
                prev = self._state(run)
                reason = cancellation_token.reason or "Experiment cancelled during observation."
                controller.request_abort(reason=reason, source="cancellation")
                self._audit(
                    controller,
                    "abort_requested_cancellation",
                    prev,
                    "cancelled",
                    reason,
                    corr_id,
                    {"window_index": win_idx, "emergency": cancellation_token.is_emergency},
                )
                return FaultInjectionOutcome(
                    run_id=run.run_id,
                    experiment_id=spec.experiment_id,
                    success=False,
                    aborted=True,
                    cancelled=True,
                    abort_reason=reason,
                    abort_source="cancellation",
                    injection_attempts=proxy.invocations.get("execute", 1),
                )

            # Evaluate steady-state and abort conditions
            triggered = self.observer.observe_window(
                run=run, spec=spec, observed_metrics=win_metrics
            )
            if triggered:
                self.observer.mark_fault_end(run.run_id)
                proxy.abort_was_requested = True
                prev = self._state(run)
                reason = f"Safety threshold breached: {', '.join(t.metric for t in triggered)}"
                controller.request_abort(reason=reason, source="safety_threshold")
                self._audit(
                    controller,
                    "abort_requested_threshold_breach",
                    prev,
                    "aborted",
                    reason,
                    corr_id,
                    {
                        "window_index": win_idx,
                        "triggered_conditions": [t.model_dump() for t in triggered],
                    },
                )
                return FaultInjectionOutcome(
                    run_id=run.run_id,
                    experiment_id=spec.experiment_id,
                    success=False,
                    aborted=True,
                    abort_reason=reason,
                    abort_source="safety_threshold",
                    triggered_abort_conditions=[t.model_dump() for t in triggered],
                    injection_attempts=proxy.invocations.get("execute", 1),
                )

        # Observation completed without safety abort
        self.observer.mark_fault_end(run.run_id)
        prev = self._state(run)
        controller.finish_observation()
        self._audit(
            controller,
            "observation_finished",
            prev,
            "success",
            "Observation window completed within safe thresholds.",
            corr_id,
            {"observation_windows_completed": len(windows)},
        )
        return FaultInjectionOutcome(
            run_id=run.run_id,
            experiment_id=spec.experiment_id,
            success=True,
            aborted=False,
            injection_attempts=proxy.invocations.get("execute", 1),
        )
