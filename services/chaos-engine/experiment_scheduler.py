"""Chaos Experiment Orchestration Engine for CHAOS-INTEL Phase 3C.

Coordinates the complete 14-step controlled chaos experiment lifecycle:
 1. Experiment creation
 2. Specification validation (`ExperimentValidator`)
 3. Target authorization (`ChaosEngineSettings`, `LIVE_EXECUTION_ENABLED`)
 4. Preflight checks (`controller.start_preflight()`)
 5. Steady-state baseline measurement (`observer.record_baseline()`)
 6. Blast-radius assessment (`BlastRadiusAnalyzer`)
 7. Safety approval handling (`controller.grant_approval()`, `controller.authorize()`)
 8. Execution preparation (`controller.setup()`)
 9. Fault injection (`controller.run_experiment()`)
10. Continuous observation (`controller.observe()`, `observer.observe_window()`)
11. Automatic abort on safety threshold breaches (`controller.request_abort()`)
12. Rollback & recovery verification (`RollbackManager.execute_rollback_and_verify_recovery()`)
13. Evidence collection & schema validation (`experiment-run.schema.json`, OTel, audits)
14. Final experiment report (`ChaosExperimentReport`)

Guarantees:
- Single source of truth: all `ExperimentRun` lifecycle transitions are owned strictly
  by `LifecycleController`.
- Phase 3C safety invariant: live execution is strictly disabled (`LIVE_EXECUTION_ENABLED = False`).
- Zero automatic replay of uncertain external operations.
- Inconclusive recovery is treated as unresolved, never successful.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
import jsonschema

_APP_INTEL_ROOT = Path(__file__).resolve().parents[1] / "application-intelligence"
if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

_SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "packages" / "schemas"

from src.execution.adapters.base import ExecutionAdapter
from src.execution.lifecycle import LifecycleController, create_experiment_run
from src.execution.recovery import RecoveryClassifier
from src.execution.reliability.audit import AuditEvent, AuditLogger
from src.execution.states import LifecycleState
from src.models.application import ApplicationModel
from src.models.experiment import ExperimentSpecification
from src.models.experiment_run import ExperimentRun
from src.models.safety import SafetyDecision
from src.safety.engine import evaluate_experiment_safety

from adapters.base import DeclarativeSpecTranslator
from adapters.dry_run import ChaosDryRunAdapter
from adapters.lifecycle_proxy import LifecycleAdapterProxy
from blast_radius import BlastRadiusAnalyzer, BlastRadiusAssessment
from engine_models import (
    LIVE_EXECUTION_ENABLED,
    AbortRecord,
    ApprovalGrant,
    ChaosEngineSettings,
    ChaosExperimentReport,
    ExperimentCancellationToken,
    ExperimentVerdict,
    LiveExecutionAuthorization,
    utcnow_iso,
)
from experiment_observer import ExperimentObserver
from experiment_registry import ExperimentRegistry
from experiment_validator import ExperimentValidator, ValidationReport
from fault_injector import FaultInjectionOutcome, FaultInjector
from rollback_manager import RollbackManager, RollbackOutcome


def _validate_run_schema(run: ExperimentRun) -> List[str]:
    schema_path = _SCHEMAS_DIR / "experiment-run.schema.json"
    if not schema_path.exists():
        return [f"Schema file 'experiment-run.schema.json' not found at {schema_path}"]
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft7Validator(schema)
        raw = run.model_dump()
        return [e.message for e in validator.iter_errors(raw)]
    except Exception as exc:
        return [f"Schema validation error: {exc}"]


class ExperimentScheduler:
    """Orchestrates controlled chaos experiments across all 14 lifecycle steps."""

    def __init__(
        self,
        settings: Optional[ChaosEngineSettings] = None,
        validator: Optional[ExperimentValidator] = None,
        registry: Optional[ExperimentRegistry] = None,
        observer: Optional[ExperimentObserver] = None,
        rollback_manager: Optional[RollbackManager] = None,
        fault_injector: Optional[FaultInjector] = None,
        blast_analyzer: Optional[BlastRadiusAnalyzer] = None,
        audit_logger: Optional[AuditLogger] = None,
    ) -> None:
        self.settings = settings or ChaosEngineSettings()
        self.validator = validator or ExperimentValidator()
        self.registry = registry or ExperimentRegistry()
        self.observer = observer or ExperimentObserver()
        self.audit_logger = audit_logger or AuditLogger()
        self.rollback_manager = rollback_manager or RollbackManager(
            audit_logger=self.audit_logger, observer=self.observer
        )
        self.fault_injector = fault_injector or FaultInjector(
            observer=self.observer, audit_logger=self.audit_logger
        )
        self.blast_analyzer = blast_analyzer or BlastRadiusAnalyzer()

    @staticmethod
    def _state(run: Any) -> str:
        return str(getattr(run.state, "value", run.state))

    def _audit(
        self,
        run_id: str,
        app_id: str,
        exp_id: str,
        event_type: str,
        prev_state: str,
        curr_state: str,
        outcome: str,
        reason: str,
        correlation_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.audit_logger.log(
            AuditEvent(
                run_id=run_id,
                application_id=app_id,
                experiment_id=exp_id,
                event_type=event_type,
                previous_state=prev_state,
                current_state=curr_state,
                outcome=outcome,
                reason=reason,
                correlation_id=correlation_id,
                metadata=metadata or {},
            )
        )

    def run_experiment(
        self,
        spec: ExperimentSpecification,
        app: ApplicationModel,
        adapter: Optional[ExecutionAdapter] = None,
        approval_grant: Optional[ApprovalGrant] = None,
        live_authorization: Optional[LiveExecutionAuthorization] = None,
        cancellation_token: Optional[ExperimentCancellationToken] = None,
        baseline_metrics: Optional[Dict[str, float]] = None,
        observation_metrics: Optional[List[Dict[str, float]]] = None,
        post_recovery_metrics: Optional[Dict[str, float]] = None,
        correlation_id: Optional[str] = None,
    ) -> ChaosExperimentReport:
        """Execute a single chaos experiment through all 14 lifecycle steps."""
        report_id = f"rpt-{uuid.uuid4().hex[:12]}"
        corr_id = correlation_id or f"corr-{uuid.uuid4().hex[:8]}"
        mode = spec.metadata.get("execution_mode", spec.metadata.get("mode", "dry_run"))
        is_live_requested = (mode == "live") or (
            adapter is not None and getattr(adapter, "supports_live_execution", False)
        )

        # -------------------------------------------------------------
        # STEP 1 & 2: Experiment Validation & Registration
        # -------------------------------------------------------------
        val_report: ValidationReport = self.validator.validate(spec, app)
        self.registry.store_validated(spec, val_report)

        if not val_report.valid:
            self._audit(
                run_id=f"unregistered-{spec.experiment_id}",
                app_id=spec.application_id,
                exp_id=spec.experiment_id,
                event_type="validation_rejected",
                prev_state="NONE",
                curr_state="REJECTED",
                outcome="rejected",
                reason=f"Specification validation failed: {'; '.join(val_report.errors)}",
                correlation_id=corr_id,
                metadata={"errors": val_report.errors, "warnings": val_report.warnings},
            )
            return ChaosExperimentReport(
                report_id=report_id,
                run_id=f"unregistered-{spec.experiment_id}",
                experiment_id=spec.experiment_id,
                application_id=spec.application_id,
                correlation_id=corr_id,
                mode=mode,
                live_execution=False,
                verdict="rejected",
                final_lifecycle_state="REJECTED",
                fault_type=spec.fault.type,
                target_id=spec.target.id,
                duration_seconds=spec.duration_seconds,
                safety_decision_id="none",
                safety_decision="rejected",
                validation_errors=val_report.errors,
                validation_warnings=val_report.warnings,
                errors=val_report.errors,
                audit_events=[e.model_dump() for e in self.audit_logger.get_events(f"unregistered-{spec.experiment_id}")],
            )

        # -------------------------------------------------------------
        # STEP 3: Target Authorization & Guardrail Enforcement
        # -------------------------------------------------------------
        auth_errors: List[str] = []
        target_env = spec.safety.environment_required or spec.metadata.get("environment", "")
        if target_env not in self.settings.authorized_environments:
            auth_errors.append(
                f"Target environment '{target_env}' is not authorized. "
                f"Permitted: {sorted(self.settings.authorized_environments)}"
            )
        if self.settings.authorized_target_ids is not None:
            if spec.target.id not in self.settings.authorized_target_ids:
                auth_errors.append(f"Target ID '{spec.target.id}' is not in authorized targets.")
        if spec.duration_seconds > self.settings.max_fault_duration_seconds:
            auth_errors.append(
                f"Duration {spec.duration_seconds}s exceeds engine maximum "
                f"{self.settings.max_fault_duration_seconds}s."
            )

        # Live execution invariant
        if is_live_requested:
            if not LIVE_EXECUTION_ENABLED:
                auth_errors.append(
                    "Live chaos fault execution is strictly disabled in Phase 3C (safety invariant)."
                )

        if auth_errors:
            self._audit(
                run_id=f"unauthorized-{spec.experiment_id}",
                app_id=spec.application_id,
                exp_id=spec.experiment_id,
                event_type="target_authorization_rejected",
                prev_state="NONE",
                curr_state="REJECTED",
                outcome="rejected",
                reason=f"Target authorization guardrail failure: {'; '.join(auth_errors)}",
                correlation_id=corr_id,
                metadata={"auth_errors": auth_errors},
            )
            return ChaosExperimentReport(
                report_id=report_id,
                run_id=f"unauthorized-{spec.experiment_id}",
                experiment_id=spec.experiment_id,
                application_id=spec.application_id,
                correlation_id=corr_id,
                mode=mode,
                live_execution=False,
                verdict="rejected",
                final_lifecycle_state="REJECTED",
                fault_type=spec.fault.type,
                target_id=spec.target.id,
                duration_seconds=spec.duration_seconds,
                safety_decision_id="none",
                safety_decision="rejected",
                validation_errors=auth_errors,
                errors=auth_errors,
                audit_events=[e.model_dump() for e in self.audit_logger.get_events(f"unauthorized-{spec.experiment_id}")],
            )

        # -------------------------------------------------------------
        # STEP 4: Preflight Checks
        # -------------------------------------------------------------
        safety_dec = val_report.safety_decision or evaluate_experiment_safety(spec, app)

        run = create_experiment_run(spec, safety_dec)
        self.registry.record_run(run)

        controller = LifecycleController(run=run, spec=spec, decision=safety_dec, app=app)
        self.observer.start_observation_session(run=run, spec=spec, correlation_id=corr_id)

        prev_state = self._state(run)
        controller.start_preflight()
        self._audit(
            run_id=run.run_id,
            app_id=spec.application_id,
            exp_id=spec.experiment_id,
            event_type="preflight_started",
            prev_state=prev_state,
            curr_state=self._state(run),
            outcome="passed" if run.state != LifecycleState.FAILED else "failed",
            reason="Preflight checks executed.",
            correlation_id=corr_id,
        )

        if run.state == LifecycleState.FAILED:
            err_msg = run.error.message if run.error else "Preflight checks failed."
            return self._build_report(
                report_id=report_id,
                controller=controller,
                proxy=None,
                val_report=val_report,
                corr_id=corr_id,
                verdict="failed",
                errors=[err_msg],
            )

        # -------------------------------------------------------------
        # STEP 5: Steady-State Baseline Measurement
        # -------------------------------------------------------------
        baseline_snap = self.observer.record_baseline(
            run=run, spec=spec, override_metrics=baseline_metrics
        )
        if not baseline_snap.healthy:
            prev_state = self._state(run)
            msg = f"Baseline steady state is unhealthy prior to injection: {baseline_snap.failed_checks}"
            controller.fail("BaselineDegradedError", msg)
            self._audit(
                run_id=run.run_id,
                app_id=spec.application_id,
                exp_id=spec.experiment_id,
                event_type="baseline_unhealthy_aborted",
                prev_state=prev_state,
                curr_state=self._state(run),
                outcome="failed",
                reason=msg,
                correlation_id=corr_id,
                metadata={"failed_checks": baseline_snap.failed_checks},
            )
            return self._build_report(
                report_id=report_id,
                controller=controller,
                proxy=None,
                val_report=val_report,
                corr_id=corr_id,
                verdict="failed",
                errors=[msg],
            )

        # -------------------------------------------------------------
        # STEP 6: Blast-Radius Assessment
        # -------------------------------------------------------------
        blast_assessment: BlastRadiusAssessment = val_report.blast_radius_assessment or self.blast_analyzer.assess(
            spec, app
        )

        # -------------------------------------------------------------
        # STEP 7: Safety Approval Handling & Authorization
        # -------------------------------------------------------------
        if safety_dec.decision in ("rejected", "requires_configuration"):
            prev_state = self._state(run)
            controller.fail(
                "SafetyPolicyRejection",
                f"Safety Engine returned '{safety_dec.decision}': {'; '.join(safety_dec.reasons)}",
            )
            self._audit(
                run_id=run.run_id,
                app_id=spec.application_id,
                exp_id=spec.experiment_id,
                event_type="safety_policy_rejected",
                prev_state=prev_state,
                curr_state=self._state(run),
                outcome="rejected",
                reason="Safety policy rejected experiment execution.",
                correlation_id=corr_id,
                metadata={"reasons": safety_dec.reasons},
            )
            return self._build_report(
                report_id=report_id,
                controller=controller,
                proxy=None,
                val_report=val_report,
                corr_id=corr_id,
                verdict="rejected",
                blast_radius=blast_assessment,
                errors=list(safety_dec.reasons),
            )

        if run.approval.required:
            if not approval_grant or not approval_grant.approved:
                prev_state = self._state(run)
                controller.fail(
                    "ApprovalMissingError",
                    "Safety decision requires human approval, but no valid ApprovalGrant was provided.",
                )
                self._audit(
                    run_id=run.run_id,
                    app_id=spec.application_id,
                    exp_id=spec.experiment_id,
                    event_type="approval_missing",
                    prev_state=prev_state,
                    curr_state=self._state(run),
                    outcome="rejected",
                    reason="Experiment execution lacks required human approval grant.",
                    correlation_id=corr_id,
                )
                return self._build_report(
                    report_id=report_id,
                    controller=controller,
                    proxy=None,
                    val_report=val_report,
                    corr_id=corr_id,
                    verdict="rejected",
                    blast_radius=blast_assessment,
                    errors=["ApprovalGrant missing or unapproved."],
                )

            # Satisfy required conditions from the approval grant
            for cond in run.required_conditions:
                evidence = approval_grant.condition_evidence.get(
                    cond.description, f"Approved by {approval_grant.approver}"
                )
                controller.satisfy_condition(cond.condition_id, evidence)

            controller.grant_approval(approver=approval_grant.approver)
            self._audit(
                run_id=run.run_id,
                app_id=spec.application_id,
                exp_id=spec.experiment_id,
                event_type="approval_granted",
                prev_state="AUTHORIZATION_PENDING",
                curr_state="AUTHORIZATION_PENDING",
                outcome="approved",
                reason=f"Approved by human operator '{approval_grant.approver}'.",
                correlation_id=corr_id,
                metadata={"approver": approval_grant.approver, "reference": approval_grant.reference},
            )

        prev_state = self._state(run)
        try:
            controller.authorize()
            self._audit(
                run_id=run.run_id,
                app_id=spec.application_id,
                exp_id=spec.experiment_id,
                event_type="authorization_completed",
                prev_state=prev_state,
                curr_state=self._state(run),
                outcome="authorized",
                reason="All conditions and approvals satisfied; experiment authorized.",
                correlation_id=corr_id,
            )
        except BaseException as exc:
            controller.fail("AuthorizationError", str(exc))
            return self._build_report(
                report_id=report_id,
                controller=controller,
                proxy=None,
                val_report=val_report,
                corr_id=corr_id,
                verdict="rejected",
                blast_radius=blast_assessment,
                errors=[f"Authorization failed: {exc}"],
            )

        # -------------------------------------------------------------
        # STEP 8: Execution Preparation (Adapter Selection & Proxy Wrapping)
        # -------------------------------------------------------------
        effective_adapter = adapter or ChaosDryRunAdapter()
        proxy = (
            effective_adapter
            if isinstance(effective_adapter, LifecycleAdapterProxy)
            else LifecycleAdapterProxy(effective_adapter)
        )

        # -------------------------------------------------------------
        # STEPS 9, 10, 11: Fault Injection, Observation, and Abort Handling
        # -------------------------------------------------------------
        injection_outcome: FaultInjectionOutcome = self.fault_injector.execute_injection_and_observation(
            controller=controller,
            adapter=proxy,
            cancellation_token=cancellation_token,
            observation_metrics=observation_metrics,
            max_windows=self.settings.max_observation_windows,
            correlation_id=corr_id,
        )

        # -------------------------------------------------------------
        # STEP 12: Rollback and Recovery Verification
        # -------------------------------------------------------------
        rollback_outcome: Optional[RollbackOutcome] = None
        if run.state in (
            LifecycleState.OBSERVING,
            LifecycleState.ABORT_REQUESTED,
            LifecycleState.ABORTED,
            LifecycleState.RECOVERY_CHECK,
        ):
            rollback_outcome = self.rollback_manager.execute_rollback_and_verify_recovery(
                controller=controller,
                adapter=proxy,
                correlation_id=corr_id,
                post_recovery_metrics=post_recovery_metrics,
            )

        # -------------------------------------------------------------
        # STEP 13 & 14: Evidence Collection & Final Report Assembly
        # -------------------------------------------------------------
        verdict: ExperimentVerdict
        if injection_outcome.cancelled:
            verdict = "cancelled"
        elif injection_outcome.aborted or run.state == LifecycleState.ABORTED:
            verdict = "aborted"
        elif run.state == LifecycleState.COMPLETED:
            verdict = "passed"
        elif run.state in (
            LifecycleState.FAILED,
            LifecycleState.ROLLBACK_FAILED,
            LifecycleState.RECOVERY_FAILED,
        ):
            verdict = "failed"
        elif run.state == LifecycleState.RECOVERY_CHECK:
            # Inconclusive recovery (e.g. Dry Run) remains unresolved
            verdict = "unresolved"
        else:
            verdict = "unresolved"

        # Determine if hypothesis held:
        # True only if execution passed and recovery completed cleanly
        hypothesis_held: Optional[bool]
        if verdict == "passed":
            hypothesis_held = True
        elif verdict in ("failed", "aborted"):
            hypothesis_held = False
        else:
            hypothesis_held = None

        abort_rec = AbortRecord(
            triggered=injection_outcome.aborted or run.abort.requested,
            source=injection_outcome.abort_source or run.abort.source,
            reason=injection_outcome.abort_reason or run.abort.reason,
            triggered_conditions=injection_outcome.triggered_abort_conditions,
        )

        return self._build_report(
            report_id=report_id,
            controller=controller,
            proxy=proxy,
            val_report=val_report,
            corr_id=corr_id,
            verdict=verdict,
            hypothesis_held=hypothesis_held,
            blast_radius=blast_assessment,
            abort_record=abort_rec,
            rollback_outcome=rollback_outcome,
            injection_outcome=injection_outcome,
        )

    def schedule_batch(
        self,
        experiments: List[ExperimentSpecification],
        app: ApplicationModel,
        adapter: Optional[ExecutionAdapter] = None,
        approval_grant: Optional[ApprovalGrant] = None,
        stop_on_failure: bool = False,
    ) -> List[ChaosExperimentReport]:
        """Execute a batch of experiments sequentially with optional early abort."""
        reports: List[ChaosExperimentReport] = []
        for spec in experiments:
            report = self.run_experiment(
                spec=spec,
                app=app,
                adapter=adapter,
                approval_grant=approval_grant,
            )
            reports.append(report)
            if stop_on_failure and report.verdict in ("failed", "aborted", "rejected"):
                break
        return reports

    def _build_report(
        self,
        report_id: str,
        controller: LifecycleController,
        proxy: Optional[LifecycleAdapterProxy],
        val_report: ValidationReport,
        corr_id: str,
        verdict: ExperimentVerdict,
        hypothesis_held: Optional[bool] = None,
        blast_radius: Optional[BlastRadiusAssessment] = None,
        abort_record: Optional[AbortRecord] = None,
        rollback_outcome: Optional[RollbackOutcome] = None,
        injection_outcome: Optional[FaultInjectionOutcome] = None,
        errors: Optional[List[str]] = None,
    ) -> ChaosExperimentReport:
        run = controller.run
        spec = controller.spec
        run_schema_errors = _validate_run_schema(run)

        # Declarative manifests for future engine execution
        manifests = {
            "pumba": DeclarativeSpecTranslator.to_pumba_spec(spec).model_dump(),
            "tc_netem": DeclarativeSpecTranslator.to_tc_netem_spec(spec).model_dump(),
            "chaos_mesh": DeclarativeSpecTranslator.to_chaos_mesh_crd(spec).model_dump(),
            "litmus_chaos": DeclarativeSpecTranslator.to_litmus_chaos_engine(spec).model_dump(),
        }

        obs_record = None
        try:
            obs_record = self.observer.get_record(run.run_id)
        except KeyError:
            pass

        adapter_invocations = proxy.invocations if proxy else {}
        phases_completed = proxy.history if proxy else []

        all_errors: List[str] = list(errors or [])
        if run.error and run.error.message:
            all_errors.append(f"{run.error.type}: {run.error.message}")
        if rollback_outcome and rollback_outcome.error:
            all_errors.append(f"Rollback/Recovery error: {rollback_outcome.error}")
        if injection_outcome and injection_outcome.error:
            all_errors.append(f"Injection error: {injection_outcome.error}")

        classification: Optional[str] = None
        try:
            classification = RecoveryClassifier.classify(run, has_authoritative_state=True).value
        except Exception:
            pass

        outcome_uncertain = (
            (rollback_outcome.outcome_uncertain if rollback_outcome else False)
            or (injection_outcome.outcome_uncertain if injection_outcome else False)
            or (run.recovery.status == "inconclusive")
        )

        return ChaosExperimentReport(
            report_id=report_id,
            run_id=run.run_id,
            experiment_id=spec.experiment_id,
            application_id=spec.application_id,
            correlation_id=corr_id,
            mode=spec.metadata.get("execution_mode", spec.metadata.get("mode", "dry_run")),
            live_execution=False,
            adapter_id=proxy.capabilities().adapter_id if proxy else None,
            verdict=verdict,
            hypothesis_held=hypothesis_held,
            final_lifecycle_state=str(getattr(run.state, "value", run.state)),
            recovery_classification=classification,
            outcome_uncertain=outcome_uncertain,
            automatic_replay_attempted=False,
            fault_type=spec.fault.type,
            target_id=spec.target.id,
            duration_seconds=spec.duration_seconds,
            risk_classification=val_report.fault_definition.risk_classification if val_report.fault_definition else None,
            safety_decision_id=controller.decision.decision_id if controller.decision else "none",
            safety_decision=controller.decision.decision if controller.decision else "none",
            validation_errors=val_report.errors,
            validation_warnings=val_report.warnings,
            blast_radius=blast_radius or val_report.blast_radius_assessment,
            abort=abort_record or AbortRecord(),
            rollback=rollback_outcome,
            observation=obs_record,
            adapter_invocations=adapter_invocations,
            lifecycle_phases_completed=phases_completed,
            evidence_refs=[ev.model_dump() for ev in run.evidence_refs],
            audit_events=[e.model_dump() for e in self.audit_logger.get_events(run.run_id)],
            declarative_manifests=manifests,
            run_schema_errors=run_schema_errors,
            errors=all_errors,
            generated_at=utcnow_iso(),
        )
