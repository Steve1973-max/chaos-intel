from ..models.experiment import BlastRadius, SteadyState, AbortCondition, Rollback, Safety

def get_default_blast_radius(scope="single_service", max_affected=1) -> BlastRadius:
    return BlastRadius(scope=scope, max_affected_components=max_affected)

def get_default_steady_state() -> SteadyState:
    return SteadyState(
        required=True,
        checks=["baseline_request_success_rate", "baseline_p95_latency", "target_health"]
    )

def get_default_abort_conditions() -> list[AbortCondition]:
    return [
        AbortCondition(metric="error_rate", operator=">", threshold=None, action="abort", requires_configuration=True),
        AbortCondition(metric="service_health", operator="==", threshold="critical", action="abort", requires_configuration=False)
    ]

def get_default_rollback() -> Rollback:
    return Rollback(strategy="restore_target", automatic=True, verification_required=True)

def get_default_safety() -> Safety:
    return Safety(
        requires_approval=True,
        environment_required=None,
        reversible=True,
        rollback_required=True,
        production_allowed=False
    )
