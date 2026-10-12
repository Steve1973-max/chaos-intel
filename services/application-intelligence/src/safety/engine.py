import hashlib
from typing import List
from ..models.application import ApplicationModel
from ..models.experiment import ExperimentSpecification
from ..models.safety import SafetyDecision, SafetyCheck
from .policy import PolicyConstants
from .rules import (
    EnvironmentRule, ApprovalRule, BlastRadiusRule,
    RollbackRule, SteadyStateRule, AbortConditionsRule,
    TargetRule, FaultRule, DurationRule, CapabilitiesRule
)

def evaluate_experiment_safety(app_id: str, experiment: ExperimentSpecification) -> SafetyDecision:
    rules = [
        EnvironmentRule(), ApprovalRule(), BlastRadiusRule(),
        RollbackRule(), SteadyStateRule(), AbortConditionsRule(),
        TargetRule(), FaultRule(), DurationRule(), CapabilitiesRule()
    ]
    
    checks = []
    blockers = []
    warnings = []
    required_conditions = []
    required_approvals = []
    
    # 1. Run all checks
    for rule in rules:
        rule_checks = rule.evaluate(experiment)
        for check in rule_checks:
            checks.append(check)
            if check.status == "fail":
                blockers.append(check.message)
            elif check.status == "warning":
                warnings.append(check.message)
                if check.category == "approval":
                    required_approvals.append(check.message)
            elif check.status == "requires_configuration":
                required_conditions.append(check.message)
                
    # 2. Determine Precedence
    if len(blockers) > 0:
        decision = "blocked"
        allowed = False
    elif len(required_conditions) > 0:
        decision = "requires_configuration"
        allowed = False
    elif len(required_approvals) > 0:
        decision = "requires_approval"
        allowed = False
    else:
        decision = "approved"
        allowed = True
        
    # Generate ID
    hash_obj = hashlib.md5(f"{app_id}:{experiment.experiment_id}:{PolicyConstants.POLICY_VERSION}".encode('utf-8'))
    decision_id = f"dec-{hash_obj.hexdigest()[:8]}"
    
    return SafetyDecision(
        decision_id=decision_id,
        experiment_id=experiment.experiment_id,
        application_id=app_id,
        decision=decision,
        allowed=allowed,
        checks=checks,
        blockers=blockers,
        warnings=warnings,
        required_approvals=required_approvals,
        required_conditions=required_conditions,
        policy_version=PolicyConstants.POLICY_VERSION
    )

def generate_safety_decisions(app: ApplicationModel) -> List[SafetyDecision]:
    decisions = []
    for exp in app.experiments:
        decisions.append(evaluate_experiment_safety(app.application_id, exp))
    return decisions
