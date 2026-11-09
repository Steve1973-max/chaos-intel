"""Observability & OpenTelemetry-Compatible Telemetry Collector for CHAOS-INTEL Phase 3C.

Captures:
- Baseline metrics (`cpu_percent`, `memory_percent`, `latency_p95_ms`, `error_rate`, `availability_ratio`)
- Fault start and end timestamps
- CPU and memory measurements during fault injection
- Latency and error-rate deltas relative to baseline
- Service availability ratio
- Recovery duration (`recovery_duration_ms`)
- Correlation IDs and OpenTelemetry-compatible span/metric records
- Structured `EvidenceRef` instances attached to `ExperimentRun`
"""

from __future__ import annotations

import hashlib
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

_APP_INTEL_ROOT = Path(__file__).resolve().parents[1] / "application-intelligence"
if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

from src.models.experiment import ExperimentSpecification
from src.models.experiment_run import EvidenceRef, ExperimentRun

from steady_state import SteadyStateEvaluator, SteadyStateSnapshot, TriggeredAbortCondition


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class OpenTelemetryMetricPoint(BaseModel):
    """OpenTelemetry-compatible metric data point."""

    name: str
    unit: str
    value: float
    timestamp: str = Field(default_factory=utcnow_iso)
    attributes: Dict[str, Any] = Field(default_factory=dict)


class OpenTelemetrySpanRecord(BaseModel):
    """OpenTelemetry-compatible trace span record."""

    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    name: str
    start_time: str
    end_time: str
    status_code: str = "OK"  # OK, ERROR
    attributes: Dict[str, Any] = Field(default_factory=dict)


class TelemetryDelta(BaseModel):
    """Computed delta between baseline and fault observation windows."""

    cpu_percent_delta: float = 0.0
    memory_percent_delta: float = 0.0
    latency_p95_ms_delta: float = 0.0
    error_rate_delta: float = 0.0
    availability_ratio_delta: float = 0.0


class ExperimentObservationRecord(BaseModel):
    """Aggregated observability record for a chaos experiment run."""

    run_id: str
    experiment_id: str
    application_id: str
    correlation_id: str
    trace_id: str
    baseline_snapshot: Optional[SteadyStateSnapshot] = None
    fault_started_at: Optional[str] = None
    fault_ended_at: Optional[str] = None
    observation_snapshots: List[SteadyStateSnapshot] = Field(default_factory=list)
    post_recovery_snapshot: Optional[SteadyStateSnapshot] = None
    recovery_started_at: Optional[str] = None
    recovery_completed_at: Optional[str] = None
    recovery_duration_ms: Optional[float] = None
    telemetry_delta: TelemetryDelta = Field(default_factory=TelemetryDelta)
    triggered_abort_conditions: List[TriggeredAbortCondition] = Field(default_factory=list)
    otel_metrics: List[OpenTelemetryMetricPoint] = Field(default_factory=list)
    otel_spans: List[OpenTelemetrySpanRecord] = Field(default_factory=list)
    evidence_refs: List[EvidenceRef] = Field(default_factory=list)


class ExperimentObserver:
    """Collects telemetry, evaluates safety abort thresholds, and records structured evidence."""

    METRIC_UNITS: Dict[str, str] = {
        "cpu_percent": "%",
        "memory_percent": "%",
        "latency_p95_ms": "ms",
        "error_rate": "1",
        "availability_ratio": "1",
    }

    def __init__(self, steady_state_evaluator: Optional[SteadyStateEvaluator] = None) -> None:
        self.steady_state_evaluator = steady_state_evaluator or SteadyStateEvaluator()
        self._records: Dict[str, ExperimentObservationRecord] = {}
        self._recovery_timers: Dict[str, float] = {}

    def start_observation_session(
        self,
        run: ExperimentRun,
        spec: ExperimentSpecification,
        correlation_id: Optional[str] = None,
    ) -> ExperimentObservationRecord:
        corr_id = correlation_id or run.run_id
        trace_id = hashlib.sha256(f"trace:{run.run_id}:{corr_id}".encode("utf-8")).hexdigest()[:32]
        record = ExperimentObservationRecord(
            run_id=run.run_id,
            experiment_id=spec.experiment_id,
            application_id=spec.application_id,
            correlation_id=corr_id,
            trace_id=trace_id,
        )
        self._records[run.run_id] = record
        return record

    def get_record(self, run_id: str) -> ExperimentObservationRecord:
        if run_id not in self._records:
            raise KeyError(f"No observation record found for run_id '{run_id}'.")
        return self._records[run_id]

    def _append_otel_metrics(
        self,
        record: ExperimentObservationRecord,
        phase: str,
        metrics: Dict[str, float],
    ) -> None:
        for name, val in sorted(metrics.items()):
            record.otel_metrics.append(
                OpenTelemetryMetricPoint(
                    name=f"chaos.experiment.{name}",
                    unit=self.METRIC_UNITS.get(name, "1"),
                    value=float(val),
                    timestamp=utcnow_iso(),
                    attributes={
                        "run_id": record.run_id,
                        "experiment_id": record.experiment_id,
                        "application_id": record.application_id,
                        "correlation_id": record.correlation_id,
                        "phase": phase,
                    },
                )
            )

    def _add_evidence(
        self,
        run: ExperimentRun,
        record: ExperimentObservationRecord,
        ev_type: str,
        location: str,
        metadata: Dict[str, Any],
    ) -> EvidenceRef:
        idx = len(record.evidence_refs) + 1
        ev = EvidenceRef(
            evidence_id=f"{run.run_id}-ev-{idx:02d}",
            type=ev_type,
            location=location,
            metadata={"correlation_id": record.correlation_id, **metadata},
        )
        record.evidence_refs.append(ev)
        run.evidence_refs.append(ev)
        return ev

    def record_evidence(
        self,
        run: ExperimentRun,
        ev_type: str,
        location: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EvidenceRef:
        """Attach structured evidence to both the observation record and the `ExperimentRun`."""
        return self._add_evidence(run, self.get_record(run.run_id), ev_type, location, metadata or {})

    def record_baseline(
        self,
        run: ExperimentRun,
        spec: ExperimentSpecification,
        override_metrics: Optional[Dict[str, float]] = None,
    ) -> SteadyStateSnapshot:
        record = self.get_record(run.run_id)
        snap = self.steady_state_evaluator.measure(
            spec, phase="baseline", override_metrics=override_metrics
        )
        record.baseline_snapshot = snap
        self._append_otel_metrics(record, "baseline", snap.metrics)
        self._add_evidence(
            run=run,
            record=record,
            ev_type="baseline_telemetry",
            location=f"otel://metrics/{record.trace_id}/baseline",
            metadata={"healthy": snap.healthy, "metrics": snap.metrics},
        )
        return snap

    def mark_fault_start(self, run_id: str) -> str:
        record = self.get_record(run_id)
        ts = utcnow_iso()
        record.fault_started_at = ts
        return ts

    def mark_fault_end(self, run_id: str) -> str:
        record = self.get_record(run_id)
        ts = utcnow_iso()
        record.fault_ended_at = ts
        if record.fault_started_at:
            span_id = hashlib.sha256(f"{record.trace_id}:fault".encode("utf-8")).hexdigest()[:16]
            record.otel_spans.append(
                OpenTelemetrySpanRecord(
                    trace_id=record.trace_id,
                    span_id=span_id,
                    name="chaos.fault_window",
                    start_time=record.fault_started_at,
                    end_time=ts,
                    status_code="OK",
                    attributes={"run_id": run_id, "experiment_id": record.experiment_id},
                )
            )
        return ts

    def observe_window(
        self,
        run: ExperimentRun,
        spec: ExperimentSpecification,
        observed_metrics: Optional[Dict[str, float]] = None,
    ) -> List[TriggeredAbortCondition]:
        record = self.get_record(run.run_id)
        snap = self.steady_state_evaluator.measure(
            spec, phase="observation", override_metrics=observed_metrics
        )
        record.observation_snapshots.append(snap)
        self._append_otel_metrics(record, "observation", snap.metrics)

        if record.baseline_snapshot is not None:
            base = record.baseline_snapshot.metrics
            obs = snap.metrics
            record.telemetry_delta = TelemetryDelta(
                cpu_percent_delta=round(obs.get("cpu_percent", 0.0) - base.get("cpu_percent", 0.0), 4),
                memory_percent_delta=round(obs.get("memory_percent", 0.0) - base.get("memory_percent", 0.0), 4),
                latency_p95_ms_delta=round(obs.get("latency_p95_ms", 0.0) - base.get("latency_p95_ms", 0.0), 4),
                error_rate_delta=round(obs.get("error_rate", 0.0) - base.get("error_rate", 0.0), 6),
                availability_ratio_delta=round(
                    obs.get("availability_ratio", 0.0) - base.get("availability_ratio", 0.0), 6
                ),
            )

        triggered = SteadyStateEvaluator.evaluate_abort_conditions(
            spec.abort_conditions, snap.metrics
        )
        if triggered:
            record.triggered_abort_conditions.extend(triggered)
            self._add_evidence(
                run=run,
                record=record,
                ev_type="safety_threshold_breach",
                location=f"otel://alerts/{record.trace_id}/abort-threshold",
                metadata={
                    "triggered": [t.model_dump() for t in triggered],
                    "metrics": snap.metrics,
                },
            )
        else:
            self._add_evidence(
                run=run,
                record=record,
                ev_type="observation_telemetry",
                location=f"otel://metrics/{record.trace_id}/observation-{len(record.observation_snapshots)}",
                metadata={
                    "metrics": snap.metrics,
                    "delta": record.telemetry_delta.model_dump(),
                },
            )

        return triggered

    def mark_recovery_start(self, run_id: str) -> None:
        record = self.get_record(run_id)
        record.recovery_started_at = utcnow_iso()
        self._recovery_timers[run_id] = time.perf_counter()

    def record_post_recovery(
        self,
        run: ExperimentRun,
        spec: ExperimentSpecification,
        override_metrics: Optional[Dict[str, float]] = None,
    ) -> SteadyStateSnapshot:
        record = self.get_record(run.run_id)
        record.recovery_completed_at = utcnow_iso()
        if run.run_id in self._recovery_timers:
            elapsed_ms = round((time.perf_counter() - self._recovery_timers.pop(run.run_id)) * 1000.0, 3)
            record.recovery_duration_ms = max(0.0, elapsed_ms)
        else:
            record.recovery_duration_ms = 0.0

        snap = self.steady_state_evaluator.measure(
            spec, phase="post_recovery", override_metrics=override_metrics
        )
        record.post_recovery_snapshot = snap
        self._append_otel_metrics(record, "post_recovery", snap.metrics)
        self._add_evidence(
            run=run,
            record=record,
            ev_type="recovery_telemetry",
            location=f"otel://metrics/{record.trace_id}/post-recovery",
            metadata={
                "healthy": snap.healthy,
                "recovery_duration_ms": record.recovery_duration_ms,
                "metrics": snap.metrics,
            },
        )
        return snap

