from ..models.experiment_run import ExperimentRun
from ..models.safety import SafetyDecision
from .errors import AuthorizationError

def authorize_run(run: ExperimentRun, decision: SafetyDecision):
    """
    Authorization must consume PreflightResult and SafetyDecision.
    Only if every required condition passes may the lifecycle transition AUTHORIZATION_PENDING -> AUTHORIZED.
    """
    if run.preflight.status != "passed":
        raise AuthorizationError("Preflight has not passed. Cannot authorize.")
        
    if decision.decision == "blocked":
        raise AuthorizationError("SafetyDecision is blocked.")
        
    if decision.decision == "requires_configuration":
        raise AuthorizationError("SafetyDecision is requires_configuration. A new decision is required.")
        
    if len(decision.blockers) > 0:
        raise AuthorizationError("SafetyDecision contains blockers.")
        
    if decision.decision == "requires_approval" and run.approval.status != "approved":
        raise AuthorizationError("SafetyDecision requires approval but run approval is not approved.")
        
    if run.approval.required and run.approval.status != "approved":
        raise AuthorizationError("Run Approval required but not granted.")
        
    unsatisfied = [c for c in run.required_conditions if c.status != "satisfied"]
    if len(unsatisfied) > 0:
        raise AuthorizationError("Required conditions not satisfied.")
