import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError
import uuid

from src.execution.persistence.models import Base
from src.execution.persistence.repositories import (
    SqlAlchemyIdempotencyRepository,
    SqlAlchemyLeaseRepository
)
from src.execution.persistence.interfaces import IdempotencyConflictError

@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    yield db
    db.close()

def test_reserve_does_not_rollback_parent_transaction(session):
    repo = SqlAlchemyIdempotencyRepository(session)
    
    # We want to ensure that if `flush()` raises IntegrityError (due to our simulated race),
    # the repository handles it and recovers WITHOUT rolling back the parent transaction.
    
    original_flush = session.flush
    flush_calls = [0]
    
    def mock_flush():
        flush_calls[0] += 1
        if flush_calls[0] == 1:
            raise IntegrityError("Mock", "Mock", "Mock")
        return original_flush()
        
    with patch.object(session, 'flush', side_effect=mock_flush):
        original_execute = session.execute
        
        execute_calls = [0]
        def mock_execute(stmt):
            execute_calls[0] += 1
            if execute_calls[0] == 2:
                # The second select is triggered by the recovery block.
                # We return a mock record.
                return type("MockResult", (), {
                    "scalar_one_or_none": lambda self: type("MockRecord", (), {
                        "fingerprint": "fp-1",
                        "status": "completed",
                        "terminal_result": {"ok": True}
                    })()
                })()
            return original_execute(stmt)
            
        with patch.object(session, 'execute', side_effect=mock_execute):
            status, result = repo.reserve("app-1", "exp-1", "key-1", "fp-1", "owner-1")
            
            assert status == "completed"
            assert result == {"ok": True}
            
            # THE CRITICAL ASSERTION: The session must still be active (i.e. no rollback on parent)
            assert session.is_active is True

def test_acquire_handles_concurrent_insert_gracefully(session):
    repo = SqlAlchemyLeaseRepository(session)
    
    # Simulate a concurrent insert. The first fetch returns None.
    # The insert attempt fails with IntegrityError (simulating race).
    # The retry block fetches the concurrently inserted lease and updates it.
    
    original_flush = session.flush
    flush_calls = [0]
    
    def mock_flush():
        flush_calls[0] += 1
        if flush_calls[0] == 1:
            raise IntegrityError("Mock", "Mock", "Mock")
        return original_flush()
        
    with patch.object(session, 'flush', side_effect=mock_flush):
        original_execute = session.execute
        
        execute_calls = [0]
        def custom_execute(stmt):
            execute_calls[0] += 1
            if execute_calls[0] == 1:
                return type("MockResult", (), {"scalar_one_or_none": lambda self: None})()
            elif execute_calls[0] == 2:
                return type("MockResult", (), {
                    "scalar_one_or_none": lambda self: type("MockLease", (), {
                        "id": "123",
                        "resource_id": "res-1",
                        "owner_id": "other-owner",
                        "status": "active",
                        "version": 1,
                        "fencing_token": 1,
                        "expires_at": datetime.now(timezone.utc)
                    })()
                })()
            return original_execute(stmt)
            
        with patch.object(session, 'execute', side_effect=custom_execute):
            lease = repo.acquire("res-1", "my-owner", 60)
            
            assert lease.owner_id == "my-owner"
            assert lease.version == 2
            assert lease.fencing_token == 2
            assert flush_calls[0] == 2

def test_reserve_conflict_raises_typed_error_and_preserves_parent_transaction(session):
    repo = SqlAlchemyIdempotencyRepository(session)
    
    # We want to ensure that if `flush()` raises IntegrityError (concurrent insert),
    # and the subsequent fetch reveals a different fingerprint,
    # it raises IdempotencyConflictError WITHOUT rolling back the parent transaction.
    
    original_flush = session.flush
    flush_calls = [0]
    
    def mock_flush():
        flush_calls[0] += 1
        if flush_calls[0] == 1:
            raise IntegrityError("Mock", "Mock", "Mock")
        return original_flush()
        
    with patch.object(session, 'flush', side_effect=mock_flush):
        original_execute = session.execute
        
        execute_calls = [0]
        def mock_execute(stmt):
            execute_calls[0] += 1
            if execute_calls[0] == 2:
                # The second select is triggered by the recovery block.
                # We return a mock record with a DIFFERENT fingerprint.
                return type("MockResult", (), {
                    "scalar_one_or_none": lambda self: type("MockRecord", (), {
                        "fingerprint": "different-fp",
                        "status": "completed",
                        "terminal_result": {"ok": True}
                    })()
                })()
            return original_execute(stmt)
            
        with patch.object(session, 'execute', side_effect=mock_execute):
            with pytest.raises(IdempotencyConflictError, match="Fingerprint divergence"):
                repo.reserve("app-1", "exp-1", "key-1", "my-fp", "owner-1")
            
            # THE CRITICAL ASSERTION: The session must still be active (i.e. no rollback on parent)
            assert session.is_active is True
            
            # Perform a subsequent valid write to prove the transaction is usable
            from src.execution.persistence.models import IdempotencyRecordModel
            session.execute = original_execute # restore execute
            session.add(IdempotencyRecordModel(
                application_id="app-valid", operation_scope="exp-valid",
                idempotency_key_digest="key-valid", fingerprint="fp-valid",
                owner_id="owner-valid"
            ))
            session.commit()
            
            record = session.execute(
                __import__('sqlalchemy').select(IdempotencyRecordModel).where(IdempotencyRecordModel.application_id == "app-valid")
            ).scalar_one_or_none()
            assert record is not None
            assert record.fingerprint == "fp-valid"
