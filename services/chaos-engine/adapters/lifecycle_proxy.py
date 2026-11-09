"""Lifecycle Adapter Proxy for CHAOS-INTEL Phase 3C.

Wraps any `ExecutionAdapter` so that the chaos engine can drive the existing
`LifecycleController` (the single source of truth for state transitions) while:
- recording every per-phase result and exception (for evidence, audit, and
  uncertain-outcome detection),
- counting adapter invocations (to prove zero automatic replay), and
- gating recovery verdicts with independent steady-state evidence, so that an
  adapter-reported success is downgraded to `CONFIRMED_FAILURE` when the
  post-recovery steady state is not restored, and mapped to
  `CONFIRMED_ROLLBACK` when the experiment was aborted.

The proxy never mutates `ExperimentRun.state`; all transitions remain owned by
`LifecycleController` and `assert_valid_transition`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_APP_INTEL_ROOT = Path(__file__).resolve().parents[2] / "application-intelligence"
if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

from src.execution.adapters.base import ExecutionAdapter
from src.execution.adapters.capabilities import AdapterCapabilities
from src.execution.adapters.context import ExecutionContext
from src.execution.adapters.result import ExecutionResult
from src.execution.recovery import RecoveryResult, RecoveryResultVariant


class LifecycleAdapterProxy(ExecutionAdapter):
    """Delegating, recording, recovery-gating proxy around an `ExecutionAdapter`."""

    PHASES = ("prepare", "execute", "observe", "abort", "rollback", "verify_recovery", "cleanup")

    def __init__(self, inner: ExecutionAdapter) -> None:
        if isinstance(inner, LifecycleAdapterProxy):
            inner = inner.inner
        self.inner: ExecutionAdapter = inner
        self.results: Dict[str, Any] = {}
        self.exceptions: Dict[str, BaseException] = {}
        self.invocations: Dict[str, int] = {p: 0 for p in self.PHASES}
        self.history: List[str] = []

        # Recovery gating inputs (set by the engine before verify_recovery)
        self.post_recovery_healthy: Optional[bool] = None
        self.post_recovery_failed_checks: List[str] = []
        self.abort_was_requested: bool = False
        self.recovery_gating_decision: Optional[str] = None

    # ``ExecutionAdapter.capabilities`` is declared as a classmethod; the proxy
    # delegates per-instance so the wrapped adapter's identity is preserved.
    def capabilities(self) -> AdapterCapabilities:  # type: ignore[override]
        return self.inner.capabilities()

    @property
    def supports_live_execution(self) -> bool:
        return bool(getattr(self.inner, "supports_live_execution", False))

    def _call(self, phase: str, context: ExecutionContext) -> Any:
        self.invocations[phase] += 1
        self.history.append(phase)
        try:
            result = getattr(self.inner, phase)(context)
        except BaseException as exc:
            self.exceptions[phase] = exc
            raise
        self.results[phase] = result
        return result

    def prepare(self, context: ExecutionContext) -> ExecutionResult:
        return self._call("prepare", context)

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        return self._call("execute", context)

    def observe(self, context: ExecutionContext) -> ExecutionResult:
        return self._call("observe", context)

    def abort(self, context: ExecutionContext) -> ExecutionResult:
        return self._call("abort", context)

    def rollback(self, context: ExecutionContext) -> ExecutionResult:
        return self._call("rollback", context)

    def cleanup(self, context: ExecutionContext) -> ExecutionResult:
        return self._call("cleanup", context)

    def verify_recovery(self, context: ExecutionContext) -> RecoveryResult:
        result: RecoveryResult = self._call("verify_recovery", context)

        if result.variant == RecoveryResultVariant.CONFIRMED_SUCCESS:
            if self.post_recovery_healthy is False:
                self.recovery_gating_decision = "downgraded_success_to_failure_steady_state_not_restored"
                gated = RecoveryResult(
                    variant=RecoveryResultVariant.CONFIRMED_FAILURE,
                    run_id=result.run_id,
                    message=(
                        "Adapter reported recovery success, but independent post-recovery steady-state "
                        f"checks failed: {self.post_recovery_failed_checks}"
                    ),
                )
                self.results["verify_recovery"] = gated
                return gated
            if self.abort_was_requested:
                self.recovery_gating_decision = "mapped_success_to_confirmed_rollback_after_abort"
                gated = RecoveryResult(
                    variant=RecoveryResultVariant.CONFIRMED_ROLLBACK,
                    run_id=result.run_id,
                    message=f"Experiment aborted; rollback and recovery confirmed. {result.message or ''}".strip(),
                )
                self.results["verify_recovery"] = gated
                return gated

        self.recovery_gating_decision = f"passthrough_{result.variant.value}"
        return result

