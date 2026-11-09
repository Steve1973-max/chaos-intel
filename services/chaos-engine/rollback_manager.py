"""Rollback & Recovery Verification Manager for CHAOS-INTEL Phase 3C.

Coordinates rollback and recovery verification strictly through the existing
`LifecycleController` state machine (`ROLLBACK`, `RECOVERY_CHECK`, `COMPLETED`,
`FAILED`, `ABORTED`, `ROLLBACK_FAILED`, `RECOVERY_FAILED`). This module never
writes `ExperimentRun.state` directly. It enforces:
- Zero automatic replay of uncertain external operations (rollback is attempted once)
- Treating uncertain or inconclusive recovery as unresolved, never successful
- Independent steady-state evidence gating of adapter-reported recovery success
- Recording every rollback and recovery decision in the audit trail
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

_APP_INTEL_ROOT = Path(__file__).resolve().parents[1] / "application-intelligence"
if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

from src.execution.adapters.base import ExecutionAdapter
from src.execution.lifecycle import LifecycleController
from src.execution.recovery import RecoveryClassifier
from src.execution.reliability.audit import AuditEvent, AuditLogger
from src.execution.states import LifecycleState

from adapters.base import UncertainFaultOperationError
from adapters.lifecycle_proxy import LifecycleAdapterProxy
from experiment_observer import ExperimentObserver


class RollbackOutcome(BaseModel):
    """Structured outcome of rollback and recovery verification."""

    run_id: str
    experiment_id: str
    rollback_status: str  # completed, failed, uncertain_no_replay
    recovery_status: str  # passed, failed, unresolved, not_attempted
    final_lifecycle_state: str
    recovery_classification: str
    outcome_uncertain: bool = False
    automatic_replay_attempted: bool = False
    rollback_attempts: int = 0
    recovery_gating_decision: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RollbackManager:
    """Executes rollback and recovery verification via `LifecycleController`."""

    def __init__(
        self,
        audit_logger: Optional[AuditLogger] = None,
        observer: Optional[ExperimentObserver] = None,
    ) -> None:
        self.audit_logger = audit_logger or AuditLogger()
        self.observer = observer or ExperimentObserver()

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

    def execute_rollback_and_verify_recovery(
        self,
        controller: LifecycleController,
        adapter: ExecutionAdapter,
        *,
        correlation_id: Optional[str] = None,
        post_recovery_metrics: Optional[Dict[str, float]] = None,
    ) -> RollbackOutcome:
        """Run rollback once, then verify recovery, using only `LifecycleController` transitions."""
        proxy = adapter if isinstance(adapter, LifecycleAdapterProxy) else LifecycleAdapterProxy(adapter)
        run = controller.run
        spec = controller.spec
        corr_id = correlation_id or run.run_id

        # ---- Step 1: Rollback (OBSERVING / ABORT_REQUESTED / ABORTED -> ROLLBACK -> RECOVERY_CHECK | ROLLBACK_FAILED)
        prev_state = self._state(run)
        try:
            self.observer.mark_recovery_start(run.run_id)
        except KeyError:
            pass

        rollback_attempts = 0
        if run.state != LifecycleState.RECOVERY_CHECK:
            controller.perform_rollback(adapter=proxy)
            rollback_attempts = proxy.invocations["rollback"]

            if run.state == LifecycleState.ROLLBACK_FAILED:
                exc = proxy.exceptions.get("rollback")
                is_uncertain = isinstance(exc, UncertainFaultOperationError)
                err_msg = run.rollback.error or (str(exc) if exc else "Rollback failed.")
                self._audit(
                    controller,
                    "rollback_failed",
                    prev_state,
                    "uncertain_no_replay" if is_uncertain else "failed",
                    err_msg,
                    corr_id,
                    {
                        "automatic_replay": False,
                        "outcome_uncertain": is_uncertain,
                        "rollback_attempts": rollback_attempts,
                        "error_type": type(exc).__name__ if exc else None,
                    },
                )
                return RollbackOutcome(
                    run_id=run.run_id,
                    experiment_id=spec.experiment_id,
                    rollback_status="uncertain_no_replay" if is_uncertain else "failed",
                    recovery_status="unresolved",
                    final_lifecycle_state=self._state(run),
                    recovery_classification=RecoveryClassifier.classify(run, has_authoritative_state=True).value,
                    outcome_uncertain=True,  # a failed rollback leaves target state unknown
                    automatic_replay_attempted=False,
                    rollback_attempts=rollback_attempts,
                    error=err_msg,
                )

            self._audit(
                controller,
                "rollback_completed",
                prev_state,
                "success",
                f"Rollback strategy '{spec.rollback.strategy}' completed; entering RECOVERY_CHECK.",
                corr_id,
                {"rollback_attempts": rollback_attempts},
            )
        else:
            self._audit(
                controller,
                "rollback_skipped",
                prev_state,
                "success",
                "Rollback skipped (not required); already in RECOVERY_CHECK.",
                corr_id,
                {"rollback_attempts": 0},
            )

        # ---- Step 2: Independent post-recovery steady-state measurement (gates adapter verdict)
        post_snap = None
        try:
            post_snap = self.observer.record_post_recovery(
                run=run, spec=spec, override_metrics=post_recovery_metrics
            )
        except KeyError:
            post_snap = self.observer.steady_state_evaluator.measure(
                spec, phase="post_recovery", override_metrics=post_recovery_metrics
            )
        proxy.post_recovery_healthy = post_snap.healthy
        proxy.post_recovery_failed_checks = list(post_snap.failed_checks)

        # ---- Step 3: Recovery verification via LifecycleController (RECOVERY_CHECK -> terminal | stays RECOVERY_CHECK)
        prev_state = self._state(run)
        controller.verify_recovery(adapter=proxy)
        classification = RecoveryClassifier.classify(run, has_authoritative_state=True).value
        gating = proxy.recovery_gating_decision

        if run.state == LifecycleState.RECOVERY_CHECK and run.recovery.status == "inconclusive":
            # Inconclusive recovery MUST remain unresolved, never COMPLETED.
            self._audit(
                controller,
                "recovery_inconclusive",
                prev_state,
                "unresolved",
                "Recovery verification returned INCONCLUSIVE; run remains unresolved in RECOVERY_CHECK.",
                corr_id,
                {"outcome_uncertain": True, "automatic_replay": False, "gating": gating},
            )
            return RollbackOutcome(
                run_id=run.run_id,
                experiment_id=spec.experiment_id,
                rollback_status="completed",
                recovery_status="unresolved",
                final_lifecycle_state=self._state(run),
                recovery_classification=classification,
                outcome_uncertain=True,
                rollback_attempts=rollback_attempts,
                recovery_gating_decision=gating,
                error="Recovery verification was inconclusive; state remains unresolved.",
            )

        if run.state == LifecycleState.RECOVERY_FAILED:
            exc = proxy.exceptions.get("verify_recovery")
            is_uncertain = isinstance(exc, UncertainFaultOperationError)
            err_msg = run.recovery.error or "Recovery verification failed."
            self._audit(
                controller,
                "recovery_failed",
                prev_state,
                "uncertain" if is_uncertain else "failed",
                err_msg,
                corr_id,
                {"outcome_uncertain": is_uncertain, "automatic_replay": False, "gating": gating},
            )
            return RollbackOutcome(
                run_id=run.run_id,
                experiment_id=spec.experiment_id,
                rollback_status="completed",
                recovery_status="unresolved" if is_uncertain else "failed",
                final_lifecycle_state=self._state(run),
                recovery_classification=classification,
                outcome_uncertain=is_uncertain,
                rollback_attempts=rollback_attempts,
                recovery_gating_decision=gating,
                error=err_msg,
            )

        if run.state == LifecycleState.FAILED:
            msg = (
                proxy.results.get("verify_recovery").message
                if proxy.results.get("verify_recovery") is not None
                else "Recovery confirmed as failed."
            )
            self._audit(
                controller,
                "recovery_confirmed_failure",
                prev_state,
                "failed",
                msg or "Recovery confirmed as failed.",
                corr_id,
                {"gating": gating, "post_recovery_failed_checks": proxy.post_recovery_failed_checks},
            )
            return RollbackOutcome(
                run_id=run.run_id,
                experiment_id=spec.experiment_id,
                rollback_status="completed",
                recovery_status="failed",
                final_lifecycle_state=self._state(run),
                recovery_classification=classification,
                rollback_attempts=rollback_attempts,
                recovery_gating_decision=gating,
                error=msg,
            )

        # COMPLETED (confirmed success) or ABORTED (confirmed rollback after abort)
        self._audit(
            controller,
            "recovery_verified",
            prev_state,
            "success",
            f"Recovery verified with independent steady-state evidence; run is '{self._state(run)}'.",
            corr_id,
            {"gating": gating},
        )
        return RollbackOutcome(
            run_id=run.run_id,
            experiment_id=spec.experiment_id,
            rollback_status="completed",
            recovery_status="passed",
            final_lifecycle_state=self._state(run),
            recovery_classification=classification,
            rollback_attempts=rollback_attempts,
            recovery_gating_decision=gating,
        )
