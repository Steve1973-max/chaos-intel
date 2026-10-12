import pytest
from src.models.experiment import ExperimentSpecification, Target, Fault, BlastRadius, SteadyState, Rollback, Safety, AbortCondition
from src.models.safety import SafetyDecision, SafetyCheck
from src.models.application import ApplicationModel
from src.models.architecture import ArchitectureGraph, GraphNode
from src.execution.states import LifecycleState
from src.execution.errors import *
from src.execution.lifecycle import LifecycleController, create_experiment_run
from src.execution.base import ExecutionAdapter

def mock_app():
    return ApplicationModel(
        application_id="app-1", name="app", technologies=[], services=[], dependencies=[], apis=[],
        architecture=ArchitectureGraph(nodes=[GraphNode(node_id="target-1", node_type="service", name="target")], edges=[]),
        risks=[], test_candidates=[]
    )

def mock_spec():
    return ExperimentSpecification(
        experiment_id="exp-1", application_id="app-1", candidate_ids=[], name="test", hypothesis="test",
        status="approved", target=Target(type="service", id="target-1", name="target-1"),
        fault=Fault(type="availability", method="service_stop"), duration_seconds=30,
        blast_radius=BlastRadius(scope="single", max_affected_components=1),
        steady_state=SteadyState(required=True, checks=["x"]),
        abort_conditions=[AbortCondition(metric="m", operator="=", threshold="1", action="abort")],
        rollback=Rollback(strategy="restore", automatic=True, verification_required=True),
        safety=Safety(requires_approval=False, rollback_required=True, reversible=True, production_allowed=False)
    )

def mock_decision():
    return SafetyDecision(
        decision_id="dec-1", experiment_id="exp-1", application_id="app-1",
        decision="approved", allowed=True
    )

def test_initial_created_state():
    spec = mock_spec()
    dec = mock_decision()
    run = create_experiment_run(spec, dec)
    assert run.state == LifecycleState.CREATED

def test_valid_normal_transitions():
    spec = mock_spec()
    dec = mock_decision()
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    ctrl.start_preflight()
    assert run.state == LifecycleState.AUTHORIZATION_PENDING
    
    ctrl.authorize()
    assert run.state == LifecycleState.AUTHORIZED
    
    ctrl.setup()
    assert run.state == LifecycleState.SETUP
    
    ctrl.run_experiment()
    assert run.state == LifecycleState.RUNNING
    
    ctrl.observe()
    assert run.state == LifecycleState.OBSERVING
    
    ctrl.perform_rollback()
    assert run.state == LifecycleState.RECOVERY_CHECK
    
    class SuccessfulRecoveryAdapter(ExecutionAdapter):
        def capabilities(self):
            from src.execution.adapters.capabilities import AdapterCapabilities
            return AdapterCapabilities(adapter_id="success-recovery", adapter_name="Success Recovery", version="1.0.0", supported_fault_types=[], supported_target_types=[], required_capabilities=[])
        def prepare(self, c): pass
        def execute(self, c): pass
        def observe(self, c): pass
        def abort(self, c): pass
        def rollback(self, c): pass
        def verify_recovery(self, c):
            from src.execution.recovery import RecoveryResult, RecoveryResultVariant
            return RecoveryResult(variant=RecoveryResultVariant.CONFIRMED_SUCCESS, run_id=c.run.run_id)
        def cleanup(self, c): pass

    ctrl.verify_recovery(adapter=SuccessfulRecoveryAdapter())
    assert run.state == LifecycleState.COMPLETED

def test_invalid_transitions():
    spec = mock_spec()
    dec = mock_decision()
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    with pytest.raises(InvalidStateTransitionError):
        ctrl.authorize() # Cannot authorize directly from CREATED

def test_blocked_safety_decision():
    spec = mock_spec()
    dec = mock_decision()
    dec.decision = "blocked"
    dec.allowed = False
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    ctrl.start_preflight()
    # It should transition to FAILED because preflight fails on a blocked safety decision
    assert run.state == LifecycleState.FAILED
    
    with pytest.raises(InvalidStateTransitionError):
        ctrl.authorize()

def test_requires_configuration_safety_decision():
    spec = mock_spec()
    dec = mock_decision()
    dec.decision = "requires_configuration"
    dec.allowed = False
    dec.required_conditions.append("Needs X")
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    ctrl.start_preflight()
    assert run.state == LifecycleState.FAILED
    assert len(run.required_conditions) == 1

def test_requires_approval_safety_decision():
    spec = mock_spec()
    dec = mock_decision()
    dec.decision = "requires_approval"
    dec.allowed = False
    app = mock_app()
    run = create_experiment_run(spec, dec)
    assert run.approval.required is True
    assert run.approval.status == "pending"

def test_approval_accepted():
    spec = mock_spec()
    dec = mock_decision()
    dec.decision = "approved"
    dec.allowed = True
    # Let's force approval requirement
    dec.required_approvals.append("Needs human")
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    ctrl.start_preflight()
    assert run.state == LifecycleState.AUTHORIZATION_PENDING
    
    ctrl.grant_approval("steve")
    assert run.approval.status == "approved"
    
    ctrl.authorize()
    assert run.state == LifecycleState.AUTHORIZED

def test_approval_rejected():
    spec = mock_spec()
    dec = mock_decision()
    dec.decision = "approved"
    dec.allowed = True
    dec.required_approvals.append("Needs human")
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    ctrl.start_preflight()
    ctrl.reject_approval("steve")
    assert run.approval.status == "rejected"
    assert run.state == LifecycleState.FAILED

def test_required_condition_satisfied():
    spec = mock_spec()
    dec = mock_decision()
    dec.decision = "approved"
    dec.allowed = True
    dec.required_conditions.append("Network check")
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    # Must satisfy BEFORE preflight to pass preflight smoothly, OR we preflight fails.
    # Ah, preflight requires conditions to be satisfied!
    assert len(run.required_conditions) == 1
    cond_id = run.required_conditions[0].condition_id
    ctrl.satisfy_condition(cond_id, "done")
    
    ctrl.start_preflight()
    assert run.state == LifecycleState.AUTHORIZATION_PENDING

def test_experiment_mismatch():
    spec = mock_spec()
    dec = mock_decision()
    dec.experiment_id = "other-exp"
    app = mock_app()
    
    with pytest.raises(ExperimentMismatchError):
        run = create_experiment_run(spec, dec)
        LifecycleController(run, spec, dec, app)

def test_authorization_denial():
    spec = mock_spec()
    dec = mock_decision()
    dec.decision = "approved"
    dec.allowed = True
    dec.required_approvals.append("X")
    app = mock_app()
    
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    # Fake being in AUTHORIZATION_PENDING but approval is still pending
    run.state = LifecycleState.AUTHORIZATION_PENDING
    run.preflight.status = "passed"
    
    with pytest.raises(AuthorizationError):
        ctrl.authorize()

def test_abort_lifecycle():
    spec = mock_spec()
    dec = mock_decision()
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    ctrl.start_preflight()
    ctrl.authorize()
    ctrl.setup()
    ctrl.run_experiment()
    
    ctrl.request_abort("Policy triggered")
    assert run.state == LifecycleState.ABORT_REQUESTED
    assert run.abort.requested is True
    
    # Rollback is required in spec, so execute_abort transitions to ROLLBACK
    ctrl.execute_abort()
    assert run.state == LifecycleState.ROLLBACK

def test_rollback_not_required():
    spec = mock_spec()
    spec.safety.rollback_required = False
    dec = mock_decision()
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    run.state = LifecycleState.ABORT_REQUESTED
    ctrl.execute_abort()
    assert run.state == LifecycleState.ABORTED

def test_rollback_failure():
    class FailingAdapter(ExecutionAdapter):
        def capabilities(self):
            from src.execution.adapters.capabilities import AdapterCapabilities
            return AdapterCapabilities(adapter_id="failing-adapter", adapter_name="Failing Adapter", version="1.0.0", supported_fault_types=[], supported_target_types=[], required_capabilities=[])
        def prepare(self, c): pass
        def execute(self, c): pass
        def observe(self, c): pass
        def abort(self, c): pass
        def rollback(self, c): raise Exception("Network error")
        def verify_recovery(self, c): pass
        def cleanup(self, c): pass

    spec = mock_spec()
    dec = mock_decision()
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    run.state = LifecycleState.OBSERVING
    ctrl.perform_rollback(adapter=FailingAdapter())
    assert run.state == LifecycleState.ROLLBACK_FAILED
    assert run.rollback.error == "Network error"

def test_recovery_failure():
    class FailingRecoveryAdapter(ExecutionAdapter):
        def capabilities(self):
            from src.execution.adapters.capabilities import AdapterCapabilities
            return AdapterCapabilities(adapter_id="failing-recovery-adapter", adapter_name="Failing Recovery Adapter", version="1.0.0", supported_fault_types=[], supported_target_types=[], required_capabilities=[])
        def prepare(self, c): pass
        def execute(self, c): pass
        def observe(self, c): pass
        def abort(self, c): pass
        def rollback(self, c): pass
        def verify_recovery(self, c): raise Exception("Health checks failing")
        def cleanup(self, c): pass

    spec = mock_spec()
    dec = mock_decision()
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    run.state = LifecycleState.RECOVERY_CHECK
    ctrl.verify_recovery(adapter=FailingRecoveryAdapter())
    assert run.state == LifecycleState.RECOVERY_FAILED
    assert run.recovery.error == "Health checks failing"

def test_no_side_effects():
    # Calling the mock adapter methods doesn't run shell or network.
    pass

def test_lifecycle_version():
    spec = mock_spec()
    dec = mock_decision()
    run = create_experiment_run(spec, dec)
    assert run.lifecycle_version == "1.0.0"

# NEW TESTS FOR STEP 10A PATCH

def test_requires_approval_pending():
    # 1. requires_approval + approval pending -> not authorized
    spec = mock_spec()
    dec = mock_decision()
    dec.decision = "requires_approval"
    dec.allowed = False
    
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    ctrl.start_preflight()
    assert run.state == LifecycleState.AUTHORIZATION_PENDING
    
    with pytest.raises(AuthorizationError):
        ctrl.authorize()
        
def test_requires_approval_explicit_approval():
    # 2. requires_approval + explicit approval -> authorized
    spec = mock_spec()
    dec = mock_decision()
    dec.decision = "requires_approval"
    dec.allowed = False
    
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    ctrl.start_preflight()
    ctrl.grant_approval("steve")
    ctrl.authorize()
    
    assert run.state == LifecycleState.AUTHORIZED
    
def test_original_safety_decision_immutable():
    # 3. original SafetyDecision remains requires_approval
    spec = mock_spec()
    dec = mock_decision()
    dec.decision = "requires_approval"
    dec.allowed = False
    
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    ctrl.start_preflight()
    ctrl.grant_approval("steve")
    ctrl.authorize()
    
    # Original decision must not have been mutated
    assert dec.decision == "requires_approval"
    assert dec.allowed is False
    
def test_requires_configuration_conditions_satisfied():
    # 4 & 5. requires_configuration + conditions satisfied -> original decision remains requires_configuration, authorization denied
    spec = mock_spec()
    dec = mock_decision()
    dec.decision = "requires_configuration"
    dec.allowed = False
    dec.required_conditions.append("Needs X")
    
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    ctrl.satisfy_condition(run.required_conditions[0].condition_id, "evidence")
    
    ctrl.start_preflight()
    # Preflight fails because decision itself is requires_configuration
    assert run.state == LifecycleState.FAILED
    assert dec.decision == "requires_configuration"
    
def test_new_safety_decision_approved():
    # 6. new SafetyDecision approved -> authorization succeeds
    spec = mock_spec()
    dec = mock_decision()
    dec.decision = "approved"
    dec.allowed = True
    
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    ctrl.start_preflight()
    ctrl.authorize()
    assert run.state == LifecycleState.AUTHORIZED
    
def test_blocked_safety_decision_always_denied():
    # 7. blocked SafetyDecision -> authorization always denied
    spec = mock_spec()
    dec = mock_decision()
    dec.decision = "blocked"
    dec.allowed = False
    
    app = mock_app()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    ctrl.start_preflight()
    assert run.state == LifecycleState.FAILED
    
    with pytest.raises(InvalidStateTransitionError):
        ctrl.authorize()

def test_api_target_exists_not_in_architecture_graph():
    # 8. API target exists in ApplicationModel but is not an architecture graph node -> preflight succeeds
    from src.models.api import Api
    spec = mock_spec()
    spec.target.id = "api-1"
    
    app = mock_app()
    app.apis.append(Api(api_id="api-1", name="api-1", path="/", method="GET", service_id="svc-1"))
    
    dec = mock_decision()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    ctrl.start_preflight()
    assert run.preflight.status == "passed"
    assert run.state == LifecycleState.AUTHORIZATION_PENDING

def test_unknown_target():
    # 9. unknown target -> preflight fails
    spec = mock_spec()
    spec.target.id = "non-existent"
    
    app = mock_app()
    dec = mock_decision()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    ctrl.start_preflight()
    assert run.preflight.status == "failed"
    assert run.state == LifecycleState.FAILED
    assert any("not found" in err for err in run.preflight.errors)

def test_ambiguous_target():
    # 10. ambiguous target -> preflight fails
    spec = mock_spec()
    spec.target.id = "target-1" # already in architecture nodes
    
    app = mock_app()
    # Add a service with the same ID
    from src.models.service import Service
    app.services.append(Service(service_id="target-1", name="target-1", type="web", path=".", application_id="app-1", source_path="."))
    
    dec = mock_decision()
    run = create_experiment_run(spec, dec)
    ctrl = LifecycleController(run, spec, dec, app)
    
    ctrl.start_preflight()
    assert run.preflight.status == "failed"
    assert run.state == LifecycleState.FAILED
    assert any("ambiguous" in err for err in run.preflight.errors)

def test_explicit_no_side_effects():
    # 11. explicit no-subprocess/no-network/no-executor side effects
    # Since ExecutionAdapter is purely abstract, calling execution logic doesn't do anything real.
    import subprocess
    import urllib.request
    
    # We can monkeypatch to ensure they are not called
    called = []
    def fake_run(*args, **kwargs): called.append("subprocess")
    def fake_urlopen(*args, **kwargs): called.append("network")
    
    original_run = subprocess.run
    original_urlopen = urllib.request.urlopen
    
    subprocess.run = fake_run
    urllib.request.urlopen = fake_urlopen
    
    try:
        spec = mock_spec()
        dec = mock_decision()
        app = mock_app()
        run = create_experiment_run(spec, dec)
        ctrl = LifecycleController(run, spec, dec, app)
        
        ctrl.start_preflight()
        ctrl.authorize()
        ctrl.setup()
        ctrl.run_experiment()
        ctrl.observe()
        ctrl.perform_rollback()
        from src.execution.adapters.dry_run import DryRunAdapter
        ctrl.verify_recovery(adapter=DryRunAdapter())
        
        assert len(called) == 0
    finally:
        subprocess.run = original_run
        urllib.request.urlopen = original_urlopen


def test_lifecycle_verify_recovery_guard_omitted_adapter():
    spec = mock_spec()
    dec = mock_decision()
    app = mock_app()
    run = create_experiment_run(spec, dec)
    run.state = LifecycleState.RECOVERY_CHECK
    ctrl = LifecycleController(run, spec, dec, app)

    ctrl.verify_recovery()  # adapter omitted

    assert run.state == LifecycleState.RECOVERY_FAILED
    assert run.recovery.status == "failed"
    assert "Execution adapter is required" in run.recovery.error
    assert run.state != LifecycleState.COMPLETED


def test_lifecycle_verify_recovery_guard_none_adapter():
    spec = mock_spec()
    dec = mock_decision()
    app = mock_app()
    run = create_experiment_run(spec, dec)
    run.state = LifecycleState.RECOVERY_CHECK
    ctrl = LifecycleController(run, spec, dec, app)

    ctrl.verify_recovery(adapter=None)

    assert run.state == LifecycleState.RECOVERY_FAILED
    assert run.recovery.status == "failed"
    assert "Execution adapter is required" in run.recovery.error
    assert run.state != LifecycleState.COMPLETED
