from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel
from .leases import LeaseManager
from .idempotency import IdempotencyManager

class ReconciliationOutcomeType(str, Enum):
    NO_ACTION_REQUIRED = "no_action_required"
    LEASE_EXPIRED = "lease_expired"
    RESULT_AVAILABLE = "result_available"
    OUTCOME_UNKNOWN = "outcome_unknown"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"

class ReconciliationOutcome(BaseModel):
    outcome: ReconciliationOutcomeType
    result: Optional[Any] = None
    reason: str

class RecoveryManager:
    """
    Recovery and reconciliation for interrupted orchestration requests.
    In-memory state is lost after process restart.
    """
    def __init__(self, lease_manager: LeaseManager, idempotency_manager: IdempotencyManager):
        self.lease_manager = lease_manager
        self.idempotency_manager = idempotency_manager

    def reconcile(self, run_id: str, idempotency_key: Optional[str] = None) -> ReconciliationOutcome:
        # Check idempotency first
        if idempotency_key:
            with self.idempotency_manager._lock:
                if idempotency_key in self.idempotency_manager._records:
                    record = self.idempotency_manager._records[idempotency_key]
                    if record.status == "completed":
                        return ReconciliationOutcome(
                            outcome=ReconciliationOutcomeType.RESULT_AVAILABLE,
                            result=record.result,
                            reason="Result found in idempotency store."
                        )
        
        # Check lease state
        with self.lease_manager._lock:
            if run_id in self.lease_manager._leases:
                lease = self.lease_manager._leases[run_id]
                if lease.status == "expired":
                    return ReconciliationOutcome(
                        outcome=ReconciliationOutcomeType.LEASE_EXPIRED,
                        reason="Lease expired without completion. May need to be restarted."
                    )
                elif lease.status == "acquired":
                    return ReconciliationOutcome(
                        outcome=ReconciliationOutcomeType.OUTCOME_UNKNOWN,
                        reason="Active lease found, but outcome is unknown or in progress."
                    )
                elif lease.status == "released":
                    return ReconciliationOutcome(
                        outcome=ReconciliationOutcomeType.NO_ACTION_REQUIRED,
                        reason="Lease was released normally."
                    )
                    
        return ReconciliationOutcome(
            outcome=ReconciliationOutcomeType.NO_ACTION_REQUIRED,
            reason="No tracking records found."
        )
