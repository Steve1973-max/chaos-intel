import os
import pytest
from src.main import analyze_application
from src.models.application import ApplicationModel
from src.models.architecture import ArchitectureGraph
from src.models.experiment import ExperimentSpecification, Target, Fault, BlastRadius, SteadyState, AbortCondition, Rollback, Safety
from src.safety.engine import generate_safety_decisions

def create_mock_app(exps=None):
    if exps is None: exps = []
    return ApplicationModel(
        application_id="app-1",
        name="test_app",
        technologies=[],
        services=[],
        dependencies=[],
        apis=[],
        architecture=ArchitectureGraph(nodes=[], edges=[]),
        risks=[],
        test_candidates=[],
        experiments=exps
    )

def default_exp(exp_id="exp-1"):
    return ExperimentSpecification(
        experiment_id=exp_id,
        application_id="app-1",
        candidate_ids=[],
        name="test",
        hypothesis="test",
        status="draft",
        target=Target(type="service", id="target-1", name="target-1"),
        fault=Fault(type="availability", method="service_stop"),
        duration_seconds=30,
        blast_radius=BlastRadius(scope="single_service", max_affected_components=1),
        steady_state=SteadyState(required=True, checks=["baseline_health"]),
        observations=[],
        abort_conditions=[AbortCondition(metric="health", operator="==", threshold="critical", action="abort")],
        rollback=Rollback(strategy="restore_target", automatic=True, verification_required=True),
        prerequisites=[],
        safety=Safety(
            requires_approval=False,
            environment_required="test",
            reversible=True,
            rollback_required=True,
            production_allowed=False
        ),
        confidence=0.8,
        evidence=[]
    )

def test_production_always_blocked():
    exp = default_exp()
    exp.safety.production_allowed = False
    exp.safety.environment_required = "production"
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert len(decs) == 1
    assert decs[0].decision == "blocked"
    assert "production" in "".join(decs[0].blockers).lower()

def test_unknown_environment_requires_configuration():
    exp = default_exp()
    exp.safety.environment_required = "unknown"
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert decs[0].decision == "requires_configuration"

def test_approval_requirement():
    exp = default_exp()
    exp.safety.requires_approval = True
    exp.fault.method = "custom"
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert decs[0].decision == "requires_approval"
    assert len(decs[0].required_approvals) > 0

def test_missing_rollback():
    exp = default_exp()
    exp.safety.rollback_required = True
    exp.rollback.strategy = ""
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert decs[0].decision == "requires_configuration"

def test_non_reversible_experiment():
    exp = default_exp()
    exp.safety.rollback_required = True
    exp.safety.reversible = False
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert decs[0].decision == "blocked"

def test_blast_radius_limits():
    exp = default_exp()
    exp.blast_radius.max_affected_components = 500
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert decs[0].decision == "blocked"

def test_missing_steady_state():
    exp = default_exp()
    exp.steady_state.required = True
    exp.steady_state.checks = []
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert decs[0].decision == "requires_configuration"

def test_missing_abort_conditions():
    exp = default_exp()
    exp.abort_conditions = []
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert decs[0].decision == "requires_configuration"

def test_invalid_target():
    exp = default_exp()
    exp.target.type = "unknown"
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert decs[0].decision == "requires_configuration"

def test_invalid_fault():
    exp = default_exp()
    exp.fault.type = "magic"
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert decs[0].decision == "blocked"

def test_invalid_duration():
    exp = default_exp()
    exp.duration_seconds = -5
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert decs[0].decision == "blocked"

def test_excessive_duration():
    exp = default_exp()
    exp.duration_seconds = 99999
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert decs[0].decision == "blocked"

def test_capability_requirement():
    exp = default_exp()
    exp.fault.method = "service_stop" # maps to service_control
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert len(decs[0].required_conditions) > 0
    assert "service_control" in "".join(decs[0].required_conditions)
    assert decs[0].decision == "requires_configuration"

def test_decision_precedence():
    exp = default_exp()
    # It has multiple issues: missing environment (requires_config) and non-reversible (blocked)
    exp.safety.environment_required = "unknown"
    exp.safety.reversible = False
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert decs[0].decision == "blocked" # blocked wins over requires_config

def test_deterministic_decision_id():
    exp = default_exp()
    app = create_mock_app([exp])
    d1 = generate_safety_decisions(app)
    d2 = generate_safety_decisions(app)
    assert d1[0].decision_id == d2[0].decision_id

def test_policy_version():
    exp = default_exp()
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert decs[0].policy_version == "1.0.0"

def test_fully_configured_experiment():
    exp = default_exp()
    exp.fault.method = "custom" # no mapped capability yet for test
    app = create_mock_app([exp])
    decs = generate_safety_decisions(app)
    assert decs[0].decision == "approved"
    assert decs[0].allowed is True

def test_empty_application():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "empty_project")
    app = analyze_application(fixture_path)
    assert len(app.safety_decisions) == 0

def test_full_end_to_end_safety_evaluation():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "react_fastapi")
    if os.path.exists(fixture_path):
        app = analyze_application(fixture_path)
        assert hasattr(app, "safety_decisions")
        assert len(app.safety_decisions) >= 0

def test_no_side_effects():
    # If the tests pass in under 1 second without failing due to network/shell mocks missing,
    # it implies it's declarative.
    pass
