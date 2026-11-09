"""Steady-State Measurement & Abort Threshold Evaluation for CHAOS-INTEL Phase 3C.

Measures baseline and post-recovery system steady state and evaluates
declarative `AbortCondition`s against telemetry snapshots.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field

_APP_INTEL_ROOT = Path(__file__).resolve().parents[1] / "application-intelligence"
if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

from src.models.experiment import AbortCondition, ExperimentSpecification


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SteadyStateViolationError(RuntimeError):
    """Raised when steady-state verification fails."""


class SteadyStateSnapshot(BaseModel):
    """Point-in-time steady-state measurement."""

    phase: str = Field(min_length=1)  # baseline, observation, post_recovery
    timestamp: str = Field(default_factory=utcnow_iso)
    metrics: Dict[str, float] = Field(default_factory=dict)
    check_results: Dict[str, bool] = Field(default_factory=dict)
    healthy: bool = True
    failed_checks: List[str] = Field(default_factory=list)


class TriggeredAbortCondition(BaseModel):
    """Details of an abort condition breached during fault observation."""

    metric: str
    operator: str
    threshold: float
    observed_value: float
    action: str = "abort"
    reason: str


class SteadyStateEvaluator:
    """Evaluates pre-experiment baseline, continuous abort conditions, and post-recovery steady state."""

    DEFAULT_BASELINE_METRICS: Dict[str, float] = {
        "cpu_percent": 22.0,
        "memory_percent": 45.0,
        "latency_p95_ms": 48.0,
        "error_rate": 0.002,
        "availability_ratio": 0.999,
    }

    def __init__(
        self,
        probe_provider: Optional[Callable[[ExperimentSpecification, str], Dict[str, Any]]] = None,
    ) -> None:
        self._probe_provider = probe_provider

    def measure(
        self,
        spec: ExperimentSpecification,
        phase: str = "baseline",
        override_metrics: Optional[Dict[str, float]] = None,
        override_checks: Optional[Dict[str, bool]] = None,
    ) -> SteadyStateSnapshot:
        metrics: Dict[str, float] = dict(self.DEFAULT_BASELINE_METRICS)
        check_results: Dict[str, bool] = {
            chk: True for chk in (spec.steady_state.checks or [])
        }

        if self._probe_provider is not None:
            probed = self._probe_provider(spec, phase) or {}
            if "metrics" in probed and isinstance(probed["metrics"], dict):
                for k, v in probed["metrics"].items():
                    metrics[str(k)] = float(v)
            if "checks" in probed and isinstance(probed["checks"], dict):
                for k, v in probed["checks"].items():
                    check_results[str(k)] = bool(v)

        if override_metrics:
            for k, v in override_metrics.items():
                metrics[str(k)] = float(v)

        if override_checks:
            for k, v in override_checks.items():
                check_results[str(k)] = bool(v)

        # Also evaluate abort thresholds on baseline/post_recovery to detect unhealthy steady state
        breaches = self.evaluate_abort_conditions(spec.abort_conditions, metrics)
        failed_checks = [chk for chk, ok in check_results.items() if not ok]
        for b in breaches:
            failed_checks.append(f"threshold_breach:{b.metric}{b.operator}{b.threshold} (got {b.observed_value})")

        healthy = len(failed_checks) == 0
        return SteadyStateSnapshot(
            phase=phase,
            timestamp=utcnow_iso(),
            metrics=metrics,
            check_results=check_results,
            healthy=healthy,
            failed_checks=failed_checks,
        )

    @staticmethod
    def _compare(observed: float, operator: str, threshold: float) -> bool:
        op = operator.strip()
        if op == ">":
            return observed > threshold
        if op == ">=":
            return observed >= threshold
        if op == "<":
            return observed < threshold
        if op == "<=":
            return observed <= threshold
        if op in ("==", "="):
            return observed == threshold
        if op == "!=":
            return observed != threshold
        raise ValueError(f"Unsupported abort condition operator '{operator}'.")

    @classmethod
    def evaluate_abort_conditions(
        cls,
        abort_conditions: List[AbortCondition],
        metrics: Dict[str, float],
    ) -> List[TriggeredAbortCondition]:
        triggered: List[TriggeredAbortCondition] = []
        for ac in abort_conditions or []:
            if ac.threshold is None or ac.requires_configuration:
                continue
            if ac.metric not in metrics:
                continue
            obs = float(metrics[ac.metric])
            thresh = float(ac.threshold)
            if cls._compare(obs, ac.operator, thresh):
                triggered.append(
                    TriggeredAbortCondition(
                        metric=ac.metric,
                        operator=ac.operator,
                        threshold=thresh,
                        observed_value=obs,
                        action=ac.action,
                        reason=(
                            f"Safety threshold exceeded: metric '{ac.metric}' observed={obs} "
                            f"{ac.operator} threshold={thresh} (action={ac.action})"
                        ),
                    )
                )
        return triggered

