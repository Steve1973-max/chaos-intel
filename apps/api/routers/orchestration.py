"""Distributed Orchestration router coordinating the 10-step multi-agent workflow."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.dependencies import get_correlation_id, get_job_queue, get_orchestrator
from apps.api.middleware.auth import require_role, UserContext
from apps.api.schemas.common import PaginatedResponse
from apps.api.schemas.orchestration import (
    PipelineJobStatusResponse,
    PipelineTriggerRequest,
)
from workers.orchestrator import DistributedOrchestrator
from workers.queue import JobQueue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orchestration", tags=["Distributed Orchestration"])


@router.post("/pipeline", response_model=PipelineJobStatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_pipeline(
    payload: PipelineTriggerRequest,
    correlation_id: str = Depends(get_correlation_id),
    queue: JobQueue = Depends(get_job_queue),
    orchestrator: DistributedOrchestrator = Depends(get_orchestrator),
    user: UserContext = Depends(require_role("operator")),
) -> PipelineJobStatusResponse:
    """Trigger the 10-step distributed chaos-intelligence orchestration workflow.

    Enforces idempotency if an idempotency_key is supplied.
    """
    job_payload = {
        "source_path": payload.source_path,
        "application_name": payload.application_name,
        "idempotency_key": payload.idempotency_key,
        "approved_by": payload.approved_by or user.principal_id,
        "approval_grant_id": payload.approval_grant_id,
        "experiment_override": payload.experiment_override,
    }

    job_id = await queue.enqueue(
        task_name="end_to_end_pipeline",
        payload=job_payload,
        correlation_id=correlation_id,
        priority=10,  # High priority for pipeline runs
    )

    job = await queue.get_job(job_id)
    return PipelineJobStatusResponse(
        job_id=job_id,
        status=getattr(job, "status", "queued"),
        correlation_id=correlation_id,
        created_at=getattr(job, "created_at", ""),
        started_at=getattr(job, "started_at", None),
        completed_at=getattr(job, "completed_at", None),
        result=getattr(job, "result", None),
        error=getattr(job, "error", None),
    )


@router.get("/pipeline/{job_id}", response_model=PipelineJobStatusResponse)
async def get_pipeline_job_status(
    job_id: str,
    correlation_id: str = Depends(get_correlation_id),
    queue: JobQueue = Depends(get_job_queue),
    user: UserContext = Depends(require_role("viewer")),
) -> PipelineJobStatusResponse:
    """Retrieve execution status, artifacts, and timeline for an orchestrated pipeline job."""
    job = await queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")

    return PipelineJobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        correlation_id=job.correlation_id,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        result=job.result,
        error=job.error,
    )


@router.post("/pipeline/{job_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_pipeline_job(
    job_id: str,
    correlation_id: str = Depends(get_correlation_id),
    queue: JobQueue = Depends(get_job_queue),
    user: UserContext = Depends(require_role("operator")),
) -> Dict[str, Any]:
    """Request graceful cancellation of a running or queued pipeline job."""
    cancelled = await queue.cancel_job(job_id)
    if not cancelled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")
    return {
        "job_id": job_id,
        "status": "cancelled",
        "correlation_id": correlation_id,
    }


@router.get("/jobs", response_model=PaginatedResponse[PipelineJobStatusResponse])
async def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    correlation_id: str = Depends(get_correlation_id),
    queue: JobQueue = Depends(get_job_queue),
    user: UserContext = Depends(require_role("viewer")),
) -> PaginatedResponse[PipelineJobStatusResponse]:
    """Retrieve paginated list of background jobs."""
    try:
        from workers.db_persistence import is_postgres_enabled, pg_list_jobs
        from workers.queue import Job
        if is_postgres_enabled():
            jobs_dict_ref = getattr(queue, "_jobs", None)
            if isinstance(jobs_dict_ref, dict):
                for r in pg_list_jobs():
                    jobs_dict_ref[r["job_id"]] = Job(**r)
    except Exception:
        pass
    jobs_dict = getattr(queue, "_jobs", {})
    all_jobs = [
        PipelineJobStatusResponse(
            job_id=j.job_id,
            status=j.status,
            correlation_id=j.correlation_id,
            created_at=j.created_at,
            started_at=j.started_at,
            completed_at=j.completed_at,
            result=j.result,
            error=j.error,
        )
        for j in jobs_dict.values()
    ]
    total = len(all_jobs)
    sliced = all_jobs[offset : offset + limit]
    return PaginatedResponse(
        items=sliced,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
    )

