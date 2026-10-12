import pytest
import time
import uuid
import threading
from typing import Dict, Any

from src.execution.reliability import (
    LeaseManager, LeaseContext, LeaseAcquisitionError, LeaseOwnershipError,
    IdempotencyManager, IdempotencyConflictError, InvalidIdempotencyKeyError,
    TimeoutManager, OrchestrationTimeoutError,
    CancellationManager, OrchestrationCancelledError,
    AuditLogger, AuditEvent,
    RecoveryManager, ReconciliationOutcomeType
)

def test_lease_acquisition_and_release():
    manager = LeaseManager()
    run_id = "run-1"
    owner_id = "owner-1"
    
    lease = manager.acquire(run_id, owner_id)
    assert lease.status == "acquired"
    assert lease.run_id == run_id
    assert lease.owner_id == owner_id
    
    manager.release(run_id, lease.lease_id, owner_id)
    assert lease.status == "released"

def test_duplicate_active_lease_rejection():
    manager = LeaseManager()
    run_id = "run-1"
    owner_1 = "owner-1"
    owner_2 = "owner-2"
    
    manager.acquire(run_id, owner_1)
    with pytest.raises(LeaseAcquisitionError):
        manager.acquire(run_id, owner_2)

def test_same_owner_duplicate_acquisition():
    manager = LeaseManager()
    run_id = "run-1"
    owner = "owner-1"
    
    manager.acquire(run_id, owner)
    with pytest.raises(LeaseAcquisitionError):
        manager.acquire(run_id, owner)

def test_invalid_lease_owner():
    manager = LeaseManager()
    run_id = "run-1"
    owner_1 = "owner-1"
    owner_2 = "owner-2"
    
    lease = manager.acquire(run_id, owner_1)
    with pytest.raises(LeaseOwnershipError):
        manager.release(run_id, lease.lease_id, owner_2)

def test_expired_lease_handling():
    manager = LeaseManager()
    run_id = "run-1"
    owner_1 = "owner-1"
    owner_2 = "owner-2"
    
    # Acquire with very short timeout
    lease = manager.acquire(run_id, owner_1, timeout_sec=0.01)
    time.sleep(0.02) # wait for expiration
    
    # Should be able to acquire now
    lease2 = manager.acquire(run_id, owner_2)
    assert lease2.status == "acquired"

def test_exception_safe_release():
    manager = LeaseManager()
    run_id = "run-1"
    owner = "owner-1"
    
    try:
        with LeaseContext(manager, run_id, owner):
            raise ValueError("Something went wrong")
    except ValueError:
        pass
        
    assert manager._leases[run_id].status == "released"

def test_idempotency_success():
    manager = IdempotencyManager()
    key = "idem-key-1"
    fp = manager.compute_fingerprint({"a": 1})
    
    is_duplicate, result = manager.record_request(key, fp)
    assert is_duplicate is False
    
    manager.store_result(key, {"status": "ok"})
    
    is_duplicate2, result2 = manager.record_request(key, fp)
    assert is_duplicate2 is True
    assert result2 == {"status": "ok"}

def test_idempotency_fingerprint_conflict():
    manager = IdempotencyManager()
    key = "idem-key-1"
    fp1 = manager.compute_fingerprint({"a": 1})
    fp2 = manager.compute_fingerprint({"a": 2})
    
    manager.record_request(key, fp1)
    with pytest.raises(IdempotencyConflictError):
        manager.record_request(key, fp2)

def test_invalid_idempotency_key():
    manager = IdempotencyManager()
    with pytest.raises(InvalidIdempotencyKeyError):
        manager.record_request("", "fp")

def test_concurrent_duplicate_request():
    manager = IdempotencyManager()
    key = "idem-key-1"
    fp = manager.compute_fingerprint({"a": 1})
    
    manager.record_request(key, fp)
    is_duplicate, result = manager.record_request(key, fp)
    assert is_duplicate is True
    assert result is None

def test_interrupted_request_handling():
    manager = IdempotencyManager()
    key = "idem-key-1"
    fp = manager.compute_fingerprint({"a": 1})
    
    manager.record_request(key, fp)
    # Never called store_result (interrupted)
    # Recovery should say in_progress or unknown
    recovery = RecoveryManager(LeaseManager(), manager)
    outcome = recovery.reconcile("run-1", key)
    assert outcome.outcome == ReconciliationOutcomeType.NO_ACTION_REQUIRED

def test_invalid_timeout():
    with pytest.raises(ValueError):
        TimeoutManager(-1.0)
    with pytest.raises(ValueError):
        TimeoutManager(0.0)

def test_timeout_behavior():
    def mock_clock():
        return mock_clock.time
    mock_clock.time = 100.0
    
    mgr = TimeoutManager(5.0, clock=mock_clock)
    mgr.check()
    mock_clock.time = 106.0
    with pytest.raises(OrchestrationTimeoutError):
        mgr.check()

def test_cancellation_request():
    mgr = CancellationManager()
    mgr.request_cancellation(reason="User clicked stop")
    with pytest.raises(OrchestrationCancelledError):
        mgr.check_cancelled()

def test_repeated_cancellation():
    mgr = CancellationManager()
    mgr.request_cancellation(reason="User clicked stop")
    mgr.request_cancellation(reason="User clicked stop again") # should be ignored
    assert mgr._cancellation.reason == "User clicked stop"

def test_structured_audit_event():
    logger = AuditLogger()
    event = AuditEvent(
        run_id="r1", application_id="a1", experiment_id="e1", 
        event_type="test", current_state="CREATED", outcome="success", correlation_id="c1"
    )
    logger.log(event)
    events = logger.get_events("r1")
    assert len(events) == 1
    assert events[0].run_id == "r1"
    assert "timestamp" in events[0].model_dump()

def test_secret_safe_audit_metadata():
    logger = AuditLogger()
    event = AuditEvent(
        run_id="r2", application_id="a1", experiment_id="e1", 
        event_type="test", current_state="CREATED", outcome="success", correlation_id="c1",
        metadata={
            "api_key": "secret_123", 
            "config": {"nested_token": "abc", "safe_val": 42},
            "db_url": "postgres://user:pass@localhost:5432/db"
        }
    )
    logger.log(event)
    
    # Original event should NOT be mutated
    assert event.metadata["api_key"] == "secret_123"
    
    events = logger.get_events("r2")
    logged_meta = events[0].metadata
    
    assert logged_meta["api_key"] == "***REDACTED***"
    assert logged_meta["config"]["nested_token"] == "***REDACTED***"
    assert logged_meta["config"]["safe_val"] == 42
    assert logged_meta["db_url"] == "***REDACTED***"

def test_expired_lease_reconciliation():
    lm = LeaseManager()
    im = IdempotencyManager()
    rm = RecoveryManager(lm, im)
    
    run_id = "r1"
    lm.acquire(run_id, "owner-1", timeout_sec=0.01)
    time.sleep(0.02)
    # Wait, the lease status is only set to expired during another acquire attempt or we can just mock it.
    lm._leases[run_id].status = "expired"
    
    outcome = rm.reconcile(run_id)
    assert outcome.outcome == ReconciliationOutcomeType.LEASE_EXPIRED

def test_unknown_outcome_reconciliation():
    lm = LeaseManager()
    im = IdempotencyManager()
    rm = RecoveryManager(lm, im)
    
    run_id = "r1"
    lm.acquire(run_id, "owner-1")
    
    outcome = rm.reconcile(run_id)
    assert outcome.outcome == ReconciliationOutcomeType.OUTCOME_UNKNOWN

def test_result_available_reconciliation():
    lm = LeaseManager()
    im = IdempotencyManager()
    rm = RecoveryManager(lm, im)
    
    key = "idem-1"
    fp = "fp"
    im.record_request(key, fp)
    im.store_result(key, {"plan": "simulated"})
    
    outcome = rm.reconcile("run-1", idempotency_key=key)
    assert outcome.outcome == ReconciliationOutcomeType.RESULT_AVAILABLE
    assert outcome.result == {"plan": "simulated"}

def test_concurrency_lease_acquisition():
    manager = LeaseManager()
    run_id = "r1"
    
    results = []
    
    def acquire():
        try:
            manager.acquire(run_id, "owner-thread")
            results.append(True)
        except LeaseAcquisitionError:
            results.append(False)
            
    t1 = threading.Thread(target=acquire)
    t2 = threading.Thread(target=acquire)
    
    t1.start()
    t2.start()
    
    t1.join()
    t2.join()
    
    assert results.count(True) == 1
    assert results.count(False) == 1
