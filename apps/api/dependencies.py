"""FastAPI dependencies for service clients, queue, orchestrator, and request context."""

from __future__ import annotations

from typing import Optional
from fastapi import Request

from packages.clients.app_intel_client import ApplicationIntelligenceClient
from packages.clients.testing_agents_client import TestingAgentsClient
from packages.clients.chaos_engine_client import ChaosEngineClient
from packages.clients.failure_intel_client import FailureIntelligenceClient
from workers.queue import InMemoryJobQueue, JobQueue
from workers.task_registry import TaskRegistry, default_task_registry
from workers.orchestrator import DistributedOrchestrator
from workers.worker import BackgroundWorker

# Global shared singletons for in-process execution and state tracking
_global_queue: JobQueue = InMemoryJobQueue()
_global_registry: TaskRegistry = default_task_registry

_app_intel_client = ApplicationIntelligenceClient()
_testing_agents_client = TestingAgentsClient()
_chaos_engine_client = ChaosEngineClient()
_failure_intel_client = FailureIntelligenceClient()

_global_orchestrator = DistributedOrchestrator(
    app_intel_client=_app_intel_client,
    testing_agents_client=_testing_agents_client,
    chaos_engine_client=_chaos_engine_client,
    failure_intel_client=_failure_intel_client,
)

_global_worker = BackgroundWorker(
    queue=_global_queue,
    registry=_global_registry,
    worker_id="api-background-worker-01",
)


def get_correlation_id(request: Request) -> str:
    """Retrieve correlation ID from request state."""
    return getattr(request.state, "correlation_id", "corr-unknown")


def get_job_queue() -> JobQueue:
    return _global_queue


def get_task_registry() -> TaskRegistry:
    return _global_registry


def get_orchestrator() -> DistributedOrchestrator:
    return _global_orchestrator


def get_app_intel_client() -> ApplicationIntelligenceClient:
    return _app_intel_client


def get_testing_agents_client() -> TestingAgentsClient:
    return _testing_agents_client


def get_chaos_engine_client() -> ChaosEngineClient:
    return _chaos_engine_client


def get_failure_intel_client() -> FailureIntelligenceClient:
    return _failure_intel_client


def get_background_worker() -> BackgroundWorker:
    return _global_worker

