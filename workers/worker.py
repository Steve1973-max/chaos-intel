"""Background Worker lifecycle and task execution engine."""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any, Dict, Optional

from .queue import Job, JobQueue, utcnow_iso
from .retry import RetryClassification, classify_error
from .task_registry import TaskRegistry, default_task_registry

logger = logging.getLogger(__name__)

_SECRET_PATTERN = re.compile(
    r'(?i)("?(?:password|token|secret|api[_-]?key|authorization|bearer)"?\s*[:=]\s*)"?([^"\s,]+)"?'
)


def redact_secrets(text: str) -> str:
    """Redact passwords, tokens, and authorization credentials from log text."""
    return _SECRET_PATTERN.sub(r'\1"[REDACTED]"', text)


class BackgroundWorker:
    """Asynchronous background worker executing tasks from a JobQueue."""

    def __init__(
        self,
        queue: JobQueue,
        registry: Optional[TaskRegistry] = None,
        worker_id: Optional[str] = None,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self.queue = queue
        self.registry = registry or default_task_registry
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.poll_interval_seconds = poll_interval_seconds
        self._is_running = False
        self._current_task: Optional[asyncio.Task] = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def start(self) -> None:
        """Start worker execution loop."""
        self._is_running = True
        logger.info(redact_secrets(f"Worker '{self.worker_id}' started."))
        self._current_task = asyncio.create_task(self.run_loop())

    async def stop(self) -> None:
        """Signal worker to stop gracefully."""
        self._is_running = False
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                pass
        logger.info(redact_secrets(f"Worker '{self.worker_id}' stopped."))

    async def run_loop(self) -> None:
        """Main worker polling loop."""
        while self._is_running:
            try:
                await self.process_next_job()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(redact_secrets(f"Worker '{self.worker_id}' error in loop: {exc}"))
                await asyncio.sleep(self.poll_interval_seconds)

    async def process_next_job(self) -> Optional[Job]:
        """Fetch and execute a single job from the queue."""
        job = await self.queue.dequeue(timeout_seconds=self.poll_interval_seconds)
        if job is None:
            return None

        # Check pre-execution cancellation
        if job.is_cancelled:
            job.status = "cancelled"
            job.completed_at = utcnow_iso()
            await self.queue.update_job(job)
            return job

        job.status = "running"
        job.worker_id = self.worker_id
        job.started_at = utcnow_iso()
        await self.queue.update_job(job)

        handler = self.registry.get_handler(job.task_name)
        if handler is None:
            job.status = "failed"
            job.completed_at = utcnow_iso()
            job.error = {
                "error_type": "TaskNotRegisteredError",
                "message": f"No handler registered for task '{job.task_name}'",
                "classification": RetryClassification.DETERMINISTIC.value,
            }
            await self.queue.update_job(job)
            return job

        # Execute with timeout and error classification
        try:
            logger.info(redact_secrets(f"Worker executing job '{job.job_id}' (task '{job.task_name}', correlation '{job.correlation_id}')"))
            result = await asyncio.wait_for(
                handler(job.payload, job.correlation_id, job),
                timeout=float(job.timeout_seconds),
            )

            # Re-check cancellation post-execution
            if job.is_cancelled:
                job.status = "cancelled"
                job.completed_at = utcnow_iso()
            else:
                job.status = "completed"
                job.result = result
                job.completed_at = utcnow_iso()

            await self.queue.update_job(job)
            return job

        except asyncio.TimeoutError:
            err_dict = {
                "error_type": "ExecutionTimeoutError",
                "message": f"Task '{job.task_name}' timed out after {job.timeout_seconds}s",
                "classification": RetryClassification.UNCERTAIN.value,
            }
            job.outcome_uncertain = True
            job.status = "dead_letter"
            job.error = err_dict
            job.completed_at = utcnow_iso()
            await self.queue.update_job(job)
            logger.warning(redact_secrets(f"Job '{job.job_id}' timed out and moved to dead-letter queue. Outcome uncertain; no automatic replay."))
            return job

        except asyncio.CancelledError:
            job.status = "cancelled"
            job.is_cancelled = True
            job.completed_at = utcnow_iso()
            await self.queue.update_job(job)
            raise

        except Exception as exc:
            classification = classify_error(exc, is_mutation=True)
            err_dict = {
                "error_type": type(exc).__name__,
                "message": str(exc),
                "classification": classification.value,
            }
            job.error = err_dict
            job.completed_at = utcnow_iso()

            if classification == RetryClassification.TRANSIENT and job.retry_count < job.max_retries:
                job.retry_count += 1
                job.status = "queued"
                logger.warning(redact_secrets(f"Transient error on job '{job.job_id}'. Re-enqueuing (attempt {job.retry_count}/{job.max_retries})."))
                await self.queue.update_job(job)
                # Re-enqueue
                await self.queue.enqueue(
                    task_name=job.task_name,
                    payload=job.payload,
                    correlation_id=job.correlation_id,
                    priority=job.priority,
                    timeout_seconds=job.timeout_seconds,
                    max_retries=job.max_retries,
                )
            elif classification == RetryClassification.UNCERTAIN:
                job.outcome_uncertain = True
                job.status = "dead_letter"
                logger.error(redact_secrets(f"Uncertain side-effect error on job '{job.job_id}': {exc}. Moved to DLQ; replay prohibited."))
                await self.queue.update_job(job)
            else:
                job.status = "failed"
                logger.error(redact_secrets(f"Deterministic failure on job '{job.job_id}': {exc}"))
                await self.queue.update_job(job)

            return job


async def _run_worker_main() -> None:
    """CLI entrypoint for standalone background worker container (`python -m workers.worker`)."""
    import os
    import signal
    from apps.api.dependencies import get_background_worker
    from apps.api.main import register_worker_tasks

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        from workers.db_persistence import get_pg_engine, is_postgres_enabled
        if is_postgres_enabled():
            get_pg_engine()
    except Exception as exc:
        logger.warning(f"Worker DB initialization warning: {exc}")

    register_worker_tasks()
    worker = get_background_worker()
    worker.worker_id = os.environ.get("WORKER_ID", "chaos-intel-worker-01")
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                # Windows event loop fallback
                signal.signal(sig, lambda *_: stop_event.set())

    await worker.start()
    try:
        await stop_event.wait()
    finally:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(_run_worker_main())
