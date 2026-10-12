import pytest
from datetime import datetime, timezone
import uuid
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.execution.persistence.models import (
    Base,
    ExperimentRunModel,
    RunTransitionHistoryModel,
    IdempotencyRecordModel,
    LeaseRecordModel,
    AuditEventModel,
    OutboxEventModel
)

# Use sqlite in memory just to test model construction, default constraints, and basic relationships.
# We do not pretend this tests Postgres locking.
@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    yield db
    db.close()

def test_experiment_run_model_creation(session):
    run_id = str(uuid.uuid4())
    run = ExperimentRunModel(
        id=run_id,
        application_id="app-1",
        experiment_id="exp-1",
        safety_decision_id="sd-1",
        state="CREATED",
        correlation_id="corr-1"
    )
    session.add(run)
    session.commit()
    
    assert run.version == 1
    assert run.metadata_payload == {}
    assert run.created_at is not None
    assert run.updated_at is not None

def test_run_transition_history(session):
    run_id = str(uuid.uuid4())
    run = ExperimentRunModel(
        id=run_id,
        application_id="app-1",
        experiment_id="exp-1",
        safety_decision_id="sd-1",
        state="CREATED",
        correlation_id="corr-1"
    )
    session.add(run)
    session.flush() # flush to get run in db for foreign key
    
    transition = RunTransitionHistoryModel(
        run_id=run.id,
        previous_state=None,
        new_state="CREATED",
        expected_version=0,
        new_version=1,
        actor="system"
    )
    session.add(transition)
    session.commit()
    
    assert transition.created_at is not None
    assert transition.run_id == run.id

def test_idempotency_record(session):
    record = IdempotencyRecordModel(
        application_id="app-1",
        operation_scope="start_run",
        idempotency_key_digest="digest-123",
        fingerprint="fp-123",
        owner_id="worker-1"
    )
    session.add(record)
    session.commit()
    
    assert record.status == "in_progress"
    assert record.terminal_result is None
    assert record.uncertain_outcome == 0

def test_lease_record(session):
    lease = LeaseRecordModel(
        resource_id="run-1",
        owner_id="worker-1",
        expires_at=datetime.now(timezone.utc)
    )
    session.add(lease)
    session.commit()
    
    assert lease.fencing_token == 1
    assert lease.acquired_at is not None

def test_audit_event(session):
    event = AuditEventModel(
        run_id="run-1",
        application_id="app-1",
        experiment_id="exp-1",
        event_type="STATE_CHANGE",
        outcome="success",
        actor="user-1"
    )
    session.add(event)
    session.commit()
    
    assert event.redacted_metadata == {}

def test_outbox_event(session):
    outbox = OutboxEventModel(
        event_type="run_completed",
        payload={"run_id": "123"}
    )
    session.add(outbox)
    session.commit()
    
    assert outbox.delivery_status == "pending"
    assert outbox.retry_count == 0

def test_added_constraints():
    # Verify the check constraints were added correctly
    idemp_args = [arg.name for arg in IdempotencyRecordModel.__table_args__ if hasattr(arg, 'name')]
    assert 'check_valid_idempotency_status' in idemp_args
    
    lease_args = [arg.name for arg in LeaseRecordModel.__table_args__ if hasattr(arg, 'name')]
    assert 'check_valid_lease_status' in lease_args
    
    outbox_args = [arg.name for arg in OutboxEventModel.__table_args__ if hasattr(arg, 'name')]
    assert 'check_valid_delivery_status' in outbox_args
    
    # Verify AuditEventModel run_id has foreign key
    assert len(AuditEventModel.run_id.property.columns[0].foreign_keys) == 1

