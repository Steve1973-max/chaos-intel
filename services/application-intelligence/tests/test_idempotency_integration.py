import pytest
from src.execution.orchestration_models import OrchestrationRequest
from src.execution.states import LifecycleState
from src.execution.orchestrator import OrchestrationController
from src.models.application import ApplicationModel
from src.models.experiment import ExperimentSpecification, Fault, Target, Safety, BlastRadius, SteadyState, Rollback
from src.models.safety import SafetyDecision
from src.models.experiment_run import ExperimentRun, ApprovalModel
from src.execution.persistence.interfaces import CommitUncertaintyError, IdempotencyConflictError
from src.execution.persistence.repositories import SqlAlchemyRunRepository, SqlAlchemyAuditRepository, SqlTransactionBoundary, SqlAlchemyIdempotencyRepository
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.execution.persistence.models import Base, IdempotencyRecordModel
from unittest.mock import patch

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

def test_1_new_reservation_success(sqlite_session, base_request):
    repo = SqlAlchemyRunRepository(sqlite_session)
    audit = SqlAlchemyAuditRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)
    idem_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    
    controller = OrchestrationController(
        run_repository=repo,
        audit_repository=audit,
        transaction_boundary=boundary,
        idempotency_repository=idem_repo
    )
    
    with patch("src.execution.router.AdapterRouter.route") as mock_route:
        from src.execution.adapters.dry_run import DryRunAdapter
        mock_route.return_value = (DryRunAdapter(), None)
        response = controller.orchestrate(base_request, idempotency_key="key-1")
    
    assert response.status == "completed"
    
    # Verify publication
    idem_record = sqlite_session.query(IdempotencyRecordModel).filter_by(idempotency_key_digest="key-1").first()
    assert idem_record.status == "completed"
    assert idem_record.terminal_result is not None
    assert idem_record.terminal_result["status"] == "completed"

def test_2_duplicate_in_progress_no_adapter(sqlite_session, base_request):
    repo = SqlAlchemyRunRepository(sqlite_session)
    audit = SqlAlchemyAuditRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)
    idem_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    
    controller = OrchestrationController(
        run_repository=repo,
        audit_repository=audit,
        transaction_boundary=boundary,
        idempotency_repository=idem_repo
    )
    
    # Pre-insert in-progress record
    idem_repo.reserve(base_request.application_model.application_id, base_request.experiment_specification.experiment_id, "key-2", controller.idempotency_manager.compute_fingerprint({
                "app_id": base_request.application_model.application_id,
                "spec_id": base_request.experiment_specification.experiment_id,
                "decision_id": base_request.safety_decision.decision_id,
                "mode": base_request.mode
            }), "owner-1")
    sqlite_session.commit()
    
    with patch("src.execution.router.AdapterRouter.route") as mock_route:
        response = controller.orchestrate(base_request, idempotency_key="key-2")
        
    assert response.status == "rejected"
    assert "already in progress" in response.errors[0]
    mock_route.assert_not_called()

def test_3_fingerprint_mismatch(sqlite_session, base_request):
    repo = SqlAlchemyRunRepository(sqlite_session)
    audit = SqlAlchemyAuditRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)
    idem_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    
    controller = OrchestrationController(
        run_repository=repo,
        audit_repository=audit,
        transaction_boundary=boundary,
        idempotency_repository=idem_repo
    )
    
    idem_repo.reserve(base_request.application_model.application_id, base_request.experiment_specification.experiment_id, "key-3", "different-fingerprint", "owner-1")
    sqlite_session.commit()
    
    response = controller.orchestrate(base_request, idempotency_key="key-3")
    assert response.status == "rejected"
    assert "Fingerprint divergence detected" in response.errors[0]

def test_4_non_owner_publication_rejected(sqlite_session, base_request):
    idem_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    idem_repo.reserve("app-1", "exp-1", "key-4", "fingerprint-1", "owner-1")
    sqlite_session.commit()
    
    with pytest.raises(ValueError, match="Only the reservation owner can publish"):
        idem_repo.publish_result("app-1", "exp-1", "key-4", "wrong-owner", {})

def test_5_completed_response_recovered(sqlite_session, base_request):
    repo = SqlAlchemyRunRepository(sqlite_session)
    audit = SqlAlchemyAuditRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)
    idem_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    
    controller1 = OrchestrationController(
        run_repository=repo,
        audit_repository=audit,
        transaction_boundary=boundary,
        idempotency_repository=idem_repo
    )
    
    response1 = controller1.orchestrate(base_request, idempotency_key="key-5")
    assert response1.status == "completed"
    
    # Recreate controller
    controller2 = OrchestrationController(
        run_repository=repo,
        audit_repository=audit,
        transaction_boundary=boundary,
        idempotency_repository=idem_repo
    )
    
    with patch("src.execution.router.AdapterRouter.route") as mock_route:
        response2 = controller2.orchestrate(base_request, idempotency_key="key-5")
        
    assert response2.status == "completed"
    assert response1.run_id == response2.run_id
    mock_route.assert_not_called()

def test_7_lifecycle_commit_success_publish_fails_retry_safety(sqlite_session, base_request):
    repo = SqlAlchemyRunRepository(sqlite_session)
    audit = SqlAlchemyAuditRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)
    idem_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    
    controller = OrchestrationController(
        run_repository=repo,
        audit_repository=audit,
        transaction_boundary=boundary,
        idempotency_repository=idem_repo
    )
    
    original_publish = idem_repo.publish_result
    def fake_publish(*args, **kwargs):
        raise Exception("Database dropped connection during publish")
        
    idem_repo.publish_result = fake_publish
    
    with patch("src.execution.router.AdapterRouter.route") as mock_route:
        from src.execution.adapters.dry_run import DryRunAdapter
        mock_route.return_value = (DryRunAdapter(), None)
        response = controller.orchestrate(base_request, idempotency_key="key-7")
        
    assert response.status == "outcome_unknown"
    assert "Response generated but could not be durably published." in response.errors[0]
    
    idem_record = sqlite_session.query(IdempotencyRecordModel).filter_by(idempotency_key_digest="key-7").first()
    assert idem_record.status == "in_progress"
    
    # Simulate an expired reservation for the retry by deleting the lock or mocking reserve to return 'acquired' again
    idem_repo.publish_result = original_publish
    sqlite_session.query(IdempotencyRecordModel).filter_by(idempotency_key_digest="key-7").delete()
    sqlite_session.commit()
    
    # The retry should be stopped by the DB run state guard
    with patch("src.execution.router.AdapterRouter.route") as mock_route2:
        retry_response = controller.orchestrate(base_request, idempotency_key="key-7")
        
    assert retry_response.status == "rejected"
    assert "cannot be re-orchestrated" in retry_response.errors[0]
    mock_route2.assert_not_called()

def test_10_invalid_stored_response_fails_closed(sqlite_session, base_request):
    idem_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    fingerprint = IdempotencyRecordModel.__table__.c.fingerprint
    
    idem_repo.reserve(base_request.application_model.application_id, base_request.experiment_specification.experiment_id, "key-10", "dummy", "owner-1")
    # Manually insert bad result
    record = sqlite_session.query(IdempotencyRecordModel).filter_by(idempotency_key_digest="key-10").first()
    record.status = "completed"
    record.terminal_result = {"status": "bad-schema"} # Missing required fields
    
    # Fix fingerprint to match
    controller = OrchestrationController(idempotency_repository=idem_repo)
    real_fingerprint = controller.idempotency_manager.compute_fingerprint({
        "app_id": base_request.application_model.application_id,
        "spec_id": base_request.experiment_specification.experiment_id,
        "decision_id": base_request.safety_decision.decision_id,
        "mode": base_request.mode
    })
    record.fingerprint = real_fingerprint
    sqlite_session.commit()
    
    response = controller.orchestrate(base_request, idempotency_key="key-10")
    assert response.status == "failed"
    assert "Stored response is malformed or incompatible." in response.errors[0]

def test_commit_uncertainty_safety(sqlite_session, base_request):
    repo = SqlAlchemyRunRepository(sqlite_session)
    audit = SqlAlchemyAuditRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)
    idem_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    
    controller = OrchestrationController(
        run_repository=repo,
        audit_repository=audit,
        transaction_boundary=boundary,
        idempotency_repository=idem_repo
    )
    
    original_transaction = boundary.transaction
    from contextlib import contextmanager
    @contextmanager
    def failing_transaction():
        yield
        raise CommitUncertaintyError("Commit uncertainty injected")
        
    boundary.transaction = failing_transaction
    
    with patch('src.execution.router.AdapterRouter.route') as mock_route:
        response = controller.orchestrate(base_request, idempotency_key="key-cu")
        
    assert response.status == "outcome_unknown"
    assert "Commit outcome is unknown" in response.errors[0]
    mock_route.assert_not_called()
    
    # Check that it wasn't published as completed
    idem_record = sqlite_session.query(IdempotencyRecordModel).filter_by(idempotency_key_digest="key-cu").first()
    assert idem_record.status == "in_progress"
    
    # Retry the request
    boundary.transaction = original_transaction # Restore normal transaction for retry to isolate idempotency behavior
    with patch('src.execution.router.AdapterRouter.route') as mock_route_retry:
        retry_response = controller.orchestrate(base_request, idempotency_key="key-cu")
        
    # The retry should see 'in_progress' and reject it
    assert retry_response.status == "rejected"
    assert "already in progress" in retry_response.errors[0]
    mock_route_retry.assert_not_called()

def test_stale_reservation_no_replay(sqlite_session, base_request):
    idem_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    import datetime
    
    # Manually insert an expired reservation
    stale_record = IdempotencyRecordModel(
        application_id=base_request.application_model.application_id,
        operation_scope=base_request.experiment_specification.experiment_id,
        idempotency_key_digest="key-stale",
        fingerprint="some-fingerprint",
        owner_id="old-owner",
        status="in_progress",
        expires_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    )
    sqlite_session.add(stale_record)
    sqlite_session.commit()
    
    # We expect the repository to still return in_progress because it does not auto-reclaim
    status, result = idem_repo.reserve(base_request.application_model.application_id, base_request.experiment_specification.experiment_id, "key-stale", "some-fingerprint", "new-owner")
    assert status == "in_progress"
    
    # Verify the record remains unchanged and retains the original owner
    record = sqlite_session.query(IdempotencyRecordModel).filter_by(idempotency_key_digest="key-stale").first()
    assert record.status == "in_progress"
    assert record.owner_id == "old-owner"

def test_pre_reservation_validation_failure(sqlite_session, base_request):
    idem_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    controller = OrchestrationController(idempotency_repository=idem_repo)
    
    # Mutate request to cause pre-reservation validation failure (ID mismatch)
    bad_request = base_request.model_copy(deep=True)
    bad_request.application_model.application_id = "mismatch-app"
    
    response = controller.orchestrate(bad_request, idempotency_key="key-preval")
    
    assert response.status == "failed"
    assert "Application ID mismatch" in response.errors[0]
    
    # Verify no reservation was made
    record = sqlite_session.query(IdempotencyRecordModel).filter_by(idempotency_key_digest="key-preval").first()
    assert record is None
