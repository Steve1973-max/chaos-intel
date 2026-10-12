import pytest
from src.models.application import ApplicationModel
from src.models.experiment import ExperimentSpecification, Fault, Target, Safety, BlastRadius, SteadyState, Rollback
from src.models.safety import SafetyDecision
from src.models.experiment_run import ExperimentRun, ApprovalModel
from src.execution.orchestration_models import OrchestrationRequest
from src.execution.orchestrator import OrchestrationController
from src.execution.lifecycle import create_experiment_run
from src.execution.states import LifecycleState
from src.execution.adapters.registry import AdapterRegistry
from src.execution.adapters.dry_run import DryRunAdapter

@pytest.fixture
def base_app():
    from src.models.service import Service
    return ApplicationModel(
        application_id="app-1",
        name="test-app",
        technologies=[],
        services=[Service(service_id="svc-1", name="service-1", type="backend", source_path="/", application_id="app-1")],
        dependencies=[],
        apis=[],
        architecture={"nodes": [], "edges": []}
    )

@pytest.fixture
def base_spec():
    return ExperimentSpecification(
        experiment_id="exp-1",
        application_id="app-1",
        candidate_ids=[],
        name="test-exp",
        hypothesis="test",
        status="draft",
        fault=Fault(type="availability", method="kill", parameters={}),
        target=Target(type="service", id="svc-1", name="service-1"),
        duration_seconds=60,
        blast_radius=BlastRadius(scope="service", max_affected_components=1),
        steady_state=SteadyState(required=False),
        rollback=Rollback(strategy="none", automatic=False),
        safety=Safety(requires_approval=True, rollback_required=True)
    )
    
@pytest.fixture
def base_decision():
    return SafetyDecision(
        decision_id="dec-1",
        experiment_id="exp-1",
        application_id="app-1",
        decision="approved",
        allowed=True,
        reason="looks good",
        blockers=[],
        required_approvals=[],
        required_conditions=[]
    )
    
@pytest.fixture
def base_run(base_spec, base_decision):
    return create_experiment_run(base_spec, base_decision)

def test_valid_dry_run_orchestration(base_app, base_spec, base_decision, base_run):
    req = OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
        mode="dry_run"
    )
    controller = OrchestrationController()
    resp = controller.orchestrate(req)
    
    assert resp.status == "completed"
    assert resp.mode == "dry_run"
    assert resp.plan is not None
    assert resp.result is not None
    assert resp.result.metadata.get("simulated") is True
    assert base_run.state == LifecycleState.SETUP

def test_live_mode_rejected(base_app, base_spec, base_decision, base_run):
    req = OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
        mode="live"
    )
    controller = OrchestrationController()
    resp = controller.orchestrate(req)
    assert resp.status == "rejected"
    assert any("Live mode is not supported" in e for e in resp.errors)

def test_app_id_mismatch(base_app, base_spec, base_decision, base_run):
    base_app.application_id = "app-2"
    req = OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
    )
    controller = OrchestrationController()
    resp = controller.orchestrate(req)
    assert resp.status == "failed"
    assert "Application ID mismatch" in resp.errors[0]
    
def test_exp_id_mismatch(base_app, base_spec, base_decision, base_run):
    base_spec.experiment_id = "exp-2"
    req = OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
    )
    controller = OrchestrationController()
    resp = controller.orchestrate(req)
    assert resp.status == "failed"
    assert "Experiment ID mismatch" in resp.errors[0]

def test_blocked_decision(base_app, base_spec, base_decision, base_run):
    base_decision.decision = "blocked"
    req = OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
    )
    controller = OrchestrationController()
    resp = controller.orchestrate(req)
    assert resp.status == "rejected"
    assert any("blocked" in e for e in resp.errors)
    
def test_requires_approval_pending(base_app, base_spec, base_decision, base_run):
    base_decision.decision = "requires_approval"
    base_run.approval = ApprovalModel(required=True, status="pending")
    req = OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
    )
    controller = OrchestrationController()
    resp = controller.orchestrate(req)
    assert resp.status == "rejected"
    assert any("Authorization conditions not met" in e for e in resp.errors)

def test_requires_approval_approved(base_app, base_spec, base_decision, base_run):
    base_decision.decision = "requires_approval"
    base_run.approval = ApprovalModel(required=True, status="approved", approved_by="admin")
    req = OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
    )
    controller = OrchestrationController()
    resp = controller.orchestrate(req)
    assert resp.status == "completed"

def test_unsupported_fault_type(base_app, base_spec, base_decision, base_run):
    base_spec.fault.type = "quantum_entanglement_failure"
    req = OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
    )
    controller = OrchestrationController()
    resp = controller.orchestrate(req)
    assert resp.status == "failed"
    assert any("Routing/Planning failed" in e for e in resp.errors)
    
def test_no_side_effects(base_app, base_spec, base_decision, base_run):
    from unittest.mock import patch
    with patch("subprocess.run") as mock_sub, patch("os.system") as mock_sys:
        req = OrchestrationRequest(
            application_model=base_app,
            experiment_specification=base_spec,
            safety_decision=base_decision,
            experiment_run=base_run,
        )
        controller = OrchestrationController()
        resp = controller.orchestrate(req)
        
        assert resp.status == "completed"
        mock_sub.assert_not_called()
        mock_sys.assert_not_called()

def test_invalid_parameter_rejected(base_app, base_spec, base_decision, base_run):
    base_spec.duration_seconds = -10
    req = OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
    )
    controller = OrchestrationController()
    resp = controller.orchestrate(req)
    assert resp.status == "rejected"
    assert any("Experiment duration is invalid" in e for e in resp.errors)

def test_run_reorchestration_rejected(base_app, base_spec, base_decision, base_run):
    base_run.state = LifecycleState.RUNNING
    req = OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
    )
    controller = OrchestrationController()
    resp = controller.orchestrate(req)
    assert resp.status == "rejected"
    assert any("cannot be re-orchestrated" in e for e in resp.errors)
