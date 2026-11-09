"""Failure Intelligence router: anomaly detection, failure correlation, recommendations."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from apps.api.dependencies import (
    get_app_intel_client,
    get_correlation_id,
    get_failure_intel_client,
    get_job_queue,
)
from apps.api.middleware.auth import require_role, UserContext
from apps.api.schemas.intelligence import (
    FailureAnalysisRequest,
    FailureAnalysisResponse,
    RecommendationListResponse,
)
from packages.clients.app_intel_client import ApplicationIntelligenceClient
from packages.clients.failure_intel_client import FailureIntelligenceClient
from workers.queue import JobQueue

router = APIRouter(prefix="/intelligence", tags=["Failure Intelligence"])

_analysis_reports: Dict[str, Dict[str, Any]] = {}
_recommendations_store: List[Dict[str, Any]] = []


@router.post("/analyze", response_model=FailureAnalysisResponse, status_code=status.HTTP_202_ACCEPTED)
async def analyze_failure(
    payload: FailureAnalysisRequest,
    correlation_id: str = Depends(get_correlation_id),
    client: FailureIntelligenceClient = Depends(get_failure_intel_client),
    app_client: ApplicationIntelligenceClient = Depends(get_app_intel_client),
    queue: JobQueue = Depends(get_job_queue),
    user: UserContext = Depends(require_role("operator")),
) -> FailureAnalysisResponse:
    """Trigger multi-modal failure correlation, anomaly detection, and root-cause analysis."""
    analysis_id = f"fa-{uuid.uuid4().hex[:12]}"

    # Use real application model if previously analyzed
    real_app = await app_client.get_application(payload.application_id, correlation_id=correlation_id)
    if real_app is not None:
        target_app = real_app
    else:
        class _MockApp:
            application_id = payload.application_id
            name = "TargetApp"
            services = []
            apis = []
            dependencies = []
            risks = []
            architecture = None
        target_app = _MockApp()

    class _MockChaosReport:
        report_id = payload.chaos_report_id or "rpt-mock"
        experiment_id = "exp-01"
        target_id = "svc-01"
        fault_type = "network_latency"
        verdict = "DRY_RUN_VERIFIED"
        recovery_classification = "unknown"
        abort = None
        observation = None

    rep = await client.analyze_experiment(
        app=target_app,
        chaos_report=_MockChaosReport(),
        test_results=[],
        correlation_id=correlation_id,
    )

    recs = [r.model_dump() if hasattr(r, "model_dump") else dict(r) for r in getattr(rep, "recommendations", [])]
    causes = [c.model_dump() if hasattr(c, "model_dump") else dict(c) for c in getattr(rep, "probable_root_causes", [])]

    record = {
        "analysis_id": getattr(rep, "analysis_id", analysis_id),
        "application_id": payload.application_id,
        "correlation_id": correlation_id,
        "anomalies_count": len(getattr(rep, "observed_anomalies", [])),
        "probable_root_causes": causes,
        "recommendations_count": len(recs),
        "recovery_status": getattr(rep, "recovery_behavior", {}).get("recovery_status", "UNKNOWN"),
    }
    _analysis_reports[record["analysis_id"]] = record
    _recommendations_store.extend(recs)

    return FailureAnalysisResponse(**record)


@router.get("/reports/{analysis_id}", response_model=FailureAnalysisResponse)
async def get_analysis_report(
    analysis_id: str,
    correlation_id: str = Depends(get_correlation_id),
    user: UserContext = Depends(require_role("viewer")),
) -> FailureAnalysisResponse:
    """Retrieve failure intelligence analysis report by ID."""
    rep = _analysis_reports.get(analysis_id)
    if not rep:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Analysis report '{analysis_id}' not found")
    return FailureAnalysisResponse(**rep)


@router.get("/recommendations", response_model=RecommendationListResponse)
async def list_recommendations(
    target_service: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    correlation_id: str = Depends(get_correlation_id),
    user: UserContext = Depends(require_role("viewer")),
) -> RecommendationListResponse:
    """Retrieve filtered, prioritized actionable recommendations."""
    filtered = _recommendations_store
    if target_service:
        filtered = [r for r in filtered if r.get("target_service") == target_service]
    if priority:
        filtered = [r for r in filtered if r.get("priority") == priority]

    sliced = filtered[offset : offset + limit]
    return RecommendationListResponse(
        recommendations=sliced,
        total=len(filtered),
    )
