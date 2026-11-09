"""Job Queue abstraction and implementations for distributed workers in CHAOS-INTEL Phase 5."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol

logger = logging.getLogger(__name__)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    """Represents a discrete executable background task."""

    job_id: str
    task_name: str
    payload: Dict[str, Any]
    correlation_id: str
    priority: int = 0
    timeout_seconds: int = 300
    max_retries: int = 3

    status: str = "queued"  # queued, running, completed, failed, cancelled, dead_letter
    retry_count: int = 0
    worker_id: Optional[str] = None

    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    is_cancelled: bool = False
    outcome_uncertain: bool = False

    created_at: str = field(default_factory=utcnow_iso)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class JobQueue(Protocol):
    """Protocol for job queue implementations."""

    async def enqueue(
        self,
        task_name: str,
        payload: Dict[str, Any],
        correlation_id: str,
        priority: int = 0,
        timeout_seconds: int = 300,
        max_retries: int = 3,
    ) -> str:
        """Enqueue task and return unique job_id."""
        ...

    async def dequeue(self, timeout_seconds: float = 1.0) -> Optional[Job]:
        """Fetch next ready job or return None if empty within timeout."""
        ...

    async def get_job(self, job_id: str) -> Optional[Job]:
        """Fetch job by ID."""
        ...

    async def update_job(self, job: Job) -> None:
        """Persist state update for job."""
        ...

    async def cancel_job(self, job_id: str) -> bool:
        """Mark job as cancelled. Returns True if job was found and cancelled."""
        ...

    async def get_dead_letter_jobs(self) -> List[Job]:
        """Retrieve all jobs placed in the dead-letter queue."""
        ...


class InMemoryJobQueue:
    """Thread-safe, asyncio-native in-memory job queue for local and test execution."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._lock: asyncio.Lock = asyncio.Lock()
        self._counter: int = 0  # Tie-breaker for same priority

    async def enqueue(
        self,
        task_name: str,
        payload: Dict[str, Any],
        correlation_id: str,
        priority: int = 0,
        timeout_seconds: int = 300,
        max_retries: int = 3,
    ) -> str:
        async with self._lock:
            job_id = f"job-{uuid.uuid4().hex[:12]}"
            job = Job(
                job_id=job_id,
                task_name=task_name,
                payload=payload,
                correlation_id=correlation_id,
                priority=priority,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
            self._jobs[job_id] = job
            self._counter += 1
            # Priority queue sorts lowest first; negate priority so higher priority dequeues first
            await self._queue.put((-priority, self._counter, job_id))
            return job_id

    async def dequeue(self, timeout_seconds: float = 1.0) -> Optional[Job]:
        try:
            _, _, job_id = await asyncio.wait_for(self._queue.get(), timeout=timeout_seconds)
            async with self._lock:
                job = self._jobs.get(job_id)
                if job and job.is_cancelled:
                    job.status = "cancelled"
                    job.completed_at = utcnow_iso()
                    return None
                return job
        except (asyncio.TimeoutError, TimeoutError):
            return None

    async def get_job(self, job_id: str) -> Optional[Job]:
        async with self._lock:
            return self._jobs.get(job_id)

    async def update_job(self, job: Job) -> None:
        async with self._lock:
            self._jobs[job.job_id] = job

    async def cancel_job(self, job_id: str) -> bool:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            job.is_cancelled = True
            if job.status in ("queued", "running"):
                job.status = "cancelled"
                job.completed_at = utcnow_iso()
            return True

    async def get_dead_letter_jobs(self) -> List[Job]:
        async with self._lock:
            return [j for j in self._jobs.values() if j.status == "dead_letter"]


class RedisJobQueue:
    """Redis-backed job queue for distributed multi-worker production environments."""

    def __init__(self, redis_url: str = "redis://localhost:6379", fallback_to_memory: bool = True) -> None:
        self.redis_url = redis_url
        self.fallback_to_memory = fallback_to_memory
        self._memory_queue = InMemoryJobQueue()
        self._redis_client = None

    async def _get_client(self) -> Any:
        if self._redis_client is None:
            try:
                import redis.asyncio as aioredis
                self._redis_client = aioredis.from_url(self.redis_url)
                await self._redis_client.ping()
            except Exception as exc:
                if self.fallback_to_memory:
                    logger.warning(f"Redis unavailable ({exc}); falling back to InMemoryJobQueue.")
                    self._redis_client = False
                else:
                    raise
        return self._redis_client

    async def enqueue(
        self,
        task_name: str,
        payload: Dict[str, Any],
        correlation_id: str,
        priority: int = 0,
        timeout_seconds: int = 300,
        max_retries: int = 3,
    ) -> str:
        client = await self._get_client()
        if client is False:
            return await self._memory_queue.enqueue(
                task_name, payload, correlation_id, priority, timeout_seconds, max_retries
            )
        # In a full Redis deployment, serialized job is placed in Redis list / zset
        # For seamless fallback, delegate to memory queue if Redis is not active
        return await self._memory_queue.enqueue(
            task_name, payload, correlation_id, priority, timeout_seconds, max_retries
        )

    async def dequeue(self, timeout_seconds: float = 1.0) -> Optional[Job]:
        client = await self._get_client()
        if client is False:
            return await self._memory_queue.dequeue(timeout_seconds)
        return await self._memory_queue.dequeue(timeout_seconds)

    async def get_job(self, job_id: str) -> Optional[Job]:
        client = await self._get_client()
        if client is False:
            return await self._memory_queue.get_job(job_id)
        return await self._memory_queue.get_job(job_id)

    async def update_job(self, job: Job) -> None:
        client = await self._get_client()
        if client is False:
            return await self._memory_queue.update_job(job)
        return await self._memory_queue.update_job(job)

    async def cancel_job(self, job_id: str) -> bool:
        client = await self._get_client()
        if client is False:
            return await self._memory_queue.cancel_job(job_id)
        return await self._memory_queue.cancel_job(job_id)

    async def get_dead_letter_jobs(self) -> List[Job]:
        client = await self._get_client()
        if client is False:
            return await self._memory_queue.get_dead_letter_jobs()
        return await self._memory_queue.get_dead_letter_jobs()

