"""Chaos Engineering router: experiment creation, approvals, controlled dry-run execution."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.dependencies import get_chaos_engine_client, get_correlation_id, get_job_queue
from apps.api.middleware.auth import require_role, UserContext
from apps.api.schemas.chaos import (
    ChaosApprovalRequest,
    ChaosExecutionRequest,
    ChaosExperimentCreateRequest,
    ChaosExperimentResponse,
    ChaosReportResponse,
)
from apps.api.schemas.common import PaginatedResponse
from packages.clients.chaos_engine_client import ChaosEngineClient
from workers.queue import JobQueue

router = APIRouter(prefix="/chaos", tags=["Chaos Engine"])

_chaos_experiments: Dict[str, Dict[str, Any]] = {}
_chaos_runs: Dict[str, Dict[str, Any]] = {}


@router.post("/experiments", response_model=ChaosExperimentResponse, status_code=status.HTTP_201_CREATED)
async def create_chaos_experiment(
    payload: ChaosExperimentCreateRequest,
    correlation_id: str = Depends(get_correlation_id),
    client: ChaosEngineClient = Depends(get_chaos_engine_client),
    user: UserContext = Depends(require_role("operator")),
) -> ChaosExperimentResponse:
    """Create and validate a new controlled chaos experiment specification."""
    exp_id = f"exp-{uuid.uuid4().hex[:8]}"
    spec_dict = {
        "experiment_id": exp_id,
        "name": payload.name,
        "application_id": payload.application_id,
        "target_service_id": payload.target_service_id,
        "fault_type": payload.fault_type,
        "environment": payload.environment,
        "duration_seconds": payload.duration_seconds,
        "safety_decision_id": payload.safety_decision_id,
        "parameters": payload.parameters,
    }
    await client.create_experiment(spec_dict, correlation_id=correlation_id)
    record = {
        **spec_dict,
        "status": "validated",
        "requires_approval": True,
    }
    _chaos_experiments[exp_id] = record
    return ChaosExperimentResponse(**record)


@router.post("/experiments/{experiment_id}/approve", status_code=status.HTTP_200_OK)
async def approve_chaos_experiment(
    experiment_id: str,
    payload: ChaosApprovalRequest,
    correlation_id: str = Depends(get_correlation_id),
    client: ChaosEngineClient = Depends(get_chaos_engine_client),
    user: UserContext = Depends(require_role("admin")),
) -> Dict[str, Any]:
    """Record explicit human approval grant. Requires admin role."""
    exp = _chaos_experiments.get(experiment_id)
    if not exp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Chaos experiment '{experiment_id}' not found")

    res = await client.submit_approval(
        experiment_id=experiment_id,
        approved_by=payload.approved_by,
        grant_id=payload.grant_id,
        correlation_id=correlation_id,
    )
    exp["status"] = "approved"
    exp["approved_by"] = payload.approved_by
    exp["grant_id"] = payload.grant_id
    return res


@router.post("/executions", response_model=ChaosReportResponse, status_code=status.HTTP_202_ACCEPTED)
async def initiate_chaos_execution(
    payload: ChaosExecutionRequest,
    correlation_id: str = Depends(get_correlation_id),
    queue: JobQueue = Depends(get_job_queue),
    user: UserContext = Depends(require_role("operator")),
) -> ChaosReportResponse:
    """Initiate a controlled experiment run. Live execution is strictly disabled; dry_run must be True."""
    if not payload.dry_run:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Live chaos execution is disabled in this phase. dry_run must be True.",
        )

    exp = _chaos_experiments.get(payload.experiment_id)
    if not exp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Chaos experiment '{payload.experiment_id}' not found")

    if exp.get("status") != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Experiment '{payload.experiment_id}' has not received human safety approval grant.",
        )

    run_id = f"run-{uuid.uuid4().hex[:8]}"
    record = {
        "run_id": run_id,
        "experiment_id": payload.experiment_id,
        "verdict": "DRY_RUN_QUEUED",
        "dry_run": True,
        "live_execution": False,
        "fault_type": exp["fault_type"],
        "target_id": exp["target_service_id"],
        "recovery_status": "PENDING",
        "timeline": [],
    }
    _chaos_runs[run_id] = record

    await queue.enqueue(
        task_name="run_chaos_experiment",
        payload={"run_id": run_id, "experiment_id": payload.experiment_id, "application_id": payload.application_id},
        correlation_id=correlation_id,
    )
    return ChaosReportResponse(**record)


@router.get("/executions/{run_id}", response_model=ChaosReportResponse)
async def get_chaos_execution(
    run_id: str,
    correlation_id: str = Depends(get_correlation_id),
    user: UserContext = Depends(require_role("viewer")),
) -> ChaosReportResponse:
    """Retrieve chaos experiment execution report."""
    rec = _chaos_runs.get(run_id)
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Chaos run '{run_id}' not found")
    return ChaosReportResponse(**rec)


@router.get("/executions", response_model=PaginatedResponse[ChaosReportResponse])
async def list_chaos_executions(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    correlation_id: str = Depends(get_correlation_id),
    user: UserContext = Depends(require_role("viewer")),
) -> PaginatedResponse[ChaosReportResponse]:
    """Retrieve paginated list of chaos runs."""
    all_runs = [ChaosReportResponse(**r) for r in _chaos_runs.values()]
    total = len(all_runs)
    sliced = all_runs[offset : offset + limit]
    return PaginatedResponse(
        items=sliced,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + limit) < total,
    )

