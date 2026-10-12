import pytest
from src.models.experiment_run import ExperimentRun, ApprovalModel
from src.models.experiment import ExperimentSpecification, Fault, Target, Safety, Rollback, BlastRadius, SteadyState
from src.models.safety import SafetyDecision
from src.models.application import ApplicationModel
from src.execution.states import LifecycleState
from src.execution.recovery import RecoveryClassifier, RecoveryClassification, RecoveryResult, RecoveryResultVariant
from src.execution.adapters.context import ExecutionContext
from src.execution.adapters.dry_run import DryRunAdapter
from src.execution.lifecycle import LifecycleController, create_experiment_run

@pytest.fixture
def base_spec():
    return ExperimentSpecification(
        experiment_id="exp-1",
        application_id="app-1",
        candidate_ids=[],
        name="test",
        hypothesis="test",
        status="draft",
        fault=Fault(type="latency", method="inject", parameters={}),
        target=Target(type="service", id="svc-1", name="svc-1"),
        duration_seconds=10,
        blast_radius=BlastRadius(scope="service", max_affected_components=1),
        steady_state=SteadyState(required=False),
        rollback=Rollback(strategy="none", automatic=False),
        safety=Safety(requires_approval=False, rollback_required=False)
    )

@pytest.fixture
def base_decision():
    return SafetyDecision(
        decision_id="dec-1",
        experiment_id="exp-1",
        application_id="app-1",
        decision="approved",
        allowed=True,
        reason="ok",
        blockers=[],
        required_approvals=[],
        required_conditions=[]
    )

@pytest.fixture
def base_app():
    return ApplicationModel(
        application_id="app-1", name="app", technologies=[], services=[], dependencies=[], apis=[], architecture={"nodes":[],"edges":[]}
    )

def test_classifier_pre_intent():
    run = ExperimentRun(run_id="r1", experiment_id="e1", application_id="a1", safety_decision_id="d1")
    run.state = LifecycleState.AUTHORIZED
    assert RecoveryClassifier.classify(run, True) == RecoveryClassification.NOT_INVOKED_PROVEN
    
    run.state = LifecycleState.CREATED
    assert RecoveryClassifier.classify(run, True) == RecoveryClassification.NOT_INVOKED_PROVEN

def test_classifier_post_intent():
    run = ExperimentRun(run_id="r1", experiment_id="e1", application_id="a1", safety_decision_id="d1")
    run.state = LifecycleState.SETUP
    assert RecoveryClassifier.classify(run, True) == RecoveryClassification.INVOCATION_POSSIBLE

    run.state = LifecycleState.RUNNING
    assert RecoveryClassifier.classify(run, True) == RecoveryClassification.INVOCATION_POSSIBLE

def test_classifier_terminal():
    run = ExperimentRun(run_id="r1", experiment_id="e1", application_id="a1", safety_decision_id="d1")
    run.state = LifecycleState.COMPLETED
    assert RecoveryClassifier.classify(run, True) == RecoveryClassification.OUTCOME_CONFIRMED

    run.state = LifecycleState.FAILED
    assert RecoveryClassifier.classify(run, True) == RecoveryClassification.OUTCOME_CONFIRMED

def test_classifier_uncertainty():
    run = ExperimentRun(run_id="r1", experiment_id="e1", application_id="a1", safety_decision_id="d1")
    run.state = LifecycleState.SETUP
    # no authoritative state (e.g. db down)
    assert RecoveryClassifier.classify(run, False) == RecoveryClassification.OUTCOME_UNKNOWN
    # none run object
    assert RecoveryClassifier.classify(None, True) == RecoveryClassification.OUTCOME_UNKNOWN

def test_recovery_result_validation():
    res = RecoveryResult(variant=RecoveryResultVariant.CONFIRMED_SUCCESS, run_id="r1")
    res.validate_for_run("r1") # should pass
    
    with pytest.raises(ValueError, match="does not match expected run_id"):
        res.validate_for_run("r2")

def test_dry_run_adapter_yields_inconclusive(base_spec, base_decision, base_app):
    run = create_experiment_run(base_spec, base_decision)
    context = ExecutionContext(run=run, experiment=base_spec, safety_decision=base_decision, application_model=base_app, adapter_id="dry-run", correlation_id=run.run_id)
    adapter = DryRunAdapter()
    res = adapter.verify_recovery(context)
    assert res.variant == RecoveryResultVariant.INCONCLUSIVE
    assert res.run_id == run.run_id

def test_lifecycle_verify_recovery_inconclusive(base_spec, base_decision, base_app):
    run = create_experiment_run(base_spec, base_decision)
    run.state = LifecycleState.RECOVERY_CHECK
    controller = LifecycleController(run, base_spec, base_decision, base_app)
    
    adapter = DryRunAdapter()
    controller.verify_recovery(adapter)
    
    assert run.recovery.status == "inconclusive"
    assert run.state == LifecycleState.RECOVERY_CHECK # state does not mutate to completed

def test_lifecycle_verify_recovery_success(base_spec, base_decision, base_app):
    run = create_experiment_run(base_spec, base_decision)
    run.state = LifecycleState.RECOVERY_CHECK
    controller = LifecycleController(run, base_spec, base_decision, base_app)
    
    class MockSuccessAdapter(DryRunAdapter):
        def verify_recovery(self, ctx):
            return RecoveryResult(variant=RecoveryResultVariant.CONFIRMED_SUCCESS, run_id=ctx.run.run_id)
            
    controller.verify_recovery(MockSuccessAdapter())
    
    assert run.recovery.status == "passed"
    assert run.state == LifecycleState.COMPLETED

def test_lifecycle_verify_recovery_failure(base_spec, base_decision, base_app):
    run = create_experiment_run(base_spec, base_decision)
    run.state = LifecycleState.RECOVERY_CHECK
    controller = LifecycleController(run, base_spec, base_decision, base_app)
    
    class MockFailureAdapter(DryRunAdapter):
        def verify_recovery(self, ctx):
            return RecoveryResult(variant=RecoveryResultVariant.CONFIRMED_FAILURE, run_id=ctx.run.run_id)
            
    controller.verify_recovery(MockFailureAdapter())
    
    assert run.recovery.status == "passed"
    assert run.state == LifecycleState.FAILED

def test_lifecycle_verify_recovery_wrong_run(base_spec, base_decision, base_app):
    run = create_experiment_run(base_spec, base_decision)
    run.state = LifecycleState.RECOVERY_CHECK
    controller = LifecycleController(run, base_spec, base_decision, base_app)
    
    class MockWrongAdapter(DryRunAdapter):
        def verify_recovery(self, ctx):
            return RecoveryResult(variant=RecoveryResultVariant.CONFIRMED_SUCCESS, run_id="wrong_id")
            
    controller.verify_recovery(MockWrongAdapter())
    
    assert run.recovery.status == "failed"
    assert run.state == LifecycleState.RECOVERY_FAILED


def test_lifecycle_verify_recovery_confirmed_rollback(base_spec, base_decision, base_app):
    """
    CONFIRMED_ROLLBACK: adapter reports that rollback completed.
    Expected contract (lifecycle.py:213–216, transitions.py:16):
      - run identity is validated before any mutation
      - state transitions from RECOVERY_CHECK to ABORTED via assert_valid_transition
      - recovery.status is set to "passed"
      - no other terminal state (COMPLETED, FAILED, RECOVERY_FAILED) is reached
    """
    run = create_experiment_run(base_spec, base_decision)
    run.state = LifecycleState.RECOVERY_CHECK
    controller = LifecycleController(run, base_spec, base_decision, base_app)

    class MockRollbackAdapter(DryRunAdapter):
        def verify_recovery(self, ctx):
            return RecoveryResult(
                variant=RecoveryResultVariant.CONFIRMED_ROLLBACK,
                run_id=ctx.run.run_id  # correct run identity
            )

    controller.verify_recovery(MockRollbackAdapter())

    # The result must map to ABORTED, not COMPLETED or FAILED
    assert run.state == LifecycleState.ABORTED, (
        f"Expected ABORTED after CONFIRMED_ROLLBACK, got {run.state}"
    )
    # recovery.status must be "passed" (rollback completed, not errored)
    assert run.recovery.status == "passed", (
        f"Expected recovery.status='passed', got {run.recovery.status!r}"
    )
    # Transition validation must not have been bypassed:
    # RECOVERY_CHECK → ABORTED is the only valid path; COMPLETED and FAILED must not be set.
    assert run.state != LifecycleState.COMPLETED
    assert run.state != LifecycleState.FAILED
    assert run.state != LifecycleState.RECOVERY_FAILED


def test_lifecycle_verify_recovery_confirmed_rollback_wrong_run(base_spec, base_decision, base_app):
    """
    CONFIRMED_ROLLBACK with a mismatched run_id must not transition the run.
    validate_for_run() must be called before any state mutation occurs.
    """
    run = create_experiment_run(base_spec, base_decision)
    run.state = LifecycleState.RECOVERY_CHECK
    controller = LifecycleController(run, base_spec, base_decision, base_app)

    class MockWrongRollbackAdapter(DryRunAdapter):
        def verify_recovery(self, ctx):
            return RecoveryResult(
                variant=RecoveryResultVariant.CONFIRMED_ROLLBACK,
                run_id="wrong-run-id"  # mismatched identity
            )

    controller.verify_recovery(MockWrongRollbackAdapter())

    # Identity check failure must route to RECOVERY_FAILED, never ABORTED
    assert run.state == LifecycleState.RECOVERY_FAILED, (
        f"Expected RECOVERY_FAILED on identity mismatch, got {run.state}"
    )
    assert run.recovery.status == "failed"
    assert run.state != LifecycleState.ABORTED


def test_lifecycle_verify_recovery_confirmed_rollback_invalid_source_state(base_spec, base_decision, base_app):
    """
    CONFIRMED_ROLLBACK must be rejected if verify_recovery is called from any state
    other than RECOVERY_CHECK. Transition validation must not be bypassed.
    """
    from src.execution.errors import InvalidStateTransitionError

    run = create_experiment_run(base_spec, base_decision)
    run.state = LifecycleState.RUNNING  # wrong source state
    controller = LifecycleController(run, base_spec, base_decision, base_app)

    class MockRollbackAdapter(DryRunAdapter):
        def verify_recovery(self, ctx):
            return RecoveryResult(
                variant=RecoveryResultVariant.CONFIRMED_ROLLBACK,
                run_id=ctx.run.run_id
            )

    with pytest.raises(InvalidStateTransitionError):
        controller.verify_recovery(MockRollbackAdapter())


# ==============================================================================
# Phase 2C.5C Tests: Recovery Processor & Safe Orchestration
# ==============================================================================

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.execution.persistence.models import Base
from src.execution.persistence.repositories import (
    SqlAlchemyLeaseRepository,
    SqlAlchemyRunRepository,
    SqlAlchemyIdempotencyRepository,
    SqlTransactionBoundary,
    SqlAlchemyAuditRepository,
)
from src.execution.recovery import (
    RecoveryProcessor,
    RecoveryProcessingRequest,
    RecoveryProcessingStatus,
)
from src.execution.reliability.errors import (
    LeaseAcquisitionError,
    LeaseOwnershipError,
)
from src.execution.persistence.interfaces import (
    OptimisticConcurrencyError,
    CommitUncertaintyError,
)
from src.execution.adapters.base import ExecutionAdapter, AdapterCapabilities
from contextlib import contextmanager
import uuid


@pytest.fixture
def sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()


def create_persisted_run(session, base_spec, base_decision, state=LifecycleState.CREATED, run_id=None):
    run_repo = SqlAlchemyRunRepository(session)
    run = create_experiment_run(base_spec, base_decision)
    if run_id:
        run.run_id = run_id
    run.state = state
    run_repo.create_run(run)
    session.commit()
    return run


def make_processor(session):
    return RecoveryProcessor(
        run_repository=SqlAlchemyRunRepository(session),
        lease_repository=SqlAlchemyLeaseRepository(session),
        idempotency_repository=SqlAlchemyIdempotencyRepository(session),
        transaction_boundary=SqlTransactionBoundary(session),
        audit_repository=SqlAlchemyAuditRepository(session),
    )


class TrackingMockAdapter(DryRunAdapter):
    def __init__(self, variant=RecoveryResultVariant.INCONCLUSIVE, wrong_run=False):
        self.variant = variant
        self.wrong_run = wrong_run
        self.verify_calls = 0
        self.replay_calls = 0

    def verify_recovery(self, ctx):
        self.verify_calls += 1
        run_id = "wrong-run-id" if self.wrong_run else ctx.run.run_id
        return RecoveryResult(variant=self.variant, run_id=run_id)

    def execute_experiment(self, ctx):
        self.replay_calls += 1
        raise AssertionError("Replay must never be called during recovery processing!")


# Test 1: Pre-intent run classified safely without invoking adapter
def test_recovery_pre_intent_not_invoked_proven(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.CREATED)
    processor = make_processor(sqlite_session)
    mock_adapter = TrackingMockAdapter(variant=RecoveryResultVariant.CONFIRMED_SUCCESS)

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req, adapter=mock_adapter)

    assert res.status == RecoveryProcessingStatus.CONFIRMED_NOT_INVOKED
    assert res.classification == RecoveryClassification.NOT_INVOKED_PROVEN
    assert res.action_taken == "recorded_finding_no_replay"
    assert mock_adapter.verify_calls == 0
    assert mock_adapter.replay_calls == 0
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    assert run_repo.get_run(run.run_id).state == LifecycleState.CREATED


# Test 2: Post-intent run not automatically replayed
def test_recovery_post_intent_not_automatically_replayed(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.RUNNING)
    processor = make_processor(sqlite_session)
    mock_adapter = TrackingMockAdapter(variant=RecoveryResultVariant.INCONCLUSIVE)

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req, adapter=mock_adapter)

    assert res.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res.action_taken == "preserved_unresolved_state"
    assert mock_adapter.verify_calls == 1
    assert mock_adapter.replay_calls == 0
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    assert run_repo.get_run(run.run_id).state == LifecycleState.RUNNING


# Test 3: Unsupported reconciliation adapter returns inconclusive result
def test_recovery_unsupported_reconciliation_adapter_inconclusive(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.RECOVERY_CHECK)
    processor = make_processor(sqlite_session)

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req, adapter=DryRunAdapter())

    assert res.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res.classification == RecoveryClassification.INVOCATION_POSSIBLE
    assert res.action_taken == "preserved_unresolved_state"
    assert "inconclusive" in res.reason.lower()
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    assert run_repo.get_run(run.run_id).state == LifecycleState.RECOVERY_CHECK


# Test 4: Inconclusive outcome preserves unresolved state and in-progress idempotency reservation
def test_recovery_inconclusive_preserves_unresolved_state_and_idempotency_reservation(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.RUNNING)
    idemp_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    idemp_repo.reserve(run.application_id, run.experiment_id, "idemp-key-test4", "fp-1", "worker-1")
    sqlite_session.commit()

    processor = make_processor(sqlite_session)
    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-key-test4",
        expected_fingerprint="fp-1",
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req, adapter=DryRunAdapter())

    assert res.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    assert run_repo.get_run(run.run_id).state == LifecycleState.RUNNING
    rec = idemp_repo.get_record(run.application_id, run.experiment_id, "idemp-key-test4")
    assert rec is not None
    assert rec.status == "in_progress"


# Test 5: Missing or mismatched idempotency records flagged as inconsistent
def test_recovery_outcome_confirmed_corroborates_idempotency(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.COMPLETED)
    idemp_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    idemp_repo.reserve(run.application_id, run.experiment_id, "idemp-valid", "fp-valid", "worker-1")
    idemp_repo.publish_result(run.application_id, run.experiment_id, "idemp-valid", "worker-1", {"status": "COMPLETED"})
    sqlite_session.commit()

    processor = make_processor(sqlite_session)

    # 5a: Valid corroborated outcome
    req_valid = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-valid",
        expected_fingerprint="fp-valid",
        expected_owner="worker-1",
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res_valid = processor.process_recovery(req_valid)
    assert res_valid.status == RecoveryProcessingStatus.OUTCOME_CONFIRMED
    assert res_valid.action_taken == "corroborated_terminal_outcome"

    # 5b: Missing idempotency record
    req_missing = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="missing-key",
        expected_fingerprint="fp-valid",
        expected_owner="worker-1",
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res_missing = processor.process_recovery(req_missing)
    assert res_missing.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res_missing.action_taken == "flagged_inconsistency"
    assert "lacks idempotency record" in res_missing.reason

    # 5c: Fingerprint mismatch
    req_mismatch = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-valid",
        expected_fingerprint="fp-different",
        expected_owner="worker-1",
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res_mismatch = processor.process_recovery(req_mismatch)
    assert res_mismatch.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res_mismatch.action_taken == "flagged_inconsistency"
    assert "fingerprint mismatch" in res_mismatch.reason.lower()

    # 5d: Contradictory in_progress reservation for terminal run
    idemp_repo.reserve(run.application_id, run.experiment_id, "idemp-inprog", "fp-inprog", "worker-1")
    sqlite_session.commit()
    req_inprog = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-inprog",
        expected_fingerprint="fp-inprog",
        expected_owner="worker-1",
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res_inprog = processor.process_recovery(req_inprog)
    assert res_inprog.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res_inprog.action_taken == "flagged_inconsistency"
    assert "status" in res_inprog.reason.lower()

    # 5e: Conflicting terminal-result payload
    idemp_repo.reserve(run.application_id, run.experiment_id, "idemp-conflict", "fp-conflict", "worker-1")
    idemp_repo.publish_result(run.application_id, run.experiment_id, "idemp-conflict", "worker-1", {"status": "FAILED"})
    sqlite_session.commit()
    req_conflict = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-conflict",
        expected_fingerprint="fp-conflict",
        expected_owner="worker-1",
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res_conflict = processor.process_recovery(req_conflict)
    assert res_conflict.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res_conflict.action_taken == "flagged_inconsistency"
    assert "disagrees" in res_conflict.reason.lower() or "conflict" in res_conflict.reason.lower()

    # 5f: Uncertain outcome flag set on idempotency record
    from src.execution.persistence.models import IdempotencyRecordModel
    from sqlalchemy import update
    sqlite_session.execute(
        update(IdempotencyRecordModel)
        .where(IdempotencyRecordModel.idempotency_key_digest == "idemp-valid")
        .values(uncertain_outcome=True)
    )
    sqlite_session.commit()
    req_uncertain = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-valid",
        expected_fingerprint="fp-valid",
        expected_owner="worker-1",
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res_uncertain = processor.process_recovery(req_uncertain)
    assert res_uncertain.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res_uncertain.action_taken == "flagged_inconsistency"
    assert "uncertain_outcome" in res_uncertain.reason.lower()

    # 5g: Owner mismatch
    # Reset uncertain_outcome first
    sqlite_session.execute(
        update(IdempotencyRecordModel)
        .where(IdempotencyRecordModel.idempotency_key_digest == "idemp-valid")
        .values(uncertain_outcome=False)
    )
    sqlite_session.commit()
    req_owner_mismatch = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-valid",
        expected_fingerprint="fp-valid",
        expected_owner="other-worker-99",
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res_owner_mismatch = processor.process_recovery(req_owner_mismatch)
    assert res_owner_mismatch.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res_owner_mismatch.action_taken == "flagged_inconsistency"
    assert "owner mismatch" in res_owner_mismatch.reason.lower()

    # 5h: Missing / unestablished expected owner
    req_no_owner = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-valid",
        expected_fingerprint="fp-valid",
        expected_owner=None,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res_no_owner = processor.process_recovery(req_no_owner)
    assert res_no_owner.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res_no_owner.action_taken == "flagged_inconsistency"


# Test 6: Wrong-run reconciliation response rejected
def test_recovery_wrong_run_reconciliation_rejected(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.RECOVERY_CHECK)
    processor = make_processor(sqlite_session)
    mock_adapter = TrackingMockAdapter(variant=RecoveryResultVariant.CONFIRMED_SUCCESS, wrong_run=True)

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req, adapter=mock_adapter)

    assert res.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res.action_taken == "reconciliation_error"
    assert "does not match expected run_id" in res.reason.lower()
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    assert run_repo.get_run(run.run_id).state == LifecycleState.RECOVERY_CHECK


# Test 7: Stale fencing token cannot commit recovery mutation
def test_recovery_stale_fencing_token_rejected(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.RECOVERY_CHECK)
    mock_adapter = TrackingMockAdapter(variant=RecoveryResultVariant.CONFIRMED_SUCCESS)

    class MockFencingErrorBoundary:
        @contextmanager
        def fenced_transaction(self, resource_id, owner_id, fencing_token):
            raise LeaseOwnershipError("Stale or invalid fencing token")
            yield

    processor = RecoveryProcessor(
        run_repository=SqlAlchemyRunRepository(sqlite_session),
        lease_repository=SqlAlchemyLeaseRepository(sqlite_session),
        transaction_boundary=MockFencingErrorBoundary(),
        audit_repository=SqlAlchemyAuditRepository(sqlite_session),
    )

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req, adapter=mock_adapter)

    assert res.status == RecoveryProcessingStatus.RECOVERY_BLOCKED
    assert res.action_taken == "none_fencing_or_concurrency_error"
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    assert run_repo.get_run(run.run_id).state == LifecycleState.RECOVERY_CHECK


# Test 8: Lease-acquisition failure causes no protected mutation
def test_recovery_lease_acquisition_failure_blocks_mutation(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.RECOVERY_CHECK)
    lease_repo = SqlAlchemyLeaseRepository(sqlite_session)
    lease_repo.acquire(f"run:{run.run_id}", "other-active-worker", 300)
    sqlite_session.commit()

    processor = make_processor(sqlite_session)
    mock_adapter = TrackingMockAdapter(variant=RecoveryResultVariant.CONFIRMED_SUCCESS)

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        worker_id="recovery-worker-1",
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req, adapter=mock_adapter)

    assert res.status == RecoveryProcessingStatus.RECOVERY_BLOCKED
    assert res.action_taken == "none_lease_held"
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    assert run_repo.get_run(run.run_id).state == LifecycleState.RECOVERY_CHECK


# Test 9: Commit-uncertainty error leaves outcome unresolved
def test_recovery_commit_uncertainty_leaves_outcome_unknown(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.RECOVERY_CHECK)
    mock_adapter = TrackingMockAdapter(variant=RecoveryResultVariant.CONFIRMED_SUCCESS)

    class MockCommitUncertaintyBoundary:
        @contextmanager
        def fenced_transaction(self, resource_id, owner_id, fencing_token):
            raise CommitUncertaintyError("Database connection timed out during commit")
            yield

    processor = RecoveryProcessor(
        run_repository=SqlAlchemyRunRepository(sqlite_session),
        lease_repository=SqlAlchemyLeaseRepository(sqlite_session),
        transaction_boundary=MockCommitUncertaintyBoundary(),
        audit_repository=SqlAlchemyAuditRepository(sqlite_session),
    )

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req, adapter=mock_adapter)

    assert res.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res.action_taken == "none_commit_uncertain"
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    assert run_repo.get_run(run.run_id).state == LifecycleState.RECOVERY_CHECK


# Test 10: Stale in-memory state revalidated inside transaction before mutation
def test_recovery_stale_in_memory_state_revalidated_inside_transaction(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.RECOVERY_CHECK)
    mock_adapter = TrackingMockAdapter(variant=RecoveryResultVariant.CONFIRMED_SUCCESS)

    real_boundary = SqlTransactionBoundary(sqlite_session)

    class VersionAdvancingBoundary:
        @contextmanager
        def fenced_transaction(self, resource_id, owner_id, fencing_token):
            # Advance the version in the database right before transaction execution
            run_repo = SqlAlchemyRunRepository(sqlite_session)
            db_run = run_repo.get_run(run.run_id)
            run_repo.transition_state(run.run_id, db_run.version, LifecycleState.RUNNING, db_run)
            sqlite_session.commit()
            with real_boundary.fenced_transaction(resource_id, owner_id, fencing_token):
                yield

    processor = RecoveryProcessor(
        run_repository=SqlAlchemyRunRepository(sqlite_session),
        lease_repository=SqlAlchemyLeaseRepository(sqlite_session),
        transaction_boundary=VersionAdvancingBoundary(),
        audit_repository=SqlAlchemyAuditRepository(sqlite_session),
    )

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req, adapter=mock_adapter)

    assert res.status == RecoveryProcessingStatus.RECOVERY_BLOCKED
    assert res.action_taken == "none_fencing_or_concurrency_error"
    assert "concurrency" in res.reason.lower() or "stale" in res.reason.lower()


# Test 11: Recovery decisions and state changes audited atomically
def test_recovery_decisions_and_transitions_audited_atomically(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.RECOVERY_CHECK)
    processor = make_processor(sqlite_session)
    mock_adapter = TrackingMockAdapter(variant=RecoveryResultVariant.CONFIRMED_SUCCESS)

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        worker_id="test-audited-worker",
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req, adapter=mock_adapter)

    assert res.status == RecoveryProcessingStatus.OUTCOME_CONFIRMED
    assert res.current_state == LifecycleState.COMPLETED

    run_repo = SqlAlchemyRunRepository(sqlite_session)
    assert run_repo.get_run(run.run_id).state == LifecycleState.COMPLETED

    history = run_repo.get_history(run.run_id)
    assert len(history) > 0
    latest_hist = history[-1]
    assert latest_hist.previous_state == LifecycleState.RECOVERY_CHECK
    assert latest_hist.new_state == LifecycleState.COMPLETED
    assert "test-audited-worker" in latest_hist.actor

    audit_repo = SqlAlchemyAuditRepository(sqlite_session)
    events = audit_repo.get_events(run.run_id)
    committed_events = [e for e in events if e.event_type == "recovery_transition_committed"]
    assert len(committed_events) == 1
    assert committed_events[0].metadata["to_state"] == LifecycleState.COMPLETED
    assert committed_events[0].metadata["worker_id"] == "test-audited-worker"


# Test 12: Recovery call with no adapter cannot falsely mark run successful; ctrl.verify_recovery guarded
def test_recovery_no_adapter_cannot_falsely_mark_success(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.RECOVERY_CHECK)
    processor = make_processor(sqlite_session)

    # 12a: RecoveryProcessor with adapter=None yields OUTCOME_UNKNOWN and does not mutate
    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req, adapter=None)

    assert res.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res.action_taken == "none_no_adapter"
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    assert run_repo.get_run(run.run_id).state == LifecycleState.RECOVERY_CHECK

    # 12b: LifecycleController.verify_recovery(adapter=None, require_adapter=True) sets RECOVERY_FAILED and records error
    mem_run = create_experiment_run(base_spec, base_decision)
    mem_run.state = LifecycleState.RECOVERY_CHECK
    ctrl = LifecycleController(mem_run, base_spec, base_decision, base_app)

    ctrl.verify_recovery(adapter=None, require_adapter=True)

    assert mem_run.state == LifecycleState.RECOVERY_FAILED
    assert mem_run.recovery.status == "failed"
    assert "Execution adapter is required" in mem_run.recovery.error
    assert mem_run.state != LifecycleState.COMPLETED


# Test 13: Repeated recovery requests do not cause duplicate external invocation
def test_recovery_repeated_requests_idempotent(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.RECOVERY_CHECK)
    processor = make_processor(sqlite_session)
    mock_adapter = TrackingMockAdapter(variant=RecoveryResultVariant.CONFIRMED_SUCCESS)

    idemp_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    idemp_repo.reserve(run.application_id, run.experiment_id, "idemp-rep-key", "fp-rep", "worker-orig")
    sqlite_session.commit()

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-rep-key",
        expected_fingerprint="fp-rep",
        expected_owner="worker-orig",
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )

    # First call: reconciles and transitions to COMPLETED
    res1 = processor.process_recovery(req, adapter=mock_adapter)
    assert res1.status == RecoveryProcessingStatus.OUTCOME_CONFIRMED
    assert mock_adapter.verify_calls == 1

    # Second call: run is now COMPLETED, idempotency result was published during first call
    res2 = processor.process_recovery(req, adapter=mock_adapter)
    assert res2.status == RecoveryProcessingStatus.OUTCOME_CONFIRMED
    assert res2.action_taken == "corroborated_terminal_outcome"
    assert mock_adapter.verify_calls == 1  # No repeated external verification!


# Test 14: Existing lifecycle and execution-intent guarantees remain intact
def test_recovery_preserves_lifecycle_and_execution_intent_guarantees(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.CREATED)
    processor = make_processor(sqlite_session)
    mock_adapter = TrackingMockAdapter(variant=RecoveryResultVariant.CONFIRMED_SUCCESS)

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req, adapter=mock_adapter)

    # Pre-intent run cannot jump to COMPLETED
    assert res.status == RecoveryProcessingStatus.CONFIRMED_NOT_INVOKED
    assert res.action_taken == "recorded_finding_no_replay"
    assert mock_adapter.verify_calls == 0

    run_repo = SqlAlchemyRunRepository(sqlite_session)
    final_run = run_repo.get_run(run.run_id)
    assert final_run.state == LifecycleState.CREATED


# Test 15 (F-01): Idempotency publication failure inside mutation transaction rolls back atomically
def test_recovery_idempotency_publication_failure_rolls_back_transaction(sqlite_session, base_spec, base_decision, base_app, monkeypatch):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.RECOVERY_CHECK)
    processor = make_processor(sqlite_session)
    mock_adapter = TrackingMockAdapter(variant=RecoveryResultVariant.CONFIRMED_SUCCESS)

    idemp_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    idemp_repo.reserve(run.application_id, run.experiment_id, "idemp-fail-key", "fp-fail", "worker-1")
    sqlite_session.commit()

    # Simulate publish_result failure inside the transaction
    def failing_publish(*args, **kwargs):
        raise RuntimeError("Simulated idempotency publication network/disk error")

    monkeypatch.setattr(processor.idempotency_repository, "publish_result", failing_publish)

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-fail-key",
        expected_fingerprint="fp-fail",
        expected_owner="worker-1",
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req, adapter=mock_adapter)

    assert res.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res.action_taken == "none_transaction_aborted"
    assert "aborted" in res.reason.lower()

    # Database state re-query: atomic rollback must have reverted run state, version, and history
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    fresh_run = run_repo.get_run(run.run_id)
    assert fresh_run.state == LifecycleState.RECOVERY_CHECK
    assert fresh_run.version == 1

    history = run_repo.get_history(run.run_id)
    assert len(history) == 0

    rec = idemp_repo.get_record(run.application_id, run.experiment_id, "idemp-fail-key")
    assert rec.status == "in_progress"


# Test 16 (F-03): Standalone audit durability and session isolation
def test_recovery_standalone_audit_durability_and_isolation(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.CREATED)
    processor = make_processor(sqlite_session)

    # Insert an unrelated dirty model into the shared session that is uncommitted
    from src.execution.persistence.models import ExperimentRunModel
    unrelated_model = ExperimentRunModel(
        id="unrelated-dirty-run-123",
        application_id="app-1",
        experiment_id="exp-1",
        state="CREATED",
        version=1,
        safety_decision_id="dec-1",
        correlation_id="not-set",
        metadata_payload={}
    )
    sqlite_session.add(unrelated_model)
    assert unrelated_model in sqlite_session.new

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req)

    assert res.status == RecoveryProcessingStatus.CONFIRMED_NOT_INVOKED

    # Verify that unrelated_model was NOT committed by processor and is still uncommitted in sqlite_session.new
    assert unrelated_model in sqlite_session.new

    # Roll back the shared session: the unrelated dirty model is discarded
    sqlite_session.rollback()
    assert unrelated_model not in sqlite_session

    run_repo = SqlAlchemyRunRepository(sqlite_session)
    assert run_repo.get_run("unrelated-dirty-run-123") is None

    # The audit event is durably committed because it was written via isolated session
    audit_repo = SqlAlchemyAuditRepository(sqlite_session)
    events = audit_repo.get_events(run.run_id)
    assert len(events) >= 1
    assert any(e.event_type == "recovery_decision" for e in events)


# Test 17 (F-03): Standalone audit write failure returns OUTCOME_UNKNOWN and does not report success
def test_recovery_standalone_audit_write_failure_returns_unknown(sqlite_session, base_spec, base_decision, base_app, monkeypatch):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.CREATED)
    processor = make_processor(sqlite_session)

    def failing_append_durable(*args, **kwargs):
        raise RuntimeError("Simulated audit write failure")

    monkeypatch.setattr(processor.audit_repository, "append_durable", failing_append_durable)

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req)

    assert res.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res.action_taken == "none_audit_write_failed"
    assert "Failed to durably record audit" in res.reason


# Test 18 (F-04): LifecycleController.verify_recovery defaults to safe behavior when require_adapter is omitted
def test_lifecycle_verify_recovery_default_guard(base_spec, base_decision, base_app):
    mem_run = create_experiment_run(base_spec, base_decision)
    mem_run.state = LifecycleState.RECOVERY_CHECK
    ctrl = LifecycleController(mem_run, base_spec, base_decision, base_app)

    # Calling verify_recovery without arguments defaults to require_adapter=True and adapter=None
    ctrl.verify_recovery()

    assert mem_run.state == LifecycleState.RECOVERY_FAILED
    assert mem_run.recovery.status == "failed"
    assert "Execution adapter is required" in mem_run.recovery.error
    assert mem_run.state != LifecycleState.COMPLETED


# Test 19 (F-06): NOT_INVOKED_PROVEN branch blocked when active worker lease is held
def test_recovery_not_invoked_proven_with_active_lease_blocks(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.CREATED)
    lease_repo = SqlAlchemyLeaseRepository(sqlite_session)
    lease_repo.acquire(f"run:{run.run_id}", "concurrent-worker-abc", 300)
    sqlite_session.commit()

    processor = make_processor(sqlite_session)
    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req)

    assert res.status == RecoveryProcessingStatus.RECOVERY_BLOCKED
    assert res.action_taken == "none_lease_held"
    assert "active unexpired worker lease" in res.reason.lower()


# Test 20 (F-06): NOT_INVOKED_PROVEN branch returns OUTCOME_UNKNOWN on lease lookup failure
def test_recovery_not_invoked_proven_lease_lookup_failure_returns_unknown(sqlite_session, base_spec, base_decision, base_app, monkeypatch):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.CREATED)
    processor = make_processor(sqlite_session)

    def failing_is_active(*args, **kwargs):
        raise RuntimeError("Lease table unreachable")

    monkeypatch.setattr(processor, "_is_active_lease_held", failing_is_active)

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req)

    assert res.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res.action_taken == "none_lease_lookup_failed"
    assert "lease lookup error" in res.reason.lower()


# ==============================================================================
# Phase 2C.5C Final Hardening Regression Tests: Gap 1 & Gap 2
# ==============================================================================

# Gap 1.1: A recovery-written metadata value cannot satisfy owner verification
def test_recovery_metadata_idempotency_owner_cannot_satisfy_owner_verification(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.COMPLETED)
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    run.metadata["idempotency_owner"] = "untrusted-recovery-written-owner"
    run_repo.transition_state(run.run_id, run.version, run.state, run)

    idemp_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    idemp_repo.reserve(run.application_id, run.experiment_id, "idemp-untrusted", "fp-valid", "untrusted-recovery-written-owner")
    idemp_repo.publish_result(run.application_id, run.experiment_id, "idemp-untrusted", "untrusted-recovery-written-owner", {"status": "COMPLETED"})
    sqlite_session.commit()

    processor = make_processor(sqlite_session)
    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-untrusted",
        expected_fingerprint="fp-valid",
        expected_owner=None,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req)

    assert res.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res.action_taken == "flagged_inconsistency"
    assert "owner mismatch or unestablished" in res.reason.lower()


# Gap 1.2: A valid independently established owner can pass corroboration
def test_recovery_valid_independently_established_owner_passes_corroboration(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.COMPLETED)
    idemp_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    idemp_repo.reserve(run.application_id, run.experiment_id, "idemp-indep", "fp-valid", "authoritative-worker-1")
    idemp_repo.publish_result(run.application_id, run.experiment_id, "idemp-indep", "authoritative-worker-1", {"status": "COMPLETED"})
    sqlite_session.commit()

    processor = make_processor(sqlite_session)

    # Case A: Owner established via explicit contract in RecoveryProcessingRequest
    req_contract = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-indep",
        expected_fingerprint="fp-valid",
        expected_owner="authoritative-worker-1",
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res_contract = processor.process_recovery(req_contract)
    assert res_contract.status == RecoveryProcessingStatus.OUTCOME_CONFIRMED
    assert res_contract.action_taken == "corroborated_terminal_outcome"

    # Case B: Owner established via immutable pre-intent run metadata (owner_id)
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    run.metadata["owner_id"] = "authoritative-worker-1"
    run_repo.transition_state(run.run_id, run.version, run.state, run)
    sqlite_session.commit()

    req_meta = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-indep",
        expected_fingerprint="fp-valid",
        expected_owner=None,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res_meta = processor.process_recovery(req_meta)
    assert res_meta.status == RecoveryProcessingStatus.OUTCOME_CONFIRMED
    assert res_meta.action_taken == "corroborated_terminal_outcome"


# Gap 1.3: Missing or mismatched ownership evidence fails closed
def test_recovery_missing_or_mismatched_ownership_fails_closed(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.COMPLETED)
    idemp_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    idemp_repo.reserve(run.application_id, run.experiment_id, "idemp-mismatch", "fp-valid", "actual-reservation-owner")
    idemp_repo.publish_result(run.application_id, run.experiment_id, "idemp-mismatch", "actual-reservation-owner", {"status": "COMPLETED"})
    sqlite_session.commit()

    processor = make_processor(sqlite_session)

    # Mismatched owner
    req_mismatch = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-mismatch",
        expected_fingerprint="fp-valid",
        expected_owner="wrong-owner",
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res_mismatch = processor.process_recovery(req_mismatch)
    assert res_mismatch.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res_mismatch.action_taken == "flagged_inconsistency"

    # Missing owner (neither in request nor in run metadata)
    req_missing = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-mismatch",
        expected_fingerprint="fp-valid",
        expected_owner=None,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res_missing = processor.process_recovery(req_missing)
    assert res_missing.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res_missing.action_taken == "flagged_inconsistency"


# Gap 1.4: Repeated recovery does not turn previously untrusted evidence into trusted evidence
def test_recovery_repeated_recovery_does_not_turn_untrusted_evidence_into_trusted(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.RECOVERY_CHECK)
    processor = make_processor(sqlite_session)
    mock_adapter = TrackingMockAdapter(variant=RecoveryResultVariant.CONFIRMED_SUCCESS)

    idemp_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    idemp_repo.reserve(run.application_id, run.experiment_id, "idemp-untrusted-rep", "fp-rep", "orig-owner")
    sqlite_session.commit()

    # Recovery request without independently established expected owner
    req_no_owner = RecoveryProcessingRequest(
        run_id=run.run_id,
        idempotency_key="idemp-untrusted-rep",
        expected_fingerprint="fp-rep",
        expected_owner=None,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )

    # Pass 1: reconciles to COMPLETED; recovery must NOT retroactively manufacture owner evidence
    res1 = processor.process_recovery(req_no_owner, adapter=mock_adapter)
    assert res1.status == RecoveryProcessingStatus.OUTCOME_CONFIRMED

    # Verify run metadata does NOT contain manufactured idempotency_owner
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    db_run = run_repo.get_run(run.run_id)
    assert "idempotency_owner" not in (db_run.metadata or {})

    # Pass 2: run is now terminal COMPLETED; because owner was not independently established,
    # repeated recovery fails closed and does NOT declare success or turn untrusted into trusted
    res2 = processor.process_recovery(req_no_owner, adapter=mock_adapter)
    assert res2.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res2.action_taken == "flagged_inconsistency"
    assert "owner mismatch or unestablished" in res2.reason.lower()


# Gap 2.1: Recovery winning coordination blocks competing execution worker
def test_recovery_winning_coordination_blocks_execution(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.CREATED)
    processor = make_processor(sqlite_session)

    worker_blocked = False
    original_audit = processor._audit

    def audit_hook(run_id, event_type, outcome, current_state, reason, metadata=None, standalone=True):
        nonlocal worker_blocked
        if event_type == "recovery_decision" and outcome == "not_invoked_proven":
            # While recovery holds coordination lease, attempt competing worker acquisition
            competing_lease_repo = SqlAlchemyLeaseRepository(sqlite_session)
            from src.execution.reliability.errors import LeaseAcquisitionError
            try:
                competing_lease_repo.acquire(f"run:{run_id}", "competing-execution-worker", 300)
            except LeaseAcquisitionError:
                worker_blocked = True
        return original_audit(run_id, event_type, outcome, current_state, reason, metadata, standalone)

    processor._audit = audit_hook

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req)

    assert res.status == RecoveryProcessingStatus.CONFIRMED_NOT_INVOKED
    assert res.action_taken == "recorded_finding_no_replay"
    assert worker_blocked is True


# Gap 2.2: Execution winning coordination blocks recovery
def test_recovery_execution_winning_coordination_blocks_recovery(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.CREATED)
    lease_repo = SqlAlchemyLeaseRepository(sqlite_session)
    lease_repo.acquire(f"run:{run.run_id}", "active-execution-worker", 300)
    sqlite_session.commit()

    processor = make_processor(sqlite_session)
    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req)

    assert res.status == RecoveryProcessingStatus.RECOVERY_BLOCKED
    assert res.action_taken == "none_lease_held"
    assert "active unexpired worker lease" in res.reason.lower()


# Gap 2.3: Race condition where run state transitioned before recovery acquires lease fails closed
def test_recovery_concurrent_state_transition_fails_closed(sqlite_session, base_spec, base_decision, base_app, monkeypatch):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.CREATED)
    processor = make_processor(sqlite_session)

    original_acquire = SqlAlchemyLeaseRepository.acquire

    def racing_acquire(self_repo, resource_id, owner_id, ttl_seconds):
        lease = original_acquire(self_repo, resource_id, owner_id, ttl_seconds)
        # Advance run state in the database right after acquire
        run_repo = SqlAlchemyRunRepository(sqlite_session)
        db_run = run_repo.get_run(run.run_id)
        run_repo.transition_state(run.run_id, db_run.version, LifecycleState.RUNNING, db_run)
        sqlite_session.commit()
        return lease

    monkeypatch.setattr(SqlAlchemyLeaseRepository, "acquire", racing_acquire)

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req)

    assert res.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res.action_taken == "state_changed_concurrently"
    assert "pre-intent guarantee no longer holds" in res.reason.lower()


# Gap 2.4: Lease expiration allows recovery to fence out stale worker token
def test_recovery_lease_expiration_and_stale_fencing_token(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.CREATED)
    lease_repo = SqlAlchemyLeaseRepository(sqlite_session)
    # Worker 1 acquires lease with 0 second TTL (immediately expired)
    worker1_lease = lease_repo.acquire(f"run:{run.run_id}", "stale-worker-1", 0)
    sqlite_session.commit()

    import time
    time.sleep(0.01)

    processor = make_processor(sqlite_session)
    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req)

    assert res.status == RecoveryProcessingStatus.CONFIRMED_NOT_INVOKED

    # Stale worker 1 attempts to use its old fencing token
    from src.execution.reliability.errors import LeaseOwnershipError
    with pytest.raises(LeaseOwnershipError):
        lease_repo.release(f"run:{run.run_id}", "stale-worker-1", worker1_lease.fencing_token)


# Gap 2.5: Coordination database failure fails closed
def test_recovery_coordination_database_failure_fails_closed(sqlite_session, base_spec, base_decision, base_app, monkeypatch):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.CREATED)
    processor = make_processor(sqlite_session)

    def failing_acquire(*args, **kwargs):
        raise RuntimeError("Database connection pool exhausted")

    monkeypatch.setattr(SqlAlchemyLeaseRepository, "acquire", failing_acquire)

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req)

    assert res.status == RecoveryProcessingStatus.OUTCOME_UNKNOWN
    assert res.action_taken == "none_lease_lookup_failed"
    assert "lease lookup error" in res.reason.lower()


# Gap 2.6: No false CONFIRMED_NOT_INVOKED when lease coordinator is missing
def test_recovery_no_lease_coordinator_blocks(sqlite_session, base_spec, base_decision, base_app):
    run = create_persisted_run(sqlite_session, base_spec, base_decision, state=LifecycleState.CREATED)
    processor = RecoveryProcessor(
        run_repository=SqlAlchemyRunRepository(sqlite_session),
        lease_repository=None,
        idempotency_repository=SqlAlchemyIdempotencyRepository(sqlite_session),
        transaction_boundary=SqlTransactionBoundary(sqlite_session),
        audit_repository=SqlAlchemyAuditRepository(sqlite_session),
    )

    req = RecoveryProcessingRequest(
        run_id=run.run_id,
        spec=base_spec,
        decision=base_decision,
        application=base_app
    )
    res = processor.process_recovery(req)

    assert res.status == RecoveryProcessingStatus.RECOVERY_BLOCKED
    assert res.action_taken == "none_no_lease_coordinator"
    assert "no lease repository configured" in res.reason.lower()


