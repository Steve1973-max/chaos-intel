import pytest
from src.execution.orchestration_models import OrchestrationRequest
from src.execution.states import LifecycleState
from src.execution.orchestrator import OrchestrationController
from src.models.application import ApplicationModel
from src.models.experiment import ExperimentSpecification, Fault, Target, Safety, BlastRadius, SteadyState, Rollback
from src.models.safety import SafetyDecision
from src.models.experiment_run import ExperimentRun, ApprovalModel
from src.execution.persistence.interfaces import CommitUncertaintyError
from src.execution.persistence.repositories import SqlAlchemyRunRepository, SqlAlchemyAuditRepository, SqlTransactionBoundary
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.execution.persistence.models import Base
from unittest.mock import patch, MagicMock

@pytest.fixture
def sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()

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
    from src.execution.lifecycle import create_experiment_run
    run = create_experiment_run(base_spec, base_decision)
    run.approval.status = "approved"
    return run

@pytest.fixture
def base_request(base_app, base_spec, base_decision, base_run):
    return OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
        mode="dry_run"
    )

def test_confirmed_rollback_no_durable_transition(sqlite_session, base_request):
    repo = SqlAlchemyRunRepository(sqlite_session)
    audit = SqlAlchemyAuditRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)
    
    # Pre-create the run
    repo.create_run(base_request.experiment_run)
    sqlite_session.commit()
    
    # Simulate a validation error during preflight
    with patch("src.execution.lifecycle.LifecycleController.start_preflight", side_effect=ValueError("Simulated validation error")):
        controller = OrchestrationController(
            run_repository=repo,
            audit_repository=audit,
            transaction_boundary=boundary
        )
        response = controller.orchestrate(base_request)
        
    assert response.status == "failed"
    
    # State in DB must remain CREATED, not AUTHORIZATION_PENDING or PREFLIGHT
    v, s = repo.get_version_and_state(base_request.experiment_run.run_id)
    assert s == LifecycleState.CREATED
    assert v == 1

def test_commit_uncertainty_no_adapter_invocation(sqlite_session, base_request):
    repo = SqlAlchemyRunRepository(sqlite_session)
    audit = SqlAlchemyAuditRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)
    
    repo.create_run(base_request.experiment_run)
    sqlite_session.commit()
    
    # Mock commit to fail after attempt
    def fake_commit():
        raise Exception("Connection dropped during commit")
        
    boundary.session.commit = fake_commit
    
    controller = OrchestrationController(
        run_repository=repo,
        audit_repository=audit,
        transaction_boundary=boundary
    )
    
    # Mock adapter router to verify it is NOT called
    with patch("src.execution.router.AdapterRouter.route") as mock_route:
        response = controller.orchestrate(base_request)
        
    assert response.status == "outcome_unknown"
    assert "Commit outcome is unknown" in response.errors[0]
    
    # Adapter must not be invoked when commit is unknown
    mock_route.assert_not_called()

def test_committed_transition_then_response_loss_prevents_duplicate(sqlite_session, base_request):
    repo = SqlAlchemyRunRepository(sqlite_session)
    audit = SqlAlchemyAuditRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)
    
    # Request 1 commits successfully and advances the state
    controller = OrchestrationController(
        run_repository=repo,
        audit_repository=audit,
        transaction_boundary=boundary
    )
    response1 = controller.orchestrate(base_request)
    assert response1.status == "completed"
    
    v, s = repo.get_version_and_state(base_request.experiment_run.run_id)
    assert s in (LifecycleState.AUTHORIZATION_PENDING, LifecycleState.AUTHORIZED, LifecycleState.SETUP) 
    
    # Request 2 (simulating response loss of Request 1)
    with patch("src.execution.lifecycle.LifecycleController.authorize") as mock_authorize:
        response2 = controller.orchestrate(base_request)
        
    assert response2.status == "rejected"
    assert "cannot be re-orchestrated" in response2.errors[0]
    
    # Second transition was NOT attempted
    mock_authorize.assert_not_called()

def test_rejected_duplicate_does_not_mutate_run(sqlite_session, base_request):
    repo = SqlAlchemyRunRepository(sqlite_session)
    audit = SqlAlchemyAuditRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)
    
    # First request
    controller = OrchestrationController(
        run_repository=repo,
        audit_repository=audit,
        transaction_boundary=boundary
    )
    controller.orchestrate(base_request)
    
    v1, s1 = repo.get_version_and_state(base_request.experiment_run.run_id)
    
    # Duplicate request
    controller.orchestrate(base_request)
    
    v2, s2 = repo.get_version_and_state(base_request.experiment_run.run_id)
    
    assert v1 == v2
    assert s1 == s2
