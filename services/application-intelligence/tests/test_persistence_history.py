import pytest
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.execution.persistence.models import Base
from src.execution.persistence.repositories import (
    SqlAlchemyRunRepository,
    SqlTransactionBoundary
)

@pytest.fixture
def sqlite_session():
    # Use in-memory SQLite for deterministic unit tests of persistence
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()

def test_append_history_success(sqlite_session):
    repo = SqlAlchemyRunRepository(sqlite_session)
    run_id = str(uuid.uuid4())
    
    # Create the run first to satisfy foreign key constraint
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
    sqlite_session.commit()
    
    event_id = str(uuid.uuid4())
    history = type("MockHistory", (), {
        "event_id": event_id,
        "run_id": run_id,
        "previous_state": "CREATED",
        "new_state": "AUTHORIZATION_PENDING",
        "expected_version": 1,
        "new_version": 2,
        "actor": "user-1",
        "reason": "Test transition",
        "correlation_id": "corr-1",
        "causation_id": "cause-1"
    })
    
    repo.append_history(history)
    sqlite_session.commit()
    
    histories = repo.get_history(run_id)
    assert len(histories) == 1
    assert histories[0].event_id == event_id
    assert histories[0].run_id == run_id
    assert histories[0].previous_state == "CREATED"
    assert histories[0].new_state == "AUTHORIZATION_PENDING"
    assert histories[0].expected_version == 1
    assert histories[0].new_version == 2
    assert histories[0].actor == "user-1"
    assert histories[0].reason == "Test transition"
    assert histories[0].correlation_id == "corr-1"
    assert histories[0].causation_id == "cause-1"

def test_append_history_rollback_on_failure(sqlite_session):
    repo = SqlAlchemyRunRepository(sqlite_session)
    boundary = SqlTransactionBoundary(sqlite_session)
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
        
    event_id = str(uuid.uuid4())
    history = type("MockHistory", (), {
        "event_id": event_id,
        "run_id": run_id,
        "previous_state": "CREATED",
        "new_state": "AUTHORIZATION_PENDING",
        "expected_version": 1,
        "new_version": 2,
        "actor": "user-1",
        "reason": "Test transition",
        "correlation_id": "corr-1",
        "causation_id": "cause-1"
    })
    
    try:
        with boundary.transaction():
            # Update state
            run.state = "AUTHORIZATION_PENDING"
            run.version = 2
            repo.transition_state(run_id, 1, "AUTHORIZATION_PENDING", run)
            # Append history
            repo.append_history(history)
            # Simulate failure after appending history
            raise RuntimeError("Simulated failure")
    except RuntimeError:
        pass
        
    # Verify rollback
    v, s = repo.get_version_and_state(run_id)
    assert v == 1
    assert s == "CREATED"
    
    histories = repo.get_history(run_id)
    assert len(histories) == 0

def test_history_insertion_failure_propagates_to_caller(sqlite_session):
    repo = SqlAlchemyRunRepository(sqlite_session)
    run_id = str(uuid.uuid4())
    
    # Create the run to satisfy FK if it was enforced
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
    sqlite_session.commit()
    
    event_id = str(uuid.uuid4())
    history = type("MockHistory", (), {
        "event_id": event_id,
        "run_id": run_id,
        "previous_state": "CREATED",
        "new_state": "AUTHORIZATION_PENDING",
        "expected_version": 1,
        "new_version": 2,
        "actor": "user-1",
        "reason": None,
        "correlation_id": None,
        "causation_id": None
    })
    
    # Insert first time successfully
    repo.append_history(history)
    sqlite_session.commit()
    
    from sqlalchemy.exc import IntegrityError
    
    with pytest.raises(IntegrityError):
        # Insert again with same event_id will cause IntegrityError
        repo.append_history(history)
