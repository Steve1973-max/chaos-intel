import uuid
from .adapters.plan import ExecutionPlan, PlanStep
from .adapters.capabilities import AdapterCapabilities
from ..models.experiment import ExperimentSpecification
from ..models.experiment_run import ExperimentRun
from ..models.safety import SafetyDecision

def generate_execution_plan(spec: ExperimentSpecification, run: ExperimentRun, decision: SafetyDecision, adapter_caps: AdapterCapabilities, mode: str) -> ExecutionPlan:
    plan_id = f"plan-{uuid.uuid4().hex[:8]}"
    
    steps = [
        PlanStep(step_id=str(uuid.uuid4()), name="Prepare", order=1, action="prepare"),
        PlanStep(step_id=str(uuid.uuid4()), name="Execute", order=2, action="execute"),
        PlanStep(step_id=str(uuid.uuid4()), name="Observe", order=3, action="observe"),
    ]
    
    order = 4
    if spec.safety.rollback_required:
        steps.append(PlanStep(step_id=str(uuid.uuid4()), name="Rollback", order=order, action="rollback"))
        order += 1
        
    steps.append(PlanStep(step_id=str(uuid.uuid4()), name="Verify Recovery", order=order, action="verify_recovery"))
    order += 1
    steps.append(PlanStep(step_id=str(uuid.uuid4()), name="Cleanup", order=order, action="cleanup"))
    
    return ExecutionPlan(
        plan_id=plan_id,
        run_id=run.run_id,
        experiment_id=spec.experiment_id,
        application_id=spec.application_id,
        adapter_id=adapter_caps.adapter_id,
        adapter_version=adapter_caps.version,
        fault_type=spec.fault.type,
        target_type=spec.target.type,
        target_id=spec.target.id,
        parameters={"duration_seconds": spec.duration_seconds},
        required_capabilities=adapter_caps.required_capabilities,
        safety_decision_id=decision.decision_id,
        mode=mode,
        steps=steps
    )
