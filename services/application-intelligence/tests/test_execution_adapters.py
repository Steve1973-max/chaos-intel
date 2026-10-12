import pytest
import subprocess
import urllib.request
from src.models.experiment import ExperimentSpecification, Target, Fault, BlastRadius, SteadyState, Rollback, Safety, AbortCondition
from src.models.safety import SafetyDecision
from src.models.application import ApplicationModel
from src.models.architecture import ArchitectureGraph, GraphNode
from src.execution.lifecycle import create_experiment_run
from src.execution.states import LifecycleState
from src.execution.adapters.registry import AdapterRegistry
from src.execution.adapters.dry_run import DryRunAdapter
from src.execution.router import AdapterRouter
from src.execution.adapters.errors import *
from src.execution.authorization import AuthorizationError
from src.execution.adapters.context import ExecutionContext

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
        abort_conditions=[],
        rollback=Rollback(strategy="restore", automatic=True, verification_required=True),
        safety=Safety(requires_approval=False, rollback_required=True, reversible=True, production_allowed=False)
    )

def mock_decision():
    return SafetyDecision(
        decision_id="dec-1", experiment_id="exp-1", application_id="app-1",
        decision="approved", allowed=True
    )

def get_authorized_run():
    spec = mock_spec()
    dec = mock_decision()
    app = mock_app()
    run = create_experiment_run(spec, dec)
    from src.execution.lifecycle import LifecycleController
    ctrl = LifecycleController(run, spec, dec, app)
    ctrl.start_preflight()
    ctrl.authorize()
    return spec, dec, app, run

def test_adapter_registration():
    reg = AdapterRegistry()
    adapter = DryRunAdapter()
    reg.register(adapter)
    assert reg.get(adapter.capabilities().adapter_id) == adapter
    
    with pytest.raises(ValueError):
        reg.register(adapter) # Duplicate rejection

def test_deterministic_adapter_resolution():
    reg = AdapterRegistry()
    reg.register(DryRunAdapter())
    
    adapter = reg.resolve("availability", "service")
    assert adapter.capabilities().adapter_id == "dry-run-adapter"

def test_unsupported_fault_detection():
    reg = AdapterRegistry()
    reg.register(DryRunAdapter())
    
    with pytest.raises(AdapterResolutionError):
        reg.resolve("unknown_fault", "service")

def test_unsupported_target_detection():
    reg = AdapterRegistry()
    reg.register(DryRunAdapter())
    
    with pytest.raises(AdapterResolutionError):
        reg.resolve("availability", "unknown_target")

def test_live_mode_rejection():
    spec, dec, app, run = get_authorized_run()
    reg = AdapterRegistry()
    reg.register(DryRunAdapter())
    router = AdapterRouter(reg)
    
    with pytest.raises(LiveExecutionUnavailableError):
        router.route(spec, run, dec, app, mode="live")

def test_invalid_duration():
    spec, dec, app, run = get_authorized_run()
    spec.duration_seconds = -1
    reg = AdapterRegistry()
    reg.register(DryRunAdapter())
    router = AdapterRouter(reg)
    
    with pytest.raises(InvalidParameterError):
        router.route(spec, run, dec, app)

def test_invalid_target():
    spec, dec, app, run = get_authorized_run()
    spec.target.id = ""
    reg = AdapterRegistry()
    reg.register(DryRunAdapter())
    router = AdapterRouter(reg)
    
    with pytest.raises(InvalidParameterError):
        router.route(spec, run, dec, app)

def test_safety_gate_enforcement():
    spec, dec, app, run = get_authorized_run()
    # Modify run to not be preflight passed
    run.preflight.status = "failed"
    
    reg = AdapterRegistry()
    reg.register(DryRunAdapter())
    router = AdapterRouter(reg)
    
    with pytest.raises(AuthorizationError):
        router.route(spec, run, dec, app)

def test_dry_run_plan_generation():
    spec, dec, app, run = get_authorized_run()
    reg = AdapterRegistry()
    reg.register(DryRunAdapter())
    router = AdapterRouter(reg)
    
    adapter, plan = router.route(spec, run, dec, app)
    assert plan.mode == "dry_run"
    assert plan.adapter_id == "dry-run-adapter"
    assert len(plan.steps) > 0
    assert any(s.action == "rollback" for s in plan.steps)
    
def test_dry_run_result():
    spec, dec, app, run = get_authorized_run()
    adapter = DryRunAdapter()
    
    ctx = ExecutionContext(
        run=run, experiment=spec, safety_decision=dec, application_model=app,
        adapter_id="dry-run-adapter", correlation_id="123"
    )
    
    res = adapter.execute(ctx)
    assert res.mode == "dry_run"
    assert res.status == "executed"
    assert res.metadata.get("simulated") is True

def test_explicit_no_side_effects_adapters():
    called = []
    def fake_run(*args, **kwargs): called.append("subprocess")
    def fake_urlopen(*args, **kwargs): called.append("network")
    
    orig_run = subprocess.run
    orig_urlopen = urllib.request.urlopen
    
    subprocess.run = fake_run
    urllib.request.urlopen = fake_urlopen
    
    try:
        spec, dec, app, run = get_authorized_run()
        reg = AdapterRegistry()
        reg.register(DryRunAdapter())
        router = AdapterRouter(reg)
        
        adapter, plan = router.route(spec, run, dec, app)
        
        ctx = ExecutionContext(
            run=run, experiment=spec, safety_decision=dec, application_model=app,
            adapter_id=adapter.capabilities().adapter_id, correlation_id="123"
        )
        
        adapter.prepare(ctx)
        adapter.execute(ctx)
        adapter.observe(ctx)
        adapter.rollback(ctx)
        adapter.verify_recovery(ctx)
        adapter.cleanup(ctx)
        
        assert len(called) == 0
    finally:
        subprocess.run = orig_run
        urllib.request.urlopen = orig_urlopen
