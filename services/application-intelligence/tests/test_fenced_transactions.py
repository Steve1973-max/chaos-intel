import pytest
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.execution.persistence.models import Base, LeaseRecordModel, ExperimentRunModel, RunTransitionHistoryModel, IdempotencyRecordModel
from src.execution.persistence.repositories import (
    SqlAlchemyLeaseRepository, SqlAlchemyRunRepository, SqlAlchemyIdempotencyRepository, SqlTransactionBoundary
)
from src.execution.reliability.errors import LeaseAcquisitionError, LeaseOwnershipError
from src.execution.persistence.interfaces import OptimisticConcurrencyError
from src.models.experiment_run import ExperimentRun

@pytest.fixture
def sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()

def create_test_run(session, run_id="run-1", expected_version=1):
    repo = SqlAlchemyRunRepository(session)
    run = ExperimentRun(
        run_id=run_id,
        application_id="app-1",
        experiment_id="exp-1",
        state="CREATED",
        version=expected_version,
        safety_decision_id="decision-1"
    )
    repo.create_run(run)
    session.commit()
    return run

def test_fenced_write_success(sqlite_session):
    lease_repo = SqlAlchemyLeaseRepository(sqlite_session)
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)

    run = create_test_run(sqlite_session, run_id="run-1")
    lease = lease_repo.acquire("run-1", "owner-1", 60)

    with boundary.fenced_transaction("run-1", "owner-1", lease.fencing_token):
        run_repo.transition_state("run-1", 1, "AUTHORIZED", run)

    assert run_repo.get_run("run-1").state == "AUTHORIZED"

def test_fenced_write_incorrect_owner_rejected(sqlite_session):
    lease_repo = SqlAlchemyLeaseRepository(sqlite_session)
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)

    run = create_test_run(sqlite_session, run_id="run-2")
    lease = lease_repo.acquire("run-2", "owner-1", 60)

    with pytest.raises(LeaseOwnershipError, match="Stale or invalid fencing token"):
        with boundary.fenced_transaction("run-2", "owner-2", lease.fencing_token):
            run_repo.transition_state("run-2", 1, "AUTHORIZED", run)

    # State must not change
    assert run_repo.get_run("run-2").state == "CREATED"

def test_stale_owner_rejected_and_does_not_mutate(sqlite_session):
    lease_repo = SqlAlchemyLeaseRepository(sqlite_session)
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    idemp_repo = SqlAlchemyIdempotencyRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)

    run = create_test_run(sqlite_session, run_id="run-4")
    idemp_repo.reserve("app-1", "exp-1", "key-1", "fingerprint", "owner-1")
    sqlite_session.commit()

    # Owner 1 gets lease
    lease1 = lease_repo.acquire("run-4", "owner-1", 60)

    # Expire it manually
    model = sqlite_session.query(LeaseRecordModel).filter_by(resource_id="run-4").first()
    model.expires_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
    sqlite_session.commit()

    # Owner 2 gets lease
    lease2 = lease_repo.acquire("run-4", "owner-2", 60)

    # Owner 1 tries to write with token 1
    with pytest.raises(LeaseOwnershipError, match="Stale or invalid fencing token"):
        with boundary.fenced_transaction("run-4", "owner-1", lease1.fencing_token):
            run_repo.transition_state("run-4", 1, "AUTHORIZED", run)
            idemp_repo.publish_result("app-1", "exp-1", "key-1", "owner-1", {"res": "ok"})
            
    # Verify no partial commits
    assert run_repo.get_run("run-4").state == "CREATED"
    assert idemp_repo.get_result("app-1", "exp-1", "key-1") is None

def test_optimistic_concurrency_still_enforced(sqlite_session):
    lease_repo = SqlAlchemyLeaseRepository(sqlite_session)
    run_repo = SqlAlchemyRunRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)

    run = create_test_run(sqlite_session, run_id="run-5")
    lease = lease_repo.acquire("run-5", "owner-1", 60)

    with pytest.raises(OptimisticConcurrencyError):
        with boundary.fenced_transaction("run-5", "owner-1", lease.fencing_token):
            # Pass wrong expected_version
            run_repo.transition_state("run-5", 99, "AUTHORIZED", run)
