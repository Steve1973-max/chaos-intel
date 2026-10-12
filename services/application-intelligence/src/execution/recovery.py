from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, Any, Dict, List
from .states import LifecycleState
from ..models.experiment_run import ExperimentRun

class RecoveryClassification(str, Enum):
    NOT_INVOKED_PROVEN = "NOT_INVOKED_PROVEN"
    INVOCATION_POSSIBLE = "INVOCATION_POSSIBLE"
    OUTCOME_CONFIRMED = "OUTCOME_CONFIRMED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"

class RecoveryClassifier:
    @classmethod
    def classify(cls, run: Optional[ExperimentRun], has_authoritative_state: bool) -> RecoveryClassification:
        """
        Deterministically classifies the recovery state based on durable evidence.
        
        A state durably preceding execution intent may be classified as NOT_INVOKED_PROVEN 
        only because the execution-intent prerequisite invariant guarantees invocation cannot happen
        without transitioning past AUTHORIZED.
        
        SETUP and any later state must be classified conservatively as INVOCATION_POSSIBLE
        unless authoritative evidence establishes a terminal outcome.
        """
        if not has_authoritative_state or run is None:
            # Missing authoritative state or database unreachable
            return RecoveryClassification.OUTCOME_UNKNOWN
            
        terminal_states = {
            LifecycleState.COMPLETED, 
            LifecycleState.FAILED, 
            LifecycleState.ABORTED, 
            LifecycleState.ROLLBACK_FAILED, 
            LifecycleState.RECOVERY_FAILED
        }
        
        if run.state in terminal_states:
            return RecoveryClassification.OUTCOME_CONFIRMED
            
        pre_intent_states = {
            LifecycleState.CREATED, 
            LifecycleState.PREFLIGHT, 
            LifecycleState.AUTHORIZATION_PENDING, 
            LifecycleState.AUTHORIZED
        }
        
        if run.state in pre_intent_states:
            return RecoveryClassification.NOT_INVOKED_PROVEN
            
        # Any active state post-intent (e.g. SETUP, RUNNING, RECOVERY_CHECK, etc.)
        return RecoveryClassification.INVOCATION_POSSIBLE

class RecoveryResultVariant(str, Enum):
    CONFIRMED_SUCCESS = "ConfirmedSuccess"
    CONFIRMED_FAILURE = "ConfirmedFailure"
    CONFIRMED_ROLLBACK = "ConfirmedRollback"
    INCONCLUSIVE = "Inconclusive"

class RecoveryResult(BaseModel):
    variant: RecoveryResultVariant
    run_id: str
    message: Optional[str] = None
    
    def validate_for_run(self, expected_run_id: str):
        if self.run_id != expected_run_id:
            raise ValueError(f"Reconciliation result run_id '{self.run_id}' does not match expected run_id '{expected_run_id}'")


class RecoveryProcessingStatus(str, Enum):
    CONFIRMED_NOT_INVOKED = "CONFIRMED_NOT_INVOKED"
    INVOCATION_POSSIBLE_RECONCILIATION_REQUIRED = "INVOCATION_POSSIBLE_RECONCILIATION_REQUIRED"
    OUTCOME_CONFIRMED = "OUTCOME_CONFIRMED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    RECOVERY_BLOCKED = "RECOVERY_BLOCKED"


class RecoveryProcessingRequest(BaseModel):
    run_id: str
    idempotency_key: Optional[str] = None
    expected_fingerprint: Optional[str] = None
    expected_owner: Optional[str] = None
    worker_id: Optional[str] = None
    recovery_ttl_sec: int = 300
    spec: Optional[Any] = None
    decision: Optional[Any] = None
    application: Optional[Any] = None


class RecoveryProcessingResult(BaseModel):
    run_id: str
    status: RecoveryProcessingStatus
    classification: RecoveryClassification
    action_taken: str
    reason: str
    current_state: Optional[str] = None
    fencing_token: Optional[int] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class RecoveryProcessor:
    """
    Phase 2C.5C: Safe Recovery-Processing Service.
    
    Coordinates the recovery of interrupted experiment runs using:
    - Authoritative persisted durable state
    - RecoveryClassifier determination
    - Idempotency record cross-corroboration
    - Lease acquisition and fencing tokens
    - State revalidation inside protected transaction boundaries
    - Atomic audit logging
    - Strictly zero automatic replays
    """

    def __init__(
        self,
        run_repository=None,
        lease_repository=None,
        idempotency_repository=None,
        audit_repository=None,
        transaction_boundary=None,
        audit_logger=None
    ):
        self.run_repository = run_repository
        self.lease_repository = lease_repository
        self.idempotency_repository = idempotency_repository
        self.audit_repository = audit_repository
        self.transaction_boundary = transaction_boundary
        self.audit_logger = audit_logger

    @staticmethod
    def _redact(data: Any) -> Any:
        import copy
        secret_keys = {
            "password", "secret", "token", "api_key", "private_key",
            "access_key", "credential", "authorization", "client_secret", "connection_string"
        }
        if isinstance(data, dict):
            redacted = {}
            for k, v in data.items():
                if any(sec in str(k).lower() for sec in secret_keys):
                    redacted[k] = "***REDACTED***"
                else:
                    redacted[k] = RecoveryProcessor._redact(v)
            return redacted
        elif isinstance(data, list):
            return [RecoveryProcessor._redact(item) for item in data]
        elif isinstance(data, str) and any(scheme in data.lower() for scheme in ["mongodb://", "postgres://", "mysql://"]):
            return "***REDACTED***"
        return copy.deepcopy(data)

    def _is_active_lease_held(self, resource_id: str) -> bool:
        if not self.lease_repository:
            return False
        if hasattr(self.lease_repository, "is_active"):
            return bool(self.lease_repository.is_active(resource_id))
        if hasattr(self.lease_repository, "session") and self.lease_repository.session is not None:
            from sqlalchemy import select
            from datetime import datetime, timezone
            from .persistence.models import LeaseRecordModel
            stmt = select(LeaseRecordModel.status, LeaseRecordModel.expires_at).where(LeaseRecordModel.resource_id == resource_id)
            row = self.lease_repository.session.execute(stmt).first()
            if not row:
                return False
            now = datetime.now(timezone.utc)
            expires_at = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
            return row.status == "active" and expires_at > now
        return False

    def _audit(self, run_id: str, event_type: str, outcome: str, current_state: Optional[str], reason: str, metadata: Optional[Dict[str, Any]] = None, standalone: bool = True):
        import uuid
        safe_meta = self._redact(metadata or {})
        
        if self.audit_repository:
            audit_evt = type("AuditEventImpl", (), {
                "event_id": str(uuid.uuid4()),
                "run_id": run_id,
                "event_type": event_type,
                "metadata": {"outcome": outcome, "current_state": current_state, "reason": reason, **safe_meta}
            })
            if standalone:
                if hasattr(self.audit_repository, "append_durable"):
                    self.audit_repository.append_durable(audit_evt)
                elif hasattr(self.audit_repository, "session") and self.audit_repository.session is not None:
                    bind = getattr(self.audit_repository.session, "bind", None) or (self.audit_repository.session.get_bind() if hasattr(self.audit_repository.session, "get_bind") else None)
                    if bind is not None:
                        from sqlalchemy.orm import Session as OrmSession
                        from .persistence.models import AuditEventModel
                        with OrmSession(bind) as isolated_session:
                            model = AuditEventModel(
                                id=audit_evt.event_id,
                                run_id=audit_evt.run_id,
                                event_type=audit_evt.event_type,
                                outcome="recorded",
                                actor="system",
                                redacted_metadata=audit_evt.metadata
                            )
                            isolated_session.add(model)
                            isolated_session.commit()
                    else:
                        self.audit_repository.append(audit_evt)
                else:
                    self.audit_repository.append(audit_evt)
            else:
                self.audit_repository.append(audit_evt)

        if self.audit_logger:
            from .reliability.audit import AuditEvent
            try:
                self.audit_logger.log(AuditEvent(
                    run_id=run_id,
                    application_id="unknown",
                    experiment_id="unknown",
                    event_type=event_type,
                    current_state=current_state or "UNKNOWN",
                    outcome=outcome,
                    reason=reason,
                    correlation_id=run_id,
                    metadata=safe_meta
                ))
            except Exception:
                pass

    def process_recovery(self, request: RecoveryProcessingRequest, adapter=None) -> RecoveryProcessingResult:
        import uuid
        from datetime import datetime, timezone
        from .transitions import assert_valid_transition
        from .persistence.interfaces import OptimisticConcurrencyError, CommitUncertaintyError
        from .reliability.errors import LeaseAcquisitionError, LeaseOwnershipError

        worker_id = request.worker_id or str(uuid.uuid4())
        lease_resource_id = f"run:{request.run_id}"

        # Step 1: Authoritative run state loading
        if self.run_repository is None:
            return RecoveryProcessingResult(
                run_id=request.run_id,
                status=RecoveryProcessingStatus.RECOVERY_BLOCKED,
                classification=RecoveryClassification.OUTCOME_UNKNOWN,
                action_taken="none_unsupported",
                reason="No run repository configured; cannot load authoritative persisted state."
            )

        try:
            db_run = self.run_repository.get_run(request.run_id)
        except Exception as e:
            return RecoveryProcessingResult(
                run_id=request.run_id,
                status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                classification=RecoveryClassification.OUTCOME_UNKNOWN,
                action_taken="none_db_error",
                reason=f"Failed to load authoritative run: {e}"
            )

        if db_run is None:
            return RecoveryProcessingResult(
                run_id=request.run_id,
                status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                classification=RecoveryClassification.OUTCOME_UNKNOWN,
                action_taken="none_run_not_found",
                reason=f"Run '{request.run_id}' not found in authoritative storage."
            )

        # Step 2: Apply RecoveryClassifier
        classification = RecoveryClassifier.classify(db_run, has_authoritative_state=True)

        # Step 3: Branch on classification
        # Branch A: NOT_INVOKED_PROVEN
        if classification == RecoveryClassification.NOT_INVOKED_PROVEN:
            # Coordination with lease acquisition:
            # Point-in-time check is insufficient to guarantee that no worker acquires a lease
            # before CONFIRMED_NOT_INVOKED is returned.
            # Recovery coordinates with execution workers using the shared authoritative lease protocol.
            # CONFIRMED_NOT_INVOKED requires:
            # 1. Historical proof: Run is in pre-intent state (CREATED/AUTHORIZED), so adapter was never invoked.
            # 2. Concurrency barrier: Exclusive lease run:{run_id} is actively held by recovery, so no worker
            #    can concurrently begin execution while this decision is verified and audited.
            recovery_lease = None
            if self.lease_repository is None:
                return RecoveryProcessingResult(
                    run_id=db_run.run_id,
                    status=RecoveryProcessingStatus.RECOVERY_BLOCKED,
                    classification=classification,
                    action_taken="none_no_lease_coordinator",
                    reason=f"No lease repository configured; cannot coordinate mutual exclusion for run '{db_run.run_id}'.",
                    current_state=db_run.state
                )

            coord_lease_repo = self.lease_repository
            isolated_lease_session = None
            if hasattr(self.lease_repository, "session") and self.lease_repository.session is not None:
                bind = getattr(self.lease_repository.session, "bind", None) or (
                    self.lease_repository.session.get_bind() if hasattr(self.lease_repository.session, "get_bind") else None
                )
                if bind is not None:
                    from sqlalchemy.orm import Session as OrmSession
                    isolated_lease_session = OrmSession(bind)
                    coord_lease_repo = type(self.lease_repository)(isolated_lease_session)

            try:
                # Retain point-in-time check delegation for backward compatibility
                if self._is_active_lease_held(lease_resource_id):
                    raise LeaseAcquisitionError(f"Resource {lease_resource_id} is already actively held")

                recovery_lease = coord_lease_repo.acquire(
                    lease_resource_id, worker_id, request.recovery_ttl_sec
                )
                if isolated_lease_session is not None:
                    isolated_lease_session.commit()
            except LeaseAcquisitionError as e:
                try:
                    self._audit(
                        run_id=db_run.run_id,
                        event_type="recovery_blocked",
                        outcome="lease_held",
                        current_state=db_run.state,
                        reason="Pre-intent run cannot be confirmed non-invoked while an active worker lease is held."
                    )
                except Exception:
                    pass
                return RecoveryProcessingResult(
                    run_id=db_run.run_id,
                    status=RecoveryProcessingStatus.RECOVERY_BLOCKED,
                    classification=classification,
                    action_taken="none_lease_held",
                    reason=f"Run '{db_run.run_id}' has an active unexpired worker lease on '{lease_resource_id}'. Active ownership cannot be ruled out.",
                    current_state=db_run.state
                )
            except Exception as e:
                try:
                    self._audit(
                        run_id=db_run.run_id,
                        event_type="recovery_lease_lookup_failed",
                        outcome="error",
                        current_state=db_run.state,
                        reason=f"Lease lookup failed during pre-intent recovery check: {e}."
                    )
                except Exception:
                    pass
                return RecoveryProcessingResult(
                    run_id=db_run.run_id,
                    status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                    classification=classification,
                    action_taken="none_lease_lookup_failed",
                    reason=f"Lease lookup error on '{lease_resource_id}': {e}. Active worker ownership cannot be ruled out.",
                    current_state=db_run.state
                )

            try:
                # Re-verify the authoritative persisted state while holding the mutual-exclusion lease
                fresh_run = self.run_repository.get_run(request.run_id)
                if not fresh_run:
                    return RecoveryProcessingResult(
                        run_id=request.run_id,
                        status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                        classification=classification,
                        action_taken="none_run_not_found",
                        reason=f"Run '{request.run_id}' not found in authoritative storage during pre-intent lease coordination.",
                        current_state=None
                    )

                fresh_classification = RecoveryClassifier.classify(fresh_run, has_authoritative_state=True)
                if fresh_classification != RecoveryClassification.NOT_INVOKED_PROVEN:
                    return RecoveryProcessingResult(
                        run_id=fresh_run.run_id,
                        status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                        classification=fresh_classification,
                        action_taken="state_changed_concurrently",
                        reason=f"Run state changed to '{fresh_run.state}' during coordination. Pre-intent guarantee no longer holds.",
                        current_state=fresh_run.state
                    )

                try:
                    self._audit(
                        run_id=fresh_run.run_id,
                        event_type="recovery_decision",
                        outcome="not_invoked_proven",
                        current_state=fresh_run.state,
                        reason="Pre-intent state confirmed; no active worker lease. Execution intent was never crossed. No automatic replay.",
                        metadata={"fencing_token": recovery_lease.fencing_token if recovery_lease else None}
                    )
                except Exception as e:
                    return RecoveryProcessingResult(
                        run_id=fresh_run.run_id,
                        status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                        classification=classification,
                        action_taken="none_audit_write_failed",
                        reason=f"Failed to durably record audit event: {e}",
                        current_state=fresh_run.state
                    )

                return RecoveryProcessingResult(
                    run_id=fresh_run.run_id,
                    status=RecoveryProcessingStatus.CONFIRMED_NOT_INVOKED,
                    classification=classification,
                    action_taken="recorded_finding_no_replay",
                    reason=f"Run '{fresh_run.run_id}' is in pre-intent state '{fresh_run.state}'. Invocation was not possible. No replay occurred.",
                    current_state=fresh_run.state,
                    fencing_token=recovery_lease.fencing_token if recovery_lease else None
                )
            finally:
                if recovery_lease and coord_lease_repo:
                    try:
                        coord_lease_repo.release(lease_resource_id, worker_id, recovery_lease.fencing_token)
                        if isolated_lease_session is not None:
                            isolated_lease_session.commit()
                    except Exception:
                        pass
                if isolated_lease_session is not None:
                    try:
                        isolated_lease_session.close()
                    except Exception:
                        pass

        # Branch B: OUTCOME_CONFIRMED
        if classification == RecoveryClassification.OUTCOME_CONFIRMED:
            # Corroborate idempotency record if key provided and repository available
            if request.idempotency_key and self.idempotency_repository:
                idemp_record = None
                if hasattr(self.idempotency_repository, "get_record"):
                    idemp_record = self.idempotency_repository.get_record(
                        db_run.application_id, db_run.experiment_id, request.idempotency_key
                    )
                else:
                    stored = self.idempotency_repository.get_result(
                        db_run.application_id, db_run.experiment_id, request.idempotency_key
                    )
                    if stored is not None:
                        idemp_record = type("SimpleRecord", (), {"status": "completed", "result": stored, "fingerprint": None, "owner_id": request.expected_owner, "uncertain_outcome": False})()

                if idemp_record is None:
                    # Missing idempotency record
                    try:
                        self._audit(
                            run_id=db_run.run_id,
                            event_type="recovery_inconsistency",
                            outcome="missing_idempotency_record",
                            current_state=db_run.state,
                            reason=f"Terminal run lacks expected idempotency record for key '{request.idempotency_key}'."
                        )
                    except Exception:
                        pass
                    return RecoveryProcessingResult(
                        run_id=db_run.run_id,
                        status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                        classification=RecoveryClassification.OUTCOME_UNKNOWN,
                        action_taken="flagged_inconsistency",
                        reason=f"Inconsistent state: run '{db_run.run_id}' is terminal ('{db_run.state}') but lacks idempotency record for key '{request.idempotency_key}'.",
                        current_state=db_run.state
                    )

                if request.expected_fingerprint and getattr(idemp_record, "fingerprint", None) and idemp_record.fingerprint != request.expected_fingerprint:
                    # Fingerprint mismatch
                    try:
                        self._audit(
                            run_id=db_run.run_id,
                            event_type="recovery_inconsistency",
                            outcome="fingerprint_mismatch",
                            current_state=db_run.state,
                            reason="Idempotency fingerprint mismatch."
                        )
                    except Exception:
                        pass
                    return RecoveryProcessingResult(
                        run_id=db_run.run_id,
                        status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                        classification=RecoveryClassification.OUTCOME_UNKNOWN,
                        action_taken="flagged_inconsistency",
                        reason=f"Inconsistent state: idempotency fingerprint mismatch (expected '{request.expected_fingerprint}', recorded '{idemp_record.fingerprint}').",
                        current_state=db_run.state
                    )

                # Authoritative owner verification:
                # The expected owner must be established strictly from an independent, authoritative source:
                # 1. request.expected_owner (authoritative reservation contract passed into recovery request)
                # 2. db_run.metadata.get("owner_id") (immutable contract recorded prior to execution by orchestrator)
                #
                # Under NO circumstances may db_run.metadata.get("idempotency_owner") or any value
                # written/manufactured by recovery be accepted as proof of original reservation ownership.
                expected_owner = (
                    request.expected_owner
                    or (db_run.metadata.get("owner_id") if isinstance(getattr(db_run, "metadata", None), dict) else None)
                )
                record_owner = getattr(idemp_record, "owner_id", None)
                if not expected_owner or not record_owner or record_owner != expected_owner:
                    try:
                        self._audit(
                            run_id=db_run.run_id,
                            event_type="recovery_inconsistency",
                            outcome="owner_mismatch_or_unknown",
                            current_state=db_run.state,
                            reason=f"Idempotency record owner mismatch or unestablished (expected '{expected_owner}', recorded '{record_owner}')."
                        )
                    except Exception:
                        pass
                    return RecoveryProcessingResult(
                        run_id=db_run.run_id,
                        status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                        classification=RecoveryClassification.OUTCOME_UNKNOWN,
                        action_taken="flagged_inconsistency",
                        reason=f"Inconsistent state: idempotency record owner mismatch or unestablished (expected '{expected_owner}', recorded '{record_owner}').",
                        current_state=db_run.state
                    )

                # Status must be exactly completed
                if getattr(idemp_record, "status", None) != "completed":
                    try:
                        self._audit(
                            run_id=db_run.run_id,
                            event_type="recovery_inconsistency",
                            outcome="status_not_completed",
                            current_state=db_run.state,
                            reason=f"Terminal run contradicts non-completed idempotency reservation status '{getattr(idemp_record, 'status', None)}'."
                        )
                    except Exception:
                        pass
                    return RecoveryProcessingResult(
                        run_id=db_run.run_id,
                        status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                        classification=RecoveryClassification.OUTCOME_UNKNOWN,
                        action_taken="flagged_inconsistency",
                        reason=f"Contradictory state: run '{db_run.run_id}' is terminal ('{db_run.state}') but idempotency status is '{getattr(idemp_record, 'status', None)}'.",
                        current_state=db_run.state
                    )

                # Uncertain outcome check
                if bool(getattr(idemp_record, "uncertain_outcome", False)):
                    try:
                        self._audit(
                            run_id=db_run.run_id,
                            event_type="recovery_inconsistency",
                            outcome="uncertain_outcome",
                            current_state=db_run.state,
                            reason="Terminal run idempotency record has uncertain_outcome set."
                        )
                    except Exception:
                        pass
                    return RecoveryProcessingResult(
                        run_id=db_run.run_id,
                        status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                        classification=RecoveryClassification.OUTCOME_UNKNOWN,
                        action_taken="flagged_inconsistency",
                        reason=f"Contradictory state: idempotency record has uncertain_outcome set for key '{request.idempotency_key}'.",
                        current_state=db_run.state
                    )

                # Terminal result structure and outcome agreement
                term_result = getattr(idemp_record, "result", None)
                if term_result is None or not isinstance(term_result, dict):
                    try:
                        self._audit(
                            run_id=db_run.run_id,
                            event_type="recovery_inconsistency",
                            outcome="invalid_terminal_result_structure",
                            current_state=db_run.state,
                            reason="Terminal idempotency record lacks structured result dictionary."
                        )
                    except Exception:
                        pass
                    return RecoveryProcessingResult(
                        run_id=db_run.run_id,
                        status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                        classification=RecoveryClassification.OUTCOME_UNKNOWN,
                        action_taken="flagged_inconsistency",
                        reason=f"Inconsistent state: terminal idempotency result is missing or non-dictionary for key '{request.idempotency_key}'.",
                        current_state=db_run.state
                    )

                result_status = term_result.get("status")
                if not result_status or result_status != db_run.state:
                    try:
                        self._audit(
                            run_id=db_run.run_id,
                            event_type="recovery_inconsistency",
                            outcome="conflicting_terminal_result",
                            current_state=db_run.state,
                            reason=f"Terminal result status '{result_status}' disagrees with authoritative run state '{db_run.state}'."
                        )
                    except Exception:
                        pass
                    return RecoveryProcessingResult(
                        run_id=db_run.run_id,
                        status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                        classification=RecoveryClassification.OUTCOME_UNKNOWN,
                        action_taken="flagged_inconsistency",
                        reason=f"Contradictory state: terminal result outcome '{result_status}' disagrees with run state '{db_run.state}'.",
                        current_state=db_run.state
                    )

                # Corroborated!
                try:
                    self._audit(
                        run_id=db_run.run_id,
                        event_type="recovery_decision",
                        outcome="outcome_confirmed",
                        current_state=db_run.state,
                        reason="Authoritative run and idempotency publication verified consistent."
                    )
                except Exception as e:
                    return RecoveryProcessingResult(
                        run_id=db_run.run_id,
                        status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                        classification=classification,
                        action_taken="none_audit_write_failed",
                        reason=f"Failed to record durable audit: {e}",
                        current_state=db_run.state
                    )

                return RecoveryProcessingResult(
                    run_id=db_run.run_id,
                    status=RecoveryProcessingStatus.OUTCOME_CONFIRMED,
                    classification=classification,
                    action_taken="corroborated_terminal_outcome",
                    reason=f"Authoritative run state '{db_run.state}' and idempotency record are corroborated and consistent.",
                    current_state=db_run.state,
                    details={"idempotency_status": idemp_record.status, "result_available": True}
                )

            # No idempotency key provided: dry-run boundary confirmation
            try:
                self._audit(
                    run_id=db_run.run_id,
                    event_type="recovery_decision",
                    outcome="outcome_confirmed",
                    current_state=db_run.state,
                    reason="Authoritative terminal run state confirmed without idempotency key."
                )
            except Exception as e:
                return RecoveryProcessingResult(
                    run_id=db_run.run_id,
                    status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                    classification=classification,
                    action_taken="none_audit_write_failed",
                    reason=f"Failed to record durable audit: {e}",
                    current_state=db_run.state
                )

            return RecoveryProcessingResult(
                run_id=db_run.run_id,
                status=RecoveryProcessingStatus.OUTCOME_CONFIRMED,
                classification=classification,
                action_taken="confirmed_terminal_run",
                reason=f"Run '{db_run.run_id}' is in authoritative terminal state '{db_run.state}'. Dry-run boundary.",
                current_state=db_run.state
            )

        # Branch C: INVOCATION_POSSIBLE
        if classification == RecoveryClassification.INVOCATION_POSSIBLE:
            if adapter is None:
                # Cannot verify recovery without an adapter providing authoritative evidence
                self._audit(
                    run_id=db_run.run_id,
                    event_type="recovery_decision",
                    outcome="inconclusive_no_adapter",
                    current_state=db_run.state,
                    reason="No execution adapter available to verify recovery evidence."
                )
                return RecoveryProcessingResult(
                    run_id=db_run.run_id,
                    status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                    classification=classification,
                    action_taken="none_no_adapter",
                    reason="No execution adapter provided for read-only reconciliation. Operation remains unresolved.",
                    current_state=db_run.state
                )

            # Adapter is available: execute read-only verification OUTSIDE database transaction
            from .adapters.context import ExecutionContext
            context = ExecutionContext(
                run=db_run,
                experiment=request.spec,
                safety_decision=request.decision,
                application_model=request.application,
                adapter_id=adapter.capabilities().adapter_id,
                correlation_id=db_run.run_id
            )

            try:
                recon_result = adapter.verify_recovery(context)
                recon_result.validate_for_run(db_run.run_id)
            except Exception as e:
                self._audit(
                    run_id=db_run.run_id,
                    event_type="recovery_reconciliation_failed",
                    outcome="error",
                    current_state=db_run.state,
                    reason=str(e)
                )
                return RecoveryProcessingResult(
                    run_id=db_run.run_id,
                    status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                    classification=classification,
                    action_taken="reconciliation_error",
                    reason=f"Adapter reconciliation error: {e}",
                    current_state=db_run.state
                )

            if recon_result.variant == RecoveryResultVariant.INCONCLUSIVE:
                self._audit(
                    run_id=db_run.run_id,
                    event_type="recovery_decision",
                    outcome="inconclusive",
                    current_state=db_run.state,
                    reason=f"Adapter '{adapter.capabilities().adapter_id}' reconciliation inconclusive."
                )
                return RecoveryProcessingResult(
                    run_id=db_run.run_id,
                    status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                    classification=classification,
                    action_taken="preserved_unresolved_state",
                    reason=f"Adapter '{adapter.capabilities().adapter_id}' reconciliation was inconclusive: {recon_result.message or 'No external evidence'}. State and idempotency reservation preserved.",
                    current_state=db_run.state
                )

            # Outcome confirmed by adapter evidence: CONFIRMED_SUCCESS, CONFIRMED_FAILURE, CONFIRMED_ROLLBACK
            target_state_map = {
                RecoveryResultVariant.CONFIRMED_SUCCESS: LifecycleState.COMPLETED,
                RecoveryResultVariant.CONFIRMED_FAILURE: LifecycleState.FAILED,
                RecoveryResultVariant.CONFIRMED_ROLLBACK: LifecycleState.ABORTED,
            }
            target_state = target_state_map[recon_result.variant]

            # Acquire recovery lease for protected mutation
            lease = None
            if self.lease_repository:
                try:
                    lease = self.lease_repository.acquire(lease_resource_id, worker_id, request.recovery_ttl_sec)
                except LeaseAcquisitionError as e:
                    self._audit(
                        run_id=db_run.run_id,
                        event_type="recovery_blocked",
                        outcome="lease_held",
                        current_state=db_run.state,
                        reason=f"Lease acquisition rejected: {e}."
                    )
                    return RecoveryProcessingResult(
                        run_id=db_run.run_id,
                        status=RecoveryProcessingStatus.RECOVERY_BLOCKED,
                        classification=classification,
                        action_taken="none_lease_held",
                        reason=f"Recovery lease acquisition rejected: {e}. Active worker holds lease.",
                        current_state=db_run.state
                    )

            try:
                # Execute mutation inside fenced transaction boundary
                context_mgr = None
                if lease and self.transaction_boundary and hasattr(self.transaction_boundary, 'fenced_transaction'):
                    context_mgr = self.transaction_boundary.fenced_transaction(
                        lease.resource_id, lease.owner_id, lease.fencing_token
                    )
                elif self.transaction_boundary:
                    context_mgr = self.transaction_boundary.transaction()

                def _mutate_state():
                    # 1. REVALIDATE AUTHORITATIVE STATE INSIDE TRANSACTION
                    fresh_run = self.run_repository.get_run(db_run.run_id)
                    if not fresh_run:
                        raise ValueError(f"Run {db_run.run_id} missing during mutation.")
                    if fresh_run.version != db_run.version or fresh_run.state != db_run.state:
                        raise OptimisticConcurrencyError(
                            f"Stale in-memory state: expected version {db_run.version} ({db_run.state}), found version {fresh_run.version} ({fresh_run.state})."
                        )

                    # 2. Assert and execute transition using the reconciled target state
                    assert_valid_transition(fresh_run.state, target_state)
                    fresh_run.state = target_state
                    if fresh_run.recovery:
                        fresh_run.recovery.status = "passed"
                        fresh_run.recovery.completed_at = datetime.now(timezone.utc).isoformat()
                    if target_state == LifecycleState.COMPLETED:
                        fresh_run.completed_at = datetime.now(timezone.utc).isoformat()

                    # Determine reservation owner for publishing idempotency result
                    owner_to_publish = (
                        request.expected_owner
                        or (fresh_run.metadata.get("owner_id") if isinstance(getattr(fresh_run, "metadata", None), dict) else None)
                        or worker_id
                    )
                    if request.idempotency_key and self.idempotency_repository:
                        if hasattr(self.idempotency_repository, "get_record"):
                            rec = self.idempotency_repository.get_record(fresh_run.application_id, fresh_run.experiment_id, request.idempotency_key)
                            if rec and getattr(rec, "owner_id", None):
                                owner_to_publish = rec.owner_id

                    # Strictly do not write idempotency_owner to fresh_run.metadata during recovery.
                    # Ownership evidence must never be retroactively manufactured during recovery.

                    old_version = fresh_run.version
                    updated_run = self.run_repository.transition_state(fresh_run.run_id, old_version, fresh_run.state, fresh_run)

                    # 3. Append history
                    history = type("RunTransitionHistoryImpl", (), {
                        "event_id": str(uuid.uuid4()),
                        "run_id": fresh_run.run_id,
                        "previous_state": db_run.state,
                        "new_state": fresh_run.state,
                        "expected_version": old_version,
                        "new_version": old_version + 1,
                        "actor": f"recovery_worker:{worker_id}",
                        "reason": f"Recovery reconciliation: {recon_result.variant.value}",
                        "correlation_id": fresh_run.run_id,
                        "causation_id": None
                    })
                    self.run_repository.append_history(history)

                    # 4. Append audit atomically
                    if self.audit_repository:
                        audit_evt = type("AuditEventImpl", (), {
                            "event_id": str(uuid.uuid4()),
                            "run_id": fresh_run.run_id,
                            "event_type": "recovery_transition_committed",
                            "metadata": {
                                "from_state": db_run.state,
                                "to_state": fresh_run.state,
                                "variant": recon_result.variant.value,
                                "worker_id": worker_id,
                                "fencing_token": lease.fencing_token if lease else None
                            }
                        })
                        self.audit_repository.append(audit_evt)

                    # 5. Publish idempotency result if key was provided
                    if request.idempotency_key and self.idempotency_repository:
                        self.idempotency_repository.publish_result(
                            application_id=fresh_run.application_id,
                            experiment_id=fresh_run.experiment_id,
                            key=request.idempotency_key,
                            owner=owner_to_publish,
                            result={"status": fresh_run.state, "recovered": True}
                        )

                    return updated_run

                if context_mgr:
                    with context_mgr:
                        final_run = _mutate_state()
                else:
                    final_run = _mutate_state()

                return RecoveryProcessingResult(
                    run_id=db_run.run_id,
                    status=RecoveryProcessingStatus.OUTCOME_CONFIRMED,
                    classification=classification,
                    action_taken=f"reconciled_and_transitioned_to_{target_state.value.lower()}",
                    reason=f"Adapter verified outcome as {recon_result.variant.value}. State transitioned to {target_state.value}.",
                    current_state=target_state,
                    fencing_token=lease.fencing_token if lease else None,
                    details={"variant": recon_result.variant.value, "worker_id": worker_id}
                )

            except CommitUncertaintyError as e:
                try:
                    self._audit(
                        run_id=db_run.run_id,
                        event_type="recovery_commit_uncertainty",
                        outcome="uncertain",
                        current_state=db_run.state,
                        reason="Commit uncertainty during recovery mutation."
                    )
                except Exception:
                    pass
                return RecoveryProcessingResult(
                    run_id=db_run.run_id,
                    status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                    classification=classification,
                    action_taken="none_commit_uncertain",
                    reason=f"Commit uncertainty during recovery mutation: {e}. Outcome remains unresolved.",
                    current_state=db_run.state,
                    fencing_token=lease.fencing_token if lease else None
                )
            except (OptimisticConcurrencyError, LeaseOwnershipError) as e:
                try:
                    self._audit(
                        run_id=db_run.run_id,
                        event_type="recovery_fencing_conflict",
                        outcome="conflict",
                        current_state=db_run.state,
                        reason=str(e)
                    )
                except Exception:
                    pass
                return RecoveryProcessingResult(
                    run_id=db_run.run_id,
                    status=RecoveryProcessingStatus.RECOVERY_BLOCKED,
                    classification=classification,
                    action_taken="none_fencing_or_concurrency_error",
                    reason=f"Fencing or concurrency conflict during recovery: {e}.",
                    current_state=db_run.state,
                    fencing_token=lease.fencing_token if lease else None
                )
            except Exception as e:
                try:
                    self._audit(
                        run_id=db_run.run_id,
                        event_type="recovery_mutation_failed",
                        outcome="failed",
                        current_state=db_run.state,
                        reason=f"Recovery mutation transaction aborted: {e}."
                    )
                except Exception:
                    pass
                return RecoveryProcessingResult(
                    run_id=db_run.run_id,
                    status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
                    classification=classification,
                    action_taken="none_transaction_aborted",
                    reason=f"Recovery mutation transaction aborted: {e}. Transaction rolled back atomically.",
                    current_state=db_run.state,
                    fencing_token=lease.fencing_token if lease else None
                )
            finally:
                if lease and self.lease_repository:
                    try:
                        self.lease_repository.release(lease.resource_id, worker_id, lease.fencing_token)
                    except Exception:
                        pass

        # Branch D: OUTCOME_UNKNOWN (fallback)
        self._audit(
            run_id=db_run.run_id,
            event_type="recovery_decision",
            outcome="outcome_unknown",
            current_state=db_run.state,
            reason="Unresolved outcome; cannot confirm terminal state or lack of invocation."
        )
        return RecoveryProcessingResult(
            run_id=db_run.run_id,
            status=RecoveryProcessingStatus.OUTCOME_UNKNOWN,
            classification=classification,
            action_taken="none_unresolved",
            reason=f"Run '{db_run.run_id}' outcome is unknown. State and idempotency protection preserved.",
            current_state=db_run.state
        )
