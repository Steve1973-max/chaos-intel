import pytest
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.execution.persistence.models import Base, LeaseRecordModel
from src.execution.persistence.repositories import (
    SqlAlchemyLeaseRepository, SqlAlchemyRunRepository, SqlAlchemyIdempotencyRepository, 
    SqlTransactionBoundary, SqlAlchemyAuditRepository
)
from src.execution.orchestrator import OrchestrationController
from src.execution.orchestration_models import OrchestrationRequest
from src.execution.lifecycle import create_experiment_run
from src.models.experiment import ExperimentSpecification, Fault, Target, Safety, BlastRadius, SteadyState, Rollback
from src.models.safety import SafetyDecision
from src.models.application import ApplicationModel
from src.models.service import Service
from src.execution.reliability.errors import LeaseOwnershipError

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

def setup_controller(session):
    return OrchestrationController(
        run_repository=SqlAlchemyRunRepository(session),
        audit_repository=SqlAlchemyAuditRepository(session),
        transaction_boundary=SqlTransactionBoundary(session),
        idempotency_repository=SqlAlchemyIdempotencyRepository(session),
        lease_repository=SqlAlchemyLeaseRepository(session)
    )

def test_valid_dry_run_with_fencing(sqlite_session, base_app, base_spec, base_decision, base_run):
    controller = setup_controller(sqlite_session)
    req = OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
        mode="dry_run"
    )
    
    resp = controller.orchestrate(req, idempotency_key="test-key")
    assert resp.status == "completed"
    
    # Verify lease was acquired and released
    lease_model = sqlite_session.query(LeaseRecordModel).filter_by(resource_id=f"run:{base_run.run_id}").first()
    assert lease_model is not None
    assert lease_model.status == "released"
    
    # Verify idempotency was stored
    idemp_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    res = idemp_repo.get_result("app-1", "exp-1", "test-key")
    assert res is not None

def test_competing_attempt_fails_to_acquire(sqlite_session, base_app, base_spec, base_decision, base_run):
    controller = setup_controller(sqlite_session)
    # Simulate an active lease held by someone else
    lease_repo = SqlAlchemyLeaseRepository(sqlite_session)
    lease_repo.acquire(f"run:{base_run.run_id}", "other-worker", 600)
    sqlite_session.commit()
    
    req = OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
        mode="dry_run"
    )
    
    resp = controller.orchestrate(req, idempotency_key="test-key-2")
    assert resp.status == "rejected"
    assert any("Lease acquisition failed" in e for e in resp.errors)

def test_stale_fencing_token_aborts_orchestration(sqlite_session, base_app, base_spec, base_decision, base_run):
    # This requires mocking the `_execute_lifecycle` or similar to expire the lease mid-flight
    # We will subclass the boundary to simulate lease expiration right before the mutation
    class SabotagedTransactionBoundary(SqlTransactionBoundary):
        def fenced_transaction(self, resource_id, owner_id, token):
            # Expire the lease manually just before we use it
            lease = self.session.query(LeaseRecordModel).filter_by(resource_id=resource_id).first()
            if lease:
                lease.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
                self.session.flush()
            return super().fenced_transaction(resource_id, owner_id, token)

    controller = OrchestrationController(
        run_repository=SqlAlchemyRunRepository(sqlite_session),
        audit_repository=SqlAlchemyAuditRepository(sqlite_session),
        transaction_boundary=SabotagedTransactionBoundary(sqlite_session),
        idempotency_repository=SqlAlchemyIdempotencyRepository(sqlite_session),
        lease_repository=SqlAlchemyLeaseRepository(sqlite_session)
    )
    
    req = OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
        mode="dry_run"
    )
    
    resp = controller.orchestrate(req, idempotency_key="test-key-3")
    assert resp.status == "rejected"
    assert any("Lease ownership lost before execution" in e for e in resp.errors)

    # Ensure run state did not change in DB
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    db_run = run_repo.get_run(base_run.run_id)
    assert db_run is None # Was never created because it failed on first preflight!

def test_idempotent_duplicate_request(sqlite_session, base_app, base_spec, base_decision, base_run):
    controller = setup_controller(sqlite_session)
    req = OrchestrationRequest(
        application_model=base_app,
        experiment_specification=base_spec,
        safety_decision=base_decision,
        experiment_run=base_run,
        mode="dry_run"
    )
    
    # First attempt
    resp1 = controller.orchestrate(req, idempotency_key="dup-key")
    assert resp1.status == "completed"
    
    # Second attempt with same key
    resp2 = controller.orchestrate(req, idempotency_key="dup-key")
    assert resp2.status == "completed"
    assert resp1.model_dump() == resp2.model_dump()
