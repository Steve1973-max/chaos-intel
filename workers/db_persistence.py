"""PostgreSQL and Redis persistence bridge for distributed API and Worker containers.

When DATABASE_URL points to PostgreSQL (e.g. in Docker Compose production deployments),
this module persists and synchronizes:
- Registered & analyzed applications (`applications` table)
- Background jobs and worker execution state (`background_jobs` table)
- Chaos experiment runs, versioned state transitions, fenced leases, idempotency records,
  and durable audit events (`experiment_runs`, `run_transitions`, `leases`,
  `idempotency_records`, `audit_events` tables)
- Redis job notifications and health probes (`REDIS_URL`)

When DATABASE_URL is unset or points to local SQLite in unit tests, `is_postgres_enabled()`
returns False so in-memory unit tests remain completely isolated.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

_APP_INTEL_PATH = Path(__file__).resolve().parents[1] / "services" / "application-intelligence"
if str(_APP_INTEL_PATH) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_PATH))

from src.execution.persistence.models import (
    AuditEventModel,
    Base,
    ExperimentRunModel,
    IdempotencyRecordModel,
    LeaseRecordModel,
    RunTransitionHistoryModel,
)
from src.execution.persistence.repositories import (
    SqlAlchemyAuditRepository,
    SqlAlchemyIdempotencyRepository,
    SqlAlchemyLeaseRepository,
    SqlAlchemyRunRepository,
    SqlTransactionBoundary,
)
from src.models.experiment_run import ExperimentRun
from workers.models import ApplicationRegistrationModel, JobRecordModel

logger = logging.getLogger("chaos_intel.db_persistence")

_engine = None
_SessionLocal = None


def _normalize_db_url(db_url: str) -> str:
    if db_url.startswith("postgresql+psycopg2://"):
        return db_url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    if db_url.startswith("postgresql://"):
        return db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return db_url


def is_postgres_enabled() -> bool:
    """Return True when DATABASE_URL is configured for PostgreSQL."""
    db_url = os.environ.get("DATABASE_URL", "")
    return db_url.startswith("postgresql")


def get_pg_engine():
    """Return singleton SQLAlchemy engine for PostgreSQL, initializing tables on first connect."""
    global _engine, _SessionLocal
    if _engine is None:
        db_url = _normalize_db_url(os.environ.get("DATABASE_URL", ""))
        _engine = create_engine(db_url, pool_pre_ping=True, future=True)
        Base.metadata.create_all(_engine)
        _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return _engine


@contextmanager
def get_pg_session() -> Generator[Session, None, None]:
    """Provide a short-lived transactional PostgreSQL session."""
    get_pg_engine()
    assert _SessionLocal is not None
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_postgres_health() -> Dict[str, Any]:
    """Execute a lightweight SELECT 1 probe against PostgreSQL."""
    if not is_postgres_enabled():
        return {"status": "DISABLED", "engine": "in_memory"}
    try:
        with get_pg_session() as session:
            session.execute(text("SELECT 1"))
        return {"status": "HEALTHY", "engine": "postgresql"}
    except Exception as exc:
        return {"status": "DEGRADED", "engine": "postgresql", "error": str(exc)}


def notify_redis_job(job_id: str, status: str) -> None:
    """Publish job state update to Redis when REDIS_URL is configured."""
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url or not is_postgres_enabled():
        return
    try:
        import redis
        client = redis.Redis.from_url(redis_url, socket_connect_timeout=1.5, socket_timeout=1.5)
        client.hset("chaos_intel:job_status", job_id, status)
        if status == "queued":
            client.rpush("chaos_intel:job_queue", job_id)
        client.close()
    except Exception as exc:
        logger.debug(f"Redis notification skipped for job {job_id}: {exc}")


def check_redis_health() -> Dict[str, Any]:
    """Execute a lightweight PING probe against Redis."""
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        return {"status": "DISABLED"}
    try:
        import redis
        client = redis.Redis.from_url(redis_url, socket_connect_timeout=1.5, socket_timeout=1.5)
        pong = client.ping()
        client.close()
        return {"status": "HEALTHY" if pong else "DEGRADED", "engine": "redis"}
    except Exception as exc:
        return {"status": "DEGRADED", "engine": "redis", "error": str(exc)}


# ---------------------------------------------------------------------------
# Application Registration & Analyzed Model Persistence
# ---------------------------------------------------------------------------

def pg_save_application(
    app_record: Dict[str, Any],
    analyzed_model_dump: Optional[Dict[str, Any]] = None,
) -> None:
    """Insert or update an ApplicationRegistrationModel record in PostgreSQL."""
    if not is_postgres_enabled():
        return
    try:
        app_id = app_record["application_id"]
        with get_pg_session() as session:
            existing = session.execute(
                select(ApplicationRegistrationModel).where(ApplicationRegistrationModel.id == app_id)
            ).scalar_one_or_none()

            payload = dict(existing.metadata_payload) if (existing and existing.metadata_payload) else {}
            payload.update(app_record)
            if analyzed_model_dump is not None:
                payload["analyzed_model"] = analyzed_model_dump

            if existing:
                existing.name = app_record.get("name", existing.name)
                existing.source_type = app_record.get("source_type", existing.source_type)
                existing.source_location = app_record.get("source_location", existing.source_location)
                existing.status = app_record.get("status", existing.status)
                existing.metadata_payload = payload
                existing.updated_at = datetime.now(timezone.utc)
            else:
                row = ApplicationRegistrationModel(
                    id=app_id,
                    name=app_record.get("name", "application"),
                    source_type=app_record.get("source_type", "archive"),
                    source_location=app_record.get("source_location", ""),
                    status=app_record.get("status", "registered"),
                    metadata_payload=payload,
                )
                session.add(row)
    except Exception as exc:
        logger.warning(f"Failed to persist application {app_record.get('application_id')} to PostgreSQL: {exc}")


def pg_get_application(application_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve an application record and its metadata_payload from PostgreSQL."""
    if not is_postgres_enabled():
        return None
    try:
        with get_pg_session() as session:
            row = session.execute(
                select(ApplicationRegistrationModel).where(ApplicationRegistrationModel.id == application_id)
            ).scalar_one_or_none()
            if not row:
                return None
            meta = dict(row.metadata_payload or {})
            meta.update(
                {
                    "application_id": row.id,
                    "name": row.name,
                    "source_type": row.source_type,
                    "source_location": row.source_location,
                    "status": row.status,
                }
            )
            return meta
    except Exception as exc:
        logger.warning(f"Failed to read application {application_id} from PostgreSQL: {exc}")
        return None


def pg_list_applications() -> List[Dict[str, Any]]:
    """Retrieve all registered applications from PostgreSQL."""
    if not is_postgres_enabled():
        return []
    try:
        with get_pg_session() as session:
            rows = (
                session.execute(
                    select(ApplicationRegistrationModel).order_by(ApplicationRegistrationModel.created_at.desc())
                )
                .scalars()
                .all()
            )
            results: List[Dict[str, Any]] = []
            for row in rows:
                meta = dict(row.metadata_payload or {})
                meta.pop("analyzed_model", None)
                meta.update(
                    {
                        "application_id": row.id,
                        "name": row.name,
                        "source_type": row.source_type,
                        "source_location": row.source_location,
                        "status": row.status,
                        "registered_at": meta.get("registered_at", row.created_at.isoformat() if row.created_at else ""),
                        "services_count": meta.get("services_count", 0),
                        "apis_count": meta.get("apis_count", 0),
                        "technologies": meta.get("technologies", []),
                    }
                )
                results.append(meta)
            return results
    except Exception as exc:
        logger.warning(f"Failed to list applications from PostgreSQL: {exc}")
        return []


# ---------------------------------------------------------------------------
# Background Job Persistence & Cross-Container Queue Coordination
# ---------------------------------------------------------------------------

def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def _row_to_job_dict(row: JobRecordModel) -> Dict[str, Any]:
    err = row.error
    outcome_uncertain = False
    if isinstance(err, dict) and err.get("classification") == "uncertain":
        outcome_uncertain = True
    elif row.status == "dead_letter":
        outcome_uncertain = True
    return {
        "job_id": row.id,
        "task_name": row.task_name,
        "payload": dict(row.payload or {}),
        "correlation_id": row.correlation_id,
        "priority": row.priority,
        "timeout_seconds": row.timeout_seconds,
        "max_retries": row.max_retries,
        "status": row.status,
        "retry_count": row.retry_count,
        "worker_id": row.worker_id,
        "result": dict(row.result) if isinstance(row.result, dict) else row.result,
        "error": dict(row.error) if isinstance(row.error, dict) else row.error,
        "is_cancelled": row.status == "cancelled",
        "outcome_uncertain": outcome_uncertain,
        "created_at": row.created_at.isoformat() if row.created_at else datetime.now(timezone.utc).isoformat(),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def pg_enqueue_job(job: Any) -> None:
    """Persist a newly enqueued Job into PostgreSQL `background_jobs` and notify Redis."""
    if not is_postgres_enabled():
        return
    try:
        with get_pg_session() as session:
            existing = session.execute(
                select(JobRecordModel).where(JobRecordModel.id == job.job_id)
            ).scalar_one_or_none()
            if existing:
                existing.status = "queued"
                existing.retry_count = job.retry_count
                existing.updated_at = datetime.now(timezone.utc)
            else:
                row = JobRecordModel(
                    id=job.job_id,
                    task_name=job.task_name,
                    correlation_id=job.correlation_id,
                    status=job.status,
                    priority=job.priority,
                    payload=job.payload,
                    result=job.result,
                    error=job.error,
                    retry_count=job.retry_count,
                    max_retries=job.max_retries,
                    timeout_seconds=job.timeout_seconds,
                    worker_id=job.worker_id,
                )
                session.add(row)
        notify_redis_job(job.job_id, "queued")
    except Exception as exc:
        logger.warning(f"Failed to enqueue job {job.job_id} in PostgreSQL: {exc}")


def pg_claim_next_queued_job(worker_id: str) -> Optional[Dict[str, Any]]:
    """Atomically claim the highest-priority queued job in PostgreSQL using FOR UPDATE SKIP LOCKED."""
    if not is_postgres_enabled():
        return None
    try:
        with get_pg_session() as session:
            stmt = (
                select(JobRecordModel)
                .where(JobRecordModel.status == "queued")
                .order_by(JobRecordModel.priority.desc(), JobRecordModel.created_at.asc())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            row = session.execute(stmt).scalar_one_or_none()
            if not row:
                return None
            now = datetime.now(timezone.utc)
            row.status = "running"
            row.worker_id = worker_id
            row.started_at = now
            row.updated_at = now
            session.flush()
            data = _row_to_job_dict(row)
        notify_redis_job(data["job_id"], "running")
        return data
    except Exception as exc:
        logger.warning(f"Failed to claim queued job from PostgreSQL: {exc}")
        return None


def pg_update_job(job: Any) -> None:
    """Persist job state transitions (`running`, `completed`, `failed`, `cancelled`, `dead_letter`) to PostgreSQL."""
    if not is_postgres_enabled():
        return
    try:
        with get_pg_session() as session:
            row = session.execute(
                select(JobRecordModel).where(JobRecordModel.id == job.job_id)
            ).scalar_one_or_none()
            if not row:
                return
            row.status = job.status
            row.worker_id = job.worker_id
            row.result = job.result
            row.error = job.error
            row.retry_count = job.retry_count
            if job.started_at:
                row.started_at = _parse_iso(job.started_at)
            if job.completed_at:
                row.completed_at = _parse_iso(job.completed_at)
            row.updated_at = datetime.now(timezone.utc)
        notify_redis_job(job.job_id, job.status)
    except Exception as exc:
        logger.warning(f"Failed to update job {job.job_id} in PostgreSQL: {exc}")


def pg_get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Fetch authoritative job state from PostgreSQL."""
    if not is_postgres_enabled():
        return None
    try:
        with get_pg_session() as session:
            row = session.execute(
                select(JobRecordModel).where(JobRecordModel.id == job_id)
            ).scalar_one_or_none()
            if not row:
                return None
            return _row_to_job_dict(row)
    except Exception as exc:
        logger.warning(f"Failed to fetch job {job_id} from PostgreSQL: {exc}")
        return None


def pg_list_jobs(status_filter: Optional[str] = None, task_name_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch jobs from PostgreSQL, optionally filtered by status or task_name."""
    if not is_postgres_enabled():
        return []
    try:
        with get_pg_session() as session:
            stmt = select(JobRecordModel)
            if status_filter:
                stmt = stmt.where(JobRecordModel.status == status_filter)
            if task_name_filter:
                stmt = stmt.where(JobRecordModel.task_name == task_name_filter)
            stmt = stmt.order_by(JobRecordModel.created_at.desc())
            rows = session.execute(stmt).scalars().all()
            return [_row_to_job_dict(r) for r in rows]
    except Exception as exc:
        logger.warning(f"Failed to list jobs from PostgreSQL: {exc}")
        return []


# ---------------------------------------------------------------------------
# Durable Execution Governance (Runs, Transitions, Leases, Idempotency, Audit)
# ---------------------------------------------------------------------------

def pg_reserve_idempotency(
    application_id: str,
    operation_scope: str,
    idempotency_key: str,
    fingerprint: str,
    owner_id: str,
) -> Tuple[str, Optional[Any]]:
    """Reserve an idempotency key in PostgreSQL `idempotency_records`."""
    if not is_postgres_enabled():
        return ("acquired", None)
    with get_pg_session() as session:
        repo = SqlAlchemyIdempotencyRepository(session)
        return repo.reserve(application_id, operation_scope, idempotency_key, fingerprint, owner_id)


def pg_publish_idempotency(
    application_id: str,
    operation_scope: str,
    idempotency_key: str,
    owner_id: str,
    result: Dict[str, Any],
) -> None:
    """Publish terminal result for a reserved idempotency key in PostgreSQL."""
    if not is_postgres_enabled():
        return
    try:
        with get_pg_session() as session:
            repo = SqlAlchemyIdempotencyRepository(session)
            repo.publish_result(application_id, operation_scope, idempotency_key, owner_id, result)
    except Exception as exc:
        logger.warning(f"Failed to publish idempotency result for {idempotency_key}: {exc}")


def pg_record_chaos_run_lifecycle(
    run_id: str,
    application_id: str,
    experiment_id: str,
    safety_decision_id: str,
    correlation_id: str,
    approved_by: str = "admin",
) -> Optional[int]:
    """Persist fenced lease acquisition, versioned run transitions, and audit events in PostgreSQL.

    Executes in short, discrete transactions without holding locks across external calls.
    Returns the fencing_token used for the run.
    """
    if not is_postgres_enabled():
        return None
    try:
        resource_id = f"chaos-target:{application_id}"
        owner_id = f"worker:{run_id}"
        fencing_token: int = 1

        # 1. Acquire fenced lease & create run in CREATED (version 1)
        with get_pg_session() as session:
            lease_repo = SqlAlchemyLeaseRepository(session)
            run_repo = SqlAlchemyRunRepository(session)
            audit_repo = SqlAlchemyAuditRepository(session)

            lease = lease_repo.acquire(resource_id, owner_id, ttl_seconds=120)
            fencing_token = lease.fencing_token
            assert lease_repo.validate_fencing_token(resource_id, fencing_token) is True

            run = ExperimentRun(
                run_id=run_id,
                application_id=application_id,
                experiment_id=experiment_id,
                state="CREATED",
                version=1,
                safety_decision_id=safety_decision_id,
            )
            run_repo.create_run(run)
            run_repo.append_history(
                type(
                    "HistoryEvt",
                    (),
                    {
                        "event_id": str(uuid.uuid4()),
                        "run_id": run_id,
                        "previous_state": None,
                        "new_state": "CREATED",
                        "expected_version": 0,
                        "new_version": 1,
                        "actor": approved_by,
                        "reason": "Dry-run chaos experiment initialized",
                        "correlation_id": correlation_id,
                        "causation_id": experiment_id,
                    },
                )()
            )
            audit_repo.append(
                type(
                    "AuditEvt",
                    (),
                    {
                        "event_id": str(uuid.uuid4()),
                        "run_id": run_id,
                        "event_type": "EXPERIMENT_RUN_CREATED",
                        "metadata": {
                            "experiment_id": experiment_id,
                            "fencing_token": fencing_token,
                            "mode": "dry_run",
                            "live_execution": False,
                        },
                    },
                )()
            )

        # 2. Fenced transition CREATED (1) -> APPROVED (2) -> COMPLETED (3) and release lease
        with get_pg_session() as session:
            boundary = SqlTransactionBoundary(session)
            run_repo = SqlAlchemyRunRepository(session)
            lease_repo = SqlAlchemyLeaseRepository(session)
            audit_repo = SqlAlchemyAuditRepository(session)

            with boundary.fenced_transaction(resource_id, owner_id, fencing_token):
                run = run_repo.get_run(run_id)
                if run:
                    run_repo.transition_state(run_id, 1, "APPROVED", run)
                    run_repo.append_history(
                        type(
                            "HistoryEvt",
                            (),
                            {
                                "event_id": str(uuid.uuid4()),
                                "run_id": run_id,
                                "previous_state": "CREATED",
                                "new_state": "APPROVED",
                                "expected_version": 1,
                                "new_version": 2,
                                "actor": approved_by,
                                "reason": "Human safety approval verified",
                                "correlation_id": correlation_id,
                                "causation_id": safety_decision_id,
                            },
                        )()
                    )
                    run_repo.transition_state(run_id, 2, "COMPLETED", run)
                    run_repo.append_history(
                        type(
                            "HistoryEvt",
                            (),
                            {
                                "event_id": str(uuid.uuid4()),
                                "run_id": run_id,
                                "previous_state": "APPROVED",
                                "new_state": "COMPLETED",
                                "expected_version": 2,
                                "new_version": 3,
                                "actor": owner_id,
                                "reason": "Dry-run simulation completed with zero live side effects",
                                "correlation_id": correlation_id,
                                "causation_id": experiment_id,
                            },
                        )()
                    )
                    audit_repo.append(
                        type(
                            "AuditEvt",
                            (),
                            {
                                "event_id": str(uuid.uuid4()),
                                "run_id": run_id,
                                "event_type": "EXPERIMENT_DRY_RUN_COMPLETED",
                                "metadata": {
                                    "fencing_token": fencing_token,
                                    "final_version": 3,
                                    "live_execution": False,
                                },
                            },
                        )()
                    )
                lease_repo.release(resource_id, owner_id, fencing_token)

        return fencing_token
    except Exception as exc:
        logger.warning(f"Failed to record chaos run lifecycle in PostgreSQL for {run_id}: {exc}")
        return None
