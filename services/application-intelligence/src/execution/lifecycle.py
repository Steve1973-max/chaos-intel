from datetime import datetime, timezone
from typing import Optional
import uuid
import hashlib
from ..models.experiment_run import ExperimentRun, ApprovalModel, RequiredConditionModel, RollbackRunModel, RecoveryModel
from ..models.experiment import ExperimentSpecification
from ..models.safety import SafetyDecision
from ..models.application import ApplicationModel
from .states import LifecycleState
from .transitions import assert_valid_transition
from .errors import *
from .preflight import run_preflight
from .authorization import authorize_run
from .base import ExecutionAdapter
from .adapters.context import ExecutionContext

class LifecycleController:
    def __init__(self, run: ExperimentRun, spec: ExperimentSpecification, decision: SafetyDecision, app: ApplicationModel):
        self.run = run
        self.spec = spec
        self.decision = decision
        self.app = app
        
        # Validate matching explicitly at controller instantiation for extra safety
        if self.decision.experiment_id != self.spec.experiment_id:
            raise ExperimentMismatchError("SafetyDecision does not match ExperimentSpecification")

    def _transition(self, new_state: LifecycleState):
        assert_valid_transition(self.run.state, new_state)
        self.run.state = new_state
        self.run.updated_at = datetime.now(timezone.utc).isoformat()
        
    def start_preflight(self):
        self._transition(LifecycleState.PREFLIGHT)
        
        self.run.preflight = run_preflight(self.run, self.spec, self.decision, self.app)
        
        if self.run.preflight.status == "passed":
            # Check if approval is actually required by the decision, and if conditions exist
            self._transition(LifecycleState.AUTHORIZATION_PENDING)
        else:
            self._transition(LifecycleState.FAILED)
            
    def grant_approval(self, approver: str):
        if self.run.state != LifecycleState.AUTHORIZATION_PENDING:
            raise InvalidStateTransitionError("Can only grant approval in AUTHORIZATION_PENDING state")
            
        self.run.approval.status = "approved"
        self.run.approval.approved_by = approver
        self.run.approval.approved_at = datetime.now(timezone.utc).isoformat()
        
    def reject_approval(self, approver: str):
        if self.run.state != LifecycleState.AUTHORIZATION_PENDING:
            raise InvalidStateTransitionError("Can only reject approval in AUTHORIZATION_PENDING state")
            
        self.run.approval.status = "rejected"
        self.run.approval.approved_by = approver
        self.run.approval.approved_at = datetime.now(timezone.utc).isoformat()
        self._transition(LifecycleState.FAILED)
        
    def satisfy_condition(self, condition_id: str, evidence: str):
        for cond in self.run.required_conditions:
            if cond.condition_id == condition_id:
                cond.status = "satisfied"
                cond.evidence = evidence
                cond.satisfied_at = datetime.now(timezone.utc).isoformat()
                return
        raise ValueError("Condition not found")
        
    def authorize(self):
        if self.run.state != LifecycleState.AUTHORIZATION_PENDING:
            raise InvalidStateTransitionError("Can only authorize in AUTHORIZATION_PENDING state")
            
        try:
            # Re-run preflight to catch any condition updates if necessary, or rely on existing preflight 
            # and authorization checks.
            # But wait, preflight might have passed BEFORE conditions were met, if we didn't strictly require it.
            # The prompt says preflight must validate required conditions.
            # So preflight MUST be re-run if conditions were pending?
            # Let's just strictly run authorize_run which checks everything.
            authorize_run(self.run, self.decision)
            self._transition(LifecycleState.AUTHORIZED)
        except AuthorizationError:
            raise AuthorizationError("Authorization conditions not met")
            
    def setup(self, adapter: Optional[ExecutionAdapter] = None):
        self._transition(LifecycleState.SETUP)
        if adapter:
            context = ExecutionContext(
                run=self.run, experiment=self.spec, safety_decision=self.decision,
                application_model=self.app, adapter_id=adapter.capabilities().adapter_id,
                correlation_id=self.run.run_id
            )
            adapter.prepare(context)
            
    def run_experiment(self, adapter: Optional[ExecutionAdapter] = None):
        self._transition(LifecycleState.RUNNING)
        self.run.started_at = datetime.now(timezone.utc).isoformat()
        if adapter:
            context = ExecutionContext(
                run=self.run, experiment=self.spec, safety_decision=self.decision,
                application_model=self.app, adapter_id=adapter.capabilities().adapter_id,
                correlation_id=self.run.run_id
            )
            adapter.execute(context)
            
    def observe(self, adapter: Optional[ExecutionAdapter] = None):
        self._transition(LifecycleState.OBSERVING)
        if adapter:
            context = ExecutionContext(
                run=self.run, experiment=self.spec, safety_decision=self.decision,
                application_model=self.app, adapter_id=adapter.capabilities().adapter_id,
                correlation_id=self.run.run_id
            )
            adapter.observe(context)
            
    def finish_observation(self):
        if self.run.state != LifecycleState.OBSERVING:
            raise InvalidStateTransitionError("Can only finish observation from OBSERVING state")
            
        if self.spec.safety.rollback_required:
            pass # Caller will invoke perform_rollback
        else:
            self._transition(LifecycleState.RECOVERY_CHECK)
            
    def request_abort(self, reason: str, source: str = "manual"):
        # Can only abort from RUNNING or OBSERVING
        if self.run.state not in (LifecycleState.RUNNING, LifecycleState.OBSERVING):
            raise InvalidStateTransitionError("Can only abort from RUNNING or OBSERVING")
            
        self.run.abort.requested = True
        self.run.abort.requested_at = datetime.now(timezone.utc).isoformat()
        self.run.abort.reason = reason
        self.run.abort.source = source
        self._transition(LifecycleState.ABORT_REQUESTED)
        
    def execute_abort(self, adapter: Optional[ExecutionAdapter] = None):
        if self.run.state != LifecycleState.ABORT_REQUESTED:
            raise InvalidStateTransitionError("Must request abort first")
            
        if adapter:
            context = ExecutionContext(
                run=self.run, experiment=self.spec, safety_decision=self.decision,
                application_model=self.app, adapter_id=adapter.capabilities().adapter_id,
                correlation_id=self.run.run_id
            )
            adapter.abort(context)
            
        # If rollback is required, we go to rollback, otherwise aborted
        if self.spec.safety.rollback_required:
            self._transition(LifecycleState.ROLLBACK)
        else:
            self._transition(LifecycleState.ABORTED)
            # wait, prompt says ABORTED -> ROLLBACK. Let's just go to ABORTED. Then caller can invoke rollback.
            # "ABORT_REQUESTED -> ABORTED"
            # "ABORT_REQUESTED -> ROLLBACK"
            
    def perform_rollback(self, adapter: Optional[ExecutionAdapter] = None):
        # Can be called from OBSERVING, ABORT_REQUESTED, ABORTED
        if self.run.state not in (LifecycleState.OBSERVING, LifecycleState.ABORT_REQUESTED, LifecycleState.ABORTED):
            raise InvalidStateTransitionError("Cannot rollback from current state")
            
        self._transition(LifecycleState.ROLLBACK)
        self.run.rollback.status = "running"
        self.run.rollback.started_at = datetime.now(timezone.utc).isoformat()
        
        try:
            if adapter:
                context = ExecutionContext(
                    run=self.run, experiment=self.spec, safety_decision=self.decision,
                    application_model=self.app, adapter_id=adapter.capabilities().adapter_id,
                    correlation_id=self.run.run_id
                )
                adapter.rollback(context)
            self.run.rollback.status = "completed"
            self.run.rollback.completed_at = datetime.now(timezone.utc).isoformat()
            self._transition(LifecycleState.RECOVERY_CHECK)
        except Exception as e:
            self.run.rollback.status = "failed"
            self.run.rollback.error = str(e)
            self._transition(LifecycleState.ROLLBACK_FAILED)
            
    def verify_recovery(self, adapter: Optional[ExecutionAdapter] = None, require_adapter: bool = True):
        if self.run.state != LifecycleState.RECOVERY_CHECK:
            raise InvalidStateTransitionError("Cannot verify recovery from current state. Must be in RECOVERY_CHECK.")
        self.run.recovery.status = "running"
        self.run.recovery.started_at = datetime.now(timezone.utc).isoformat()
        
        try:
            if not adapter:
                raise ValueError("Execution adapter is required for recovery verification; cannot declare success without evidence.")

            context = ExecutionContext(
                run=self.run, experiment=self.spec, safety_decision=self.decision,
                application_model=self.app, adapter_id=adapter.capabilities().adapter_id,
                correlation_id=self.run.run_id
            )
            from .recovery import RecoveryResultVariant
            recovery_result = adapter.verify_recovery(context)
            recovery_result.validate_for_run(self.run.run_id)
            
            if recovery_result.variant == RecoveryResultVariant.INCONCLUSIVE:
                self.run.recovery.status = "inconclusive"
                self.run.recovery.completed_at = datetime.now(timezone.utc).isoformat()
                return
            elif recovery_result.variant == RecoveryResultVariant.CONFIRMED_SUCCESS:
                self.run.recovery.status = "passed"
                self.run.recovery.completed_at = datetime.now(timezone.utc).isoformat()
                self._transition(LifecycleState.COMPLETED)
                self.run.completed_at = datetime.now(timezone.utc).isoformat()
            elif recovery_result.variant == RecoveryResultVariant.CONFIRMED_FAILURE:
                self.run.recovery.status = "passed"
                self.run.recovery.completed_at = datetime.now(timezone.utc).isoformat()
                self._transition(LifecycleState.FAILED)
            elif recovery_result.variant == RecoveryResultVariant.CONFIRMED_ROLLBACK:
                self.run.recovery.status = "passed"
                self.run.recovery.completed_at = datetime.now(timezone.utc).isoformat()
                self._transition(LifecycleState.ABORTED)
        except Exception as e:
            self.run.recovery.status = "failed"
            self.run.recovery.error = str(e)
            self._transition(LifecycleState.RECOVERY_FAILED)
            
    def fail(self, error_type: str, message: str):
        allowed_states = {
            LifecycleState.PREFLIGHT, LifecycleState.AUTHORIZATION_PENDING,
            LifecycleState.SETUP, LifecycleState.RUNNING, LifecycleState.OBSERVING
        }
        if self.run.state not in allowed_states:
            raise InvalidStateTransitionError("Cannot fail from current state")
            
        from ..models.experiment_run import ErrorModel
        self.run.error = ErrorModel(type=error_type, message=message)
        self._transition(LifecycleState.FAILED)

def create_experiment_run(spec: ExperimentSpecification, decision: SafetyDecision) -> ExperimentRun:
    # Deterministic run ID
    hash_obj = hashlib.md5(f"{spec.experiment_id}:{decision.decision_id}".encode('utf-8'))
    run_id = f"run-{hash_obj.hexdigest()[:8]}"
    
    # Required conditions setup
    req_conds = []
    for cond_msg in decision.required_conditions:
        req_conds.append(RequiredConditionModel(
            condition_id=str(uuid.uuid4()),
            description=cond_msg
        ))
        
    approval = ApprovalModel(
        required=decision.decision == "requires_approval" or len(decision.required_approvals) > 0,
        status="pending" if (decision.decision == "requires_approval" or len(decision.required_approvals) > 0) else "not_required"
    )
    
    return ExperimentRun(
        run_id=run_id,
        experiment_id=spec.experiment_id,
        application_id=spec.application_id,
        safety_decision_id=decision.decision_id,
        required_conditions=req_conds,
        approval=approval,
        rollback=RollbackRunModel(required=spec.safety.rollback_required),
        recovery=RecoveryModel(required=spec.safety.rollback_required) # usually they go hand in hand
    )
