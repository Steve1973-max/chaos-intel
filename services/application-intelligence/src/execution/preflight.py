from datetime import datetime, timezone
import uuid
from ..models.experiment import ExperimentSpecification
from ..models.safety import SafetyDecision
from ..models.application import ApplicationModel
from ..models.experiment_run import ExperimentRun, PreflightModel, PreflightCheck

def run_preflight(run: ExperimentRun, spec: ExperimentSpecification, decision: SafetyDecision, app: ApplicationModel) -> PreflightModel:
    checks = []
    
    # Matches
    if decision.experiment_id != spec.experiment_id:
        checks.append(PreflightCheck(check_id=str(uuid.uuid4()), status="failed", message="Safety decision experiment_id mismatch."))
    else:
        checks.append(PreflightCheck(check_id=str(uuid.uuid4()), status="passed", message="Experiment ID matches."))
        
    if decision.application_id != app.application_id or spec.application_id != app.application_id:
        checks.append(PreflightCheck(check_id=str(uuid.uuid4()), status="failed", message="Application ID mismatch."))
    else:
        checks.append(PreflightCheck(check_id=str(uuid.uuid4()), status="passed", message="Application ID matches."))
        
    # Safety
    if decision.decision == "blocked":
        checks.append(PreflightCheck(check_id=str(uuid.uuid4()), status="failed", message="Safety decision is blocked."))
    elif decision.decision == "requires_configuration":
        checks.append(PreflightCheck(check_id=str(uuid.uuid4()), status="failed", message="Safety decision is requires_configuration. A new decision must be generated."))
    else:
        checks.append(PreflightCheck(check_id=str(uuid.uuid4()), status="passed", message=f"Safety decision is {decision.decision}."))
        
    if len(decision.blockers) > 0:
        checks.append(PreflightCheck(check_id=str(uuid.uuid4()), status="failed", message="Safety decision contains blockers."))
    else:
        checks.append(PreflightCheck(check_id=str(uuid.uuid4()), status="passed", message="No blockers present."))
        
    # Conditions and Approvals are evaluated at AUTHORIZATION gate.
    # Preflight only checks structural validity.
    
    # Target existence
    target_exists = False
    ambiguous = False
    found_count = 0
    
    if spec.target.type == "unknown":
        target_exists = False
    else:
        for node in app.architecture.nodes:
            if node.node_id == spec.target.id or node.name == spec.target.id:
                found_count += 1
        for dep in app.dependencies:
            if dep.name == spec.target.id or dep.target_service_id == spec.target.id:
                found_count += 1
        for srv in app.services:
            if srv.name == spec.target.id or srv.service_id == spec.target.id:
                found_count += 1
        for api in app.apis:
            if api.api_id == spec.target.id or api.name == spec.target.id:
                found_count += 1
                
        if found_count == 1:
            target_exists = True
        elif found_count > 1:
            target_exists = True
            ambiguous = True

    if not target_exists:
        checks.append(PreflightCheck(check_id=str(uuid.uuid4()), status="failed", message=f"Target {spec.target.id} not found or is unknown."))
    elif ambiguous:
        checks.append(PreflightCheck(check_id=str(uuid.uuid4()), status="failed", message=f"Target {spec.target.id} is ambiguous."))
    else:
        checks.append(PreflightCheck(check_id=str(uuid.uuid4()), status="passed", message="Target uniquely found in application model."))
        
    # Duration
    if spec.duration_seconds is None or spec.duration_seconds <= 0:
        checks.append(PreflightCheck(check_id=str(uuid.uuid4()), status="failed", message="Experiment duration is invalid."))
    else:
        checks.append(PreflightCheck(check_id=str(uuid.uuid4()), status="passed", message="Experiment duration is valid."))
        
    return PreflightModel(
        status="passed" if all(c.status == "passed" for c in checks) else "failed",
        checks=checks,
        evaluated_at=datetime.now(timezone.utc).isoformat(),
        errors=[c.message for c in checks if c.status == "failed"]
    )
