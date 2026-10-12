import pytest
from datetime import datetime, timezone
import uuid
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
import threading

from src.execution.persistence.models import Base
from src.execution.persistence.repositories import (
    SqlAlchemyRunRepository,
    SqlAlchemyIdempotencyRepository,
    SqlAlchemyLeaseRepository,
    SqlAlchemyAuditRepository,
    SqlTransactionBoundary
)
from src.execution.persistence.db import init_db, get_engine, get_db_session

# Integration tests using Testcontainers
try:
    from testcontainers.postgres import PostgresContainer
    TESTCONTAINERS_AVAILABLE = True
except ImportError:
    TESTCONTAINERS_AVAILABLE = False

@pytest.fixture(scope="module")
def postgres_engine():
    if not TESTCONTAINERS_AVAILABLE:
        pytest.skip("testcontainers not available")
    
    try:
        postgres = PostgresContainer("postgres:15-alpine")
        postgres.start()
    except Exception as e:
        pytest.skip(f"Docker not available or failed to start container: {e}")
        
    db_url = postgres.get_connection_url()
    # testcontainers returns dialect+driver, sqlalchemy 2.0 prefers postgresql+psycopg
    if db_url.startswith("postgresql+psycopg2://"):
        db_url = db_url.replace("postgresql+psycopg2://", "postgresql+psycopg://")
    
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    
    yield engine
    
    postgres.stop()

@pytest.fixture
def db_session(postgres_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=postgres_engine)
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()

def test_idempotency_concurrent_duplicate(db_session):
    repo = SqlAlchemyIdempotencyRepository(db_session)
    app_id = "app-1"
    exp_id = "exp-1"
    key = "digest-1"
    fp = "fp-1"
    owner = "owner-1"
    
    # First attempt acquires
    status, result = repo.reserve(app_id, exp_id, key, fp, owner)
    assert status == "acquired"
    assert result is None
    
    # Second attempt gets in_progress
    status, result = repo.reserve(app_id, exp_id, key, fp, "owner-2")
    assert status == "in_progress"
    
    # Conflicting fingerprint gets rejected
    from src.execution.persistence.interfaces import IdempotencyConflictError
    with pytest.raises(IdempotencyConflictError, match="Fingerprint divergence"):
        repo.reserve(app_id, exp_id, key, "fp-2", "owner-3")
        
    # Owner publishes
    repo.publish_result(app_id, exp_id, key, owner, {"done": True})
    
    # Re-fetch gets completed
    status, result = repo.reserve(app_id, exp_id, key, fp, "owner-2")
    assert status == "completed"
    assert result == {"done": True}

def test_lease_acquisition_and_fencing(db_session):
    repo = SqlAlchemyLeaseRepository(db_session)
    res_id = "res-1"
    
    # Initial acquire
    lease = repo.acquire(res_id, "owner-1", ttl_seconds=60)
    assert lease.owner_id == "owner-1"
    assert lease.fencing_token == 1
    assert lease.status == "active"
    
    # Valid token check
    assert repo.validate_fencing_token(res_id, 1) is True
    
    # Stale token check
    assert repo.validate_fencing_token(res_id, 0) is False
    assert repo.validate_fencing_token(res_id, 2) is False
    
    # Competing worker fails to acquire
    with pytest.raises(ValueError, match="actively held"):
        repo.acquire(res_id, "owner-2", ttl_seconds=60)
        
    # Owner renews
    repo.renew(res_id, "owner-1", fencing_token=1, ttl_seconds=120)
    
    # Owner releases
    repo.release(res_id, "owner-1", fencing_token=1)
    
    # After release, validation fails
    assert repo.validate_fencing_token(res_id, 1) is False
    
    # Now owner-2 can acquire
    lease2 = repo.acquire(res_id, "owner-2", ttl_seconds=60)
    assert lease2.owner_id == "owner-2"
    assert lease2.fencing_token == 2
    assert repo.validate_fencing_token(res_id, 2) is True

def test_stale_expected_version_rejected(db_session):
    repo = SqlAlchemyRunRepository(db_session)
    run_id = str(uuid.uuid4())
    
    # Mock RunRecord
    from src.models.experiment_run import ExperimentRun
    run = ExperimentRun(**{
        "run_id": run_id,
        "application_id": "app-1",
        "experiment_id": "exp-1",
        "state": "CREATED",
        "version": 1,
        "safety_decision_id": "sd-1"
    })
    repo.create_run(run)
    db_session.commit()
    
    # Valid transition 1 -> 2
    run.state = "APPROVED"
    run.version = 2
    repo.transition_state(run_id, 1, "APPROVED", run)
    db_session.commit()
    
    v, s = repo.get_version_and_state(run_id)
    assert v == 2
    assert s == "APPROVED"
    
    # Stale transition 1 -> 2 again fails
    with pytest.raises(ValueError, match="Version mismatch"):
        run.state = "EXECUTING"
        run.version = 2
        repo.transition_state(run_id, 1, "EXECUTING", run)
    
    db_session.rollback()

def test_transaction_boundary_rollback(postgres_engine):
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=postgres_engine)
    session = SessionLocal()
    
    boundary = SqlTransactionBoundary(session)
    repo = SqlAlchemyRunRepository(session)
    run_id = str(uuid.uuid4())
    
    from src.models.experiment_run import ExperimentRun
    run = ExperimentRun(**{
        "run_id": run_id,
        "application_id": "app-1",
        "experiment_id": "exp-1",
        "state": "CREATED",
        "version": 1,
        "safety_decision_id": "sd-1"
    })
    
    with boundary.transaction():
        repo.create_run(run)
        
    v, s = repo.get_version_and_state(run_id)
    assert v == 1
    
    # Intentional failure inside transaction
    try:
        with boundary.transaction():
            run.state = "FAILING"
            run.version = 2
            repo.transition_state(run_id, 1, "FAILING", run)
            raise RuntimeError("Something went wrong")
    except RuntimeError:
        pass
        
    # Session state should be rolled back, state should still be CREATED
    # Using a new session to verify
    session.close()
    
    session2 = SessionLocal()
    repo2 = SqlAlchemyRunRepository(session2)
    v, s = repo2.get_version_and_state(run_id)
    assert v == 1
    assert s == "CREATED"
    session2.close()
