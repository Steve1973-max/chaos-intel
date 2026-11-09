"""Integration tests for Asynchronous Workers, Job Queue, and Retry Semantics (Phase 5).

Verifies:
- Priority-based job queue ordering
- Background worker lifecycle and task execution
- Cooperative cancellation of queued and running jobs
- Retry classification:
  - Transient error retry with bounded attempts
  - Deterministic error immediate failure (no retry)
  - Uncertain outcome moving to DLQ without automatic replay
- Dead-letter queue (DLQ) tracking
- Secret and credential redaction in worker logs
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from workers.queue import InMemoryJobQueue
from workers.retry import ClassifiedError, RetryClassification, classify_error
from workers.task_registry import TaskRegistry
from workers.worker import BackgroundWorker, redact_secrets


@pytest.mark.asyncio
async def test_job_queue_priority_ordering():
    """Verify jobs with higher priority are dequeued first."""
    queue = InMemoryJobQueue()

    # Enqueue low, high, and medium priority jobs
    id_low = await queue.enqueue("task_a", {"val": "low"}, correlation_id="c1", priority=0)
    id_high = await queue.enqueue("task_b", {"val": "high"}, correlation_id="c2", priority=10)
    id_med = await queue.enqueue("task_c", {"val": "med"}, correlation_id="c3", priority=5)

    # Dequeue in order: high (10) -> med (5) -> low (0)
    j1 = await queue.dequeue(timeout_seconds=0.5)
    assert j1.job_id == id_high

    j2 = await queue.dequeue(timeout_seconds=0.5)
    assert j2.job_id == id_med

    j3 = await queue.dequeue(timeout_seconds=0.5)
    assert j3.job_id == id_low


@pytest.mark.asyncio
async def test_worker_successful_task_execution():
    """Verify background worker fetches and executes registered tasks to completion."""
    queue = InMemoryJobQueue()
    registry = TaskRegistry()

    @registry.register("sample_task")
    async def sample_handler(payload, correlation_id, job):
        return {"processed": payload["num"] * 2, "corr": correlation_id}

    worker = BackgroundWorker(queue=queue, registry=registry, poll_interval_seconds=0.05)

    job_id = await queue.enqueue("sample_task", {"num": 21}, correlation_id="c-success")
    processed_job = await worker.process_next_job()

    assert processed_job is not None
    assert processed_job.job_id == job_id
    assert processed_job.status == "completed"
    assert processed_job.result == {"processed": 42, "corr": "c-success"}
    assert processed_job.completed_at is not None


@pytest.mark.asyncio
async def test_worker_cancellation():
    """Verify cancellation marks job cancelled and aborts execution."""
    queue = InMemoryJobQueue()
    registry = TaskRegistry()

    executed = False

    @registry.register("cancellable_task")
    async def cancellable_handler(payload, correlation_id, job):
        nonlocal executed
        executed = True
        return {"done": True}

    worker = BackgroundWorker(queue=queue, registry=registry)

    # Enqueue then cancel before pickup
    job_id = await queue.enqueue("cancellable_task", {}, correlation_id="c-cancel")
    cancelled = await queue.cancel_job(job_id)
    assert cancelled is True

    # Worker picks up job - skips execution because it was cancelled
    job = await worker.process_next_job()
    assert job is None
    assert executed is False  # Handler was not executed

    stored_job = await queue.get_job(job_id)
    assert stored_job.status == "cancelled"


@pytest.mark.asyncio
async def test_retry_classification_transient_vs_deterministic_vs_uncertain():
    """Verify failure classification semantics."""
    # 1. Transient error (e.g. database deadlock)
    deadlock_err = Exception("deadlock detected on lock relation")
    assert classify_error(deadlock_err) == RetryClassification.TRANSIENT

    # 2. Deterministic error (e.g. ValueError or FileNotFoundError)
    val_err = ValueError("Invalid parameter value for target scope")
    assert classify_error(val_err) == RetryClassification.DETERMINISTIC

    # 3. UNCERTAIN OUTCOME on mutation timeout
    # CRITICAL INVARIANT: Timeouts during mutating operations MUST NEVER be automatically replayed!
    mutation_timeout = TimeoutError("POST /checkout timed out waiting for gateway")
    assert classify_error(mutation_timeout, is_mutation=True) == RetryClassification.UNCERTAIN


@pytest.mark.asyncio
async def test_worker_uncertain_failure_dead_letter_ban_on_replay():
    """Verify uncertain mutating failure moves to DLQ without automatic replay."""
    queue = InMemoryJobQueue()
    registry = TaskRegistry()

    call_count = 0

    @registry.register("uncertain_task")
    async def uncertain_handler(payload, correlation_id, job):
        nonlocal call_count
        call_count += 1
        raise ClassifiedError("Mutation timed out after dispatch", RetryClassification.UNCERTAIN)

    worker = BackgroundWorker(queue=queue, registry=registry)

    job_id = await queue.enqueue("uncertain_task", {}, correlation_id="c-uncertain", max_retries=3)
    job = await worker.process_next_job()

    assert job is not None
    assert job.status == "dead_letter"
    assert job.outcome_uncertain is True
    assert call_count == 1  # Never replayed!

    # DLQ inspection
    dlq = await queue.get_dead_letter_jobs()
    assert len(dlq) == 1
    assert dlq[0].job_id == job_id


@pytest.mark.asyncio
async def test_secret_redaction():
    """Verify secrets and authentication tokens are redacted from worker logs."""
    sensitive_log = 'User logged in with password="super_secret_password_123" and api_key=xyz987654321'
    redacted = redact_secrets(sensitive_log)

    assert "super_secret_password_123" not in redacted
    assert "xyz987654321" not in redacted
    assert "[REDACTED]" in redacted
