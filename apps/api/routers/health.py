"""Health and subsystem monitoring router."""

from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, Depends

from apps.api.config import config
from apps.api.dependencies import (
    get_app_intel_client,
    get_chaos_engine_client,
    get_correlation_id,
    get_failure_intel_client,
    get_job_queue,
    get_testing_agents_client,
)
from apps.api.schemas.common import HealthResponse
from packages.clients.app_intel_client import ApplicationIntelligenceClient
from packages.clients.chaos_engine_client import ChaosEngineClient
from packages.clients.failure_intel_client import FailureIntelligenceClient
from packages.clients.testing_agents_client import TestingAgentsClient
from workers.queue import JobQueue

router = APIRouter(prefix="/health", tags=["Health & Diagnostics"])


@router.get("", response_model=HealthResponse)
async def get_health(correlation_id: str = Depends(get_correlation_id)) -> HealthResponse:
    """Return platform operational status."""
    return HealthResponse(
        status="HEALTHY",
        version="1.0.0",
        environment=config.environment,
        services={"platform_api": "HEALTHY", "correlation_id": correlation_id},
    )


@router.get("/services", response_model=HealthResponse)
async def get_services_health(
    correlation_id: str = Depends(get_correlation_id),
    app_intel: ApplicationIntelligenceClient = Depends(get_app_intel_client),
    testing: TestingAgentsClient = Depends(get_testing_agents_client),
    chaos: ChaosEngineClient = Depends(get_chaos_engine_client),
    failure: FailureIntelligenceClient = Depends(get_failure_intel_client),
    queue: JobQueue = Depends(get_job_queue),
) -> HealthResponse:
    """Execute dynamic health checks across all four core subsystem services and job queue."""
    ai_health = await app_intel.check_health()
    ta_health = await testing.check_health()
    ce_health = await chaos.check_health()
    fi_health = await failure.check_health()

    dlq_count = len(await queue.get_dead_letter_jobs())

    services_status = {
        "application_intelligence": ai_health,
        "testing_agents": ta_health,
        "chaos_engine": ce_health,
        "failure_intelligence": fi_health,
        "job_queue": {
            "status": "HEALTHY",
            "type": type(queue).__name__,
            "dead_letter_jobs_count": dlq_count,
        },
    }

    all_healthy = all(
        s.get("status") in ("HEALTHY", "OK") for s in (ai_health, ta_health, ce_health, fi_health)
    )
    overall = "HEALTHY" if all_healthy else "DEGRADED"

    return HealthResponse(
        status=overall,
        version="1.0.0",
        environment=config.environment,
        services=services_status,
    )

