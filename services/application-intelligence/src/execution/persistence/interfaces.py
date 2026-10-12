from typing import Protocol, Optional, List, Dict, Any, Tuple
from contextlib import contextmanager

class IdempotencyConflictError(Exception):
    """Raised when an idempotency reservation fails due to a mismatched fingerprint."""
    pass


class RunRecord(Protocol):
    run_id: str
    application_id: str
    experiment_id: str
    state: str
    version: int
    safety_decision_id: str

class OptimisticConcurrencyError(Exception):
    """Raised when a state transition fails due to a version mismatch."""
    pass

class CommitUncertaintyError(Exception):
    """Raised when a transaction commit fails but the outcome on the server is unknown."""
    pass

class RunTransitionHistory(Protocol):
    event_id: str
    run_id: str
    previous_state: Optional[str]
    new_state: str
    expected_version: int
    new_version: int
    actor: str
    reason: Optional[str]
    correlation_id: Optional[str]
    causation_id: Optional[str]

class TransactionBoundary(Protocol):
    @contextmanager
    def transaction(self):
        """
        Context manager for grouping writes atomically.
        """
        ...

class FencedTransactionBoundary(Protocol):
    @contextmanager
    def fenced_transaction(self, resource_id: str, owner_id: str, fencing_token: int):
        """
        Context manager that atomically validates the lease's fencing token
        and groups writes. Raises LeaseOwnershipError if token is stale.
        """
        ...

from ...models.experiment_run import ExperimentRun

class RunRepository(Protocol):
    def create_run(self, run: ExperimentRun) -> None:
        ...

    def get_run(self, run_id: str) -> Optional[ExperimentRun]:
        ...

    def get_version_and_state(self, run_id: str) -> Optional[Tuple[int, str]]:
        ...

    def transition_state(self, run_id: str, expected_version: int, new_state: str, payload: ExperimentRun) -> ExperimentRun:
        """
        Updates state to new_state and increments version, asserting expected_version matches.
        Must be paired with an insert into transition history within a TransactionBoundary.
        Raises OptimisticConcurrencyError on version mismatch.
        """
        ...
        
    def append_history(self, history: RunTransitionHistory) -> None:
        """
        Appends a transition history record atomically.
        """
        ...
        
    def get_history(self, run_id: str) -> List[RunTransitionHistory]:
        ...


class IdempotencyRecordProtocol(Protocol):
    idempotency_key: str
    fingerprint: str
    status: str
    result: Optional[Any]
    owner_id: str
    uncertain_outcome: bool

class IdempotencyRepository(Protocol):
    def reserve(self, application_id: str, experiment_id: str, key: str, fingerprint: str, owner: str) -> Tuple[str, Optional[Any]]:
        """
        Returns (status, result). Status can be 'acquired', 'in_progress', 'completed'.
        Raises conflict error if fingerprint diverges.
        """
        ...
        
    def publish_result(self, application_id: str, experiment_id: str, key: str, owner: str, result: Any) -> None:
        """
        Writes terminal result. Raises error if owner doesn't match.
        """
        ...
        
    def get_result(self, application_id: str, experiment_id: str, key: str) -> Optional[Any]:
        ...

    def get_record(self, application_id: str, experiment_id: str, key: str) -> Optional[IdempotencyRecordProtocol]:
        ...


class LeaseRecordProtocol(Protocol):
    lease_id: str
    resource_id: str
    owner_id: str
    status: str
    version: int
    fencing_token: int
    expires_at: str

class LeaseRepository(Protocol):
    def acquire(self, resource_id: str, owner_id: str, ttl_seconds: int) -> LeaseRecordProtocol:
        """
        Returns acquired lease, incrementing fencing token atomically.
        Raises error if actively held.
        """
        ...
        
    def renew(self, resource_id: str, owner_id: str, fencing_token: int, ttl_seconds: int) -> None:
        ...
        
    def release(self, resource_id: str, owner_id: str, fencing_token: int) -> None:
        ...
        
    def validate_fencing_token(self, resource_id: str, token: int) -> bool:
        ...

    def is_active(self, resource_id: str) -> bool:
        ...


class AuditEventProtocol(Protocol):
    event_id: str
    run_id: str
    event_type: str
    metadata: Dict[str, Any]

class AuditRepository(Protocol):
    def append(self, event: AuditEventProtocol) -> None:
        """
        Appends an event to the audit log. Should be called within a TransactionBoundary.
        """
        ...
        
    def get_events(self, run_id: str) -> List[AuditEventProtocol]:
        ...
