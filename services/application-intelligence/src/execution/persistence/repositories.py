from typing import Optional, List, Any, Tuple
from contextlib import contextmanager
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select, and_, update

from .interfaces import (
    RunTransitionHistory, TransactionBoundary, FencedTransactionBoundary,
    RunRepository, IdempotencyRepository, LeaseRepository, LeaseRecordProtocol, AuditRepository, AuditEventProtocol,
    IdempotencyConflictError, OptimisticConcurrencyError, CommitUncertaintyError
)
from ..reliability.errors import LeaseAcquisitionError, LeaseOwnershipError
from .models import (
    ExperimentRunModel, RunTransitionHistoryModel,
    IdempotencyRecordModel, LeaseRecordModel, AuditEventModel, OutboxEventModel
)
from ...models.experiment_run import ExperimentRun

class SqlTransactionBoundary(TransactionBoundary, FencedTransactionBoundary):
    def __init__(self, session: Session):
        self.session = session
        
    @contextmanager
    def transaction(self):
        commit_attempted = False
        try:
            yield
            commit_attempted = True
            self.session.commit()
        except Exception as e:
            try:
                self.session.rollback()
            except Exception:
                pass
            if commit_attempted:
                raise CommitUncertaintyError("Commit outcome is unknown") from e
            raise

    @contextmanager
    def fenced_transaction(self, resource_id: str, owner_id: str, fencing_token: int):
        commit_attempted = False
        try:
            # 1. Start transaction implicitly (if not already started) by executing a query.
            # 2. Lock the lease record and check fencing atomically.
            stmt = select(LeaseRecordModel).where(LeaseRecordModel.resource_id == resource_id).with_for_update()
            lease = self.session.execute(stmt).scalar_one_or_none()
            
            if not lease:
                raise LeaseOwnershipError(f"Lease not found for {resource_id}")
            if lease.owner_id != owner_id or lease.fencing_token != fencing_token or lease.status != "active":
                raise LeaseOwnershipError("Stale or invalid fencing token")
            
            now = datetime.now(timezone.utc)
            if (lease.expires_at.replace(tzinfo=timezone.utc) if lease.expires_at.tzinfo is None else lease.expires_at) < now:
                raise LeaseOwnershipError("Lease expired")
            
            # 3. Yield to perform mutations
            yield
            
            commit_attempted = True
            self.session.commit()
        except Exception as e:
            try:
                self.session.rollback()
            except Exception:
                pass
            if commit_attempted:
                raise CommitUncertaintyError("Commit outcome is unknown") from e
            raise

class SqlAlchemyRunRepository(RunRepository):
    def __init__(self, session: Session):
        self.session = session

    def create_run(self, run: ExperimentRun) -> None:
        payload = run.model_dump(mode="json")
        model = ExperimentRunModel(
            id=run.run_id,
            application_id=run.application_id,
            experiment_id=run.experiment_id,
            state=run.state,
            version=run.version,
            safety_decision_id=run.safety_decision_id,
            correlation_id="not-set",
            metadata_payload=payload
        )
        self.session.add(model)
        self.session.flush()

    def get_run(self, run_id: str) -> Optional[ExperimentRun]:
        model = self.session.execute(select(ExperimentRunModel).filter_by(id=run_id)).scalar_one_or_none()
        if not model:
            return None
            
        payload = model.metadata_payload
        if not payload:
            if model.state != "CREATED":
                raise ValueError(f"Legacy payload missing for run {run_id} in state {model.state}, requires repair")
            # For CREATED legacy runs, we can safely reconstruct
            payload = {}
            
        # Parse through Pydantic
        run = ExperimentRun.model_validate(payload)
        # Authoritative DB columns override payload
        run.run_id = model.id
        run.application_id = model.application_id
        run.experiment_id = model.experiment_id
        run.state = model.state
        run.version = model.version
        run.safety_decision_id = model.safety_decision_id
        
        return run

    def get_version_and_state(self, run_id: str) -> Optional[Tuple[int, str]]:
        row = self.session.execute(select(ExperimentRunModel.version, ExperimentRunModel.state).filter_by(id=run_id)).first()
        if not row:
            return None
        return (row.version, row.state)

    def transition_state(self, run_id: str, expected_version: int, new_state: str, payload: ExperimentRun) -> ExperimentRun:
        # Enforce consistency in the payload
        payload.state = new_state
        payload.version = expected_version + 1
        
        stmt = (
            update(ExperimentRunModel)
            .where(and_(ExperimentRunModel.id == run_id, ExperimentRunModel.version == expected_version))
            .values(state=new_state, version=expected_version + 1, metadata_payload=payload.model_dump(mode="json"))
        )
        result = self.session.execute(stmt)
        if result.rowcount == 0:
            raise OptimisticConcurrencyError(f"Version mismatch or run not found for run_id={run_id}, expected_version={expected_version}")
        
        self.session.flush()
        
        return self.get_run(run_id)

    def append_history(self, history: RunTransitionHistory) -> None:
        model = RunTransitionHistoryModel(
            id=history.event_id,
            run_id=history.run_id,
            previous_state=history.previous_state,
            new_state=history.new_state,
            expected_version=history.expected_version,
            new_version=history.new_version,
            actor=history.actor,
            reason=history.reason,
            correlation_id=history.correlation_id,
            causation_id=history.causation_id
        )
        self.session.add(model)
        self.session.flush()

    def get_history(self, run_id: str) -> List[RunTransitionHistory]:
        models = self.session.execute(
            select(RunTransitionHistoryModel).filter_by(run_id=run_id).order_by(RunTransitionHistoryModel.new_version)
        ).scalars().all()
        return [
            type("RunTransitionHistoryImpl", (), {
                "event_id": m.id,
                "run_id": m.run_id,
                "previous_state": m.previous_state,
                "new_state": m.new_state,
                "expected_version": m.expected_version,
                "new_version": m.new_version,
                "actor": m.actor,
                "reason": m.reason,
                "correlation_id": m.correlation_id,
                "causation_id": m.causation_id
            }) for m in models
        ]

class SqlAlchemyIdempotencyRepository(IdempotencyRepository):
    def __init__(self, session: Session):
        self.session = session

    def reserve(self, application_id: str, experiment_id: str, key: str, fingerprint: str, owner: str) -> Tuple[str, Optional[Any]]:
        # First attempt to fetch
        stmt = select(IdempotencyRecordModel).where(and_(
            IdempotencyRecordModel.application_id == application_id,
            IdempotencyRecordModel.operation_scope == experiment_id, # Reusing experiment_id as operation_scope here
            IdempotencyRecordModel.idempotency_key_digest == key
        ))
        record = self.session.execute(stmt).scalar_one_or_none()
        
        if record:
            if record.fingerprint != fingerprint:
                raise IdempotencyConflictError("Fingerprint divergence detected")
            return (record.status, record.terminal_result)
        
        # Try inserting
        new_record = IdempotencyRecordModel(
            application_id=application_id,
            operation_scope=experiment_id,
            idempotency_key_digest=key,
            fingerprint=fingerprint,
            owner_id=owner,
            status="in_progress"
        )
        self.session.add(new_record)
        try:
            # We use savepoint (nested transaction) to catch integrity error
            with self.session.begin_nested():
                self.session.flush()
            return ("acquired", None)
        except IntegrityError:
            # Concurrent insertion occurred
            self.session.expunge(new_record)
            record = self.session.execute(stmt).scalar_one_or_none()
            if not record:
                raise RuntimeError("Failed to read concurrently inserted record")
            if record.fingerprint != fingerprint:
                raise IdempotencyConflictError("Fingerprint divergence detected")
            return (record.status, record.terminal_result)

    def publish_result(self, application_id: str, experiment_id: str, key: str, owner: str, result: Any) -> None:
        stmt = select(IdempotencyRecordModel).where(and_(
            IdempotencyRecordModel.application_id == application_id,
            IdempotencyRecordModel.operation_scope == experiment_id,
            IdempotencyRecordModel.idempotency_key_digest == key
        )).with_for_update() # Lock the row
        
        record = self.session.execute(stmt).scalar_one_or_none()
        if not record:
            raise ValueError("Record not found")
        if record.owner_id != owner:
            raise ValueError("Only the reservation owner can publish the result")
        
        record.status = "completed"
        record.terminal_result = result
        self.session.flush()

    def get_result(self, application_id: str, experiment_id: str, key: str) -> Optional[Any]:
        stmt = select(IdempotencyRecordModel).where(and_(
            IdempotencyRecordModel.application_id == application_id,
            IdempotencyRecordModel.operation_scope == experiment_id,
            IdempotencyRecordModel.idempotency_key_digest == key
        ))
        record = self.session.execute(stmt).scalar_one_or_none()
        return record.terminal_result if record else None

    def get_record(self, application_id: str, experiment_id: str, key: str):
        stmt = select(IdempotencyRecordModel).where(and_(
            IdempotencyRecordModel.application_id == application_id,
            IdempotencyRecordModel.operation_scope == experiment_id,
            IdempotencyRecordModel.idempotency_key_digest == key
        ))
        record = self.session.execute(stmt).scalar_one_or_none()
        if not record:
            return None
        return type("IdempotencyRecordImpl", (), {
            "idempotency_key": record.idempotency_key_digest,
            "fingerprint": record.fingerprint,
            "status": record.status,
            "result": record.terminal_result,
            "owner_id": record.owner_id,
            "uncertain_outcome": bool(record.uncertain_outcome)
        })()

class SqlAlchemyLeaseRepository(LeaseRepository):
    def __init__(self, session: Session):
        self.session = session

    def acquire(self, resource_id: str, owner_id: str, ttl_seconds: int) -> LeaseRecordProtocol:
        max_retries = 3
        retries = 0
        while retries < max_retries:
            # Atomic acquire with fencing
            stmt = select(LeaseRecordModel).where(LeaseRecordModel.resource_id == resource_id).with_for_update()
            lease = self.session.execute(stmt).scalar_one_or_none()
            
            now = datetime.now(timezone.utc)
            
            if lease:
                # If active, check expiry
                if lease.status == "active" and (lease.expires_at.replace(tzinfo=timezone.utc) if lease.expires_at.tzinfo is None else lease.expires_at) > now:
                    if lease.owner_id != owner_id:
                        raise LeaseAcquisitionError(f"Resource {resource_id} is already actively held")
                    
                # If expired or released or we own it, renew/acquire
                lease.owner_id = owner_id
                lease.status = "active"
                lease.version += 1
                lease.fencing_token += 1
                lease.acquired_at = now
                lease.expires_at = datetime.fromtimestamp(now.timestamp() + ttl_seconds, tz=timezone.utc)
                self.session.flush()
                break
            else:
                lease = LeaseRecordModel(
                    resource_id=resource_id,
                    owner_id=owner_id,
                    status="active",
                    version=1,
                    fencing_token=1,
                    acquired_at=now,
                    expires_at=datetime.fromtimestamp(now.timestamp() + ttl_seconds, tz=timezone.utc)
                )
                self.session.add(lease)
                try:
                    with self.session.begin_nested():
                        self.session.flush()
                    break
                except IntegrityError:
                    self.session.expunge(lease)
                    retries += 1
                    continue
        else:
            raise RuntimeError("Exceeded maximum retries attempting to acquire lease")
            
        return type("LeaseRecordImpl", (), {
            "lease_id": lease.id,
            "resource_id": lease.resource_id,
            "owner_id": lease.owner_id,
            "status": lease.status,
            "version": lease.version,
            "fencing_token": lease.fencing_token,
            "expires_at": lease.expires_at.isoformat()
        })

    def renew(self, resource_id: str, owner_id: str, fencing_token: int, ttl_seconds: int) -> None:
        stmt = select(LeaseRecordModel).where(LeaseRecordModel.resource_id == resource_id).with_for_update()
        lease = self.session.execute(stmt).scalar_one_or_none()
        if not lease or lease.owner_id != owner_id or lease.fencing_token != fencing_token or lease.status != "active":
            raise LeaseOwnershipError("Stale or invalid lease renewal")
        
        now = datetime.now(timezone.utc)
        lease.expires_at = datetime.fromtimestamp(now.timestamp() + ttl_seconds, tz=timezone.utc)
        self.session.flush()

    def release(self, resource_id: str, owner_id: str, fencing_token: int) -> None:
        stmt = select(LeaseRecordModel).where(LeaseRecordModel.resource_id == resource_id).with_for_update()
        lease = self.session.execute(stmt).scalar_one_or_none()
        if not lease or lease.owner_id != owner_id or lease.fencing_token != fencing_token:
            raise LeaseOwnershipError("Stale or invalid lease release")
            
        lease.status = "released"
        lease.released_at = datetime.now(timezone.utc)
        self.session.flush()

    def validate_fencing_token(self, resource_id: str, token: int) -> bool:
        stmt = select(LeaseRecordModel.fencing_token, LeaseRecordModel.status, LeaseRecordModel.expires_at).where(LeaseRecordModel.resource_id == resource_id)
        row = self.session.execute(stmt).first()
        if not row:
            return False
        now = datetime.now(timezone.utc)
        # Token must match, and lease must be active and not expired
        return row.fencing_token == token and row.status == "active" and (row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at) > now

    def is_active(self, resource_id: str) -> bool:
        stmt = select(LeaseRecordModel.status, LeaseRecordModel.expires_at).where(LeaseRecordModel.resource_id == resource_id)
        row = self.session.execute(stmt).first()
        if not row:
            return False
        now = datetime.now(timezone.utc)
        expires_at = row.expires_at.replace(tzinfo=timezone.utc) if row.expires_at.tzinfo is None else row.expires_at
        return row.status == "active" and expires_at > now

class SqlAlchemyAuditRepository(AuditRepository):
    def __init__(self, session: Session):
        self.session = session

    def append(self, event: AuditEventProtocol) -> None:
        model = AuditEventModel(
            id=event.event_id,
            run_id=event.run_id,
            event_type=event.event_type,
            outcome="recorded",
            actor="system",
            redacted_metadata=event.metadata
        )
        self.session.add(model)
        self.session.flush()

    def append_durable(self, event: AuditEventProtocol) -> None:
        """
        Durably persists an audit event using an isolated session so unrelated
        pending changes in the shared session are not committed.
        """
        bind = getattr(self.session, "bind", None) or (self.session.get_bind() if hasattr(self.session, "get_bind") else None)
        if bind is not None:
            with Session(bind) as isolated_session:
                model = AuditEventModel(
                    id=event.event_id,
                    run_id=event.run_id,
                    event_type=event.event_type,
                    outcome="recorded",
                    actor="system",
                    redacted_metadata=event.metadata
                )
                isolated_session.add(model)
                isolated_session.commit()
        else:
            self.append(event)

    def get_events(self, run_id: str) -> List[AuditEventProtocol]:
        models = self.session.execute(select(AuditEventModel).filter_by(run_id=run_id).order_by(AuditEventModel.created_at)).scalars().all()
        return [
            type("AuditEventImpl", (), {
                "event_id": m.id,
                "run_id": m.run_id,
                "event_type": m.event_type,
                "metadata": m.redacted_metadata
            }) for m in models
        ]
