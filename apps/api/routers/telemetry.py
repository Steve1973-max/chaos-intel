"""Telemetry ingestion router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from apps.api.dependencies import get_correlation_id, get_failure_intel_client
from apps.api.middleware.auth import require_role, UserContext
from apps.api.schemas.telemetry import TelemetryIngestRequest, TelemetryIngestResponse
from packages.clients.failure_intel_client import FailureIntelligenceClient

router = APIRouter(prefix="/telemetry", tags=["Telemetry"])


@router.post("/ingest", response_model=TelemetryIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_telemetry(
    payload: TelemetryIngestRequest,
    correlation_id: str = Depends(get_correlation_id),
    client: FailureIntelligenceClient = Depends(get_failure_intel_client),
    user: UserContext = Depends(require_role("operator")),
) -> TelemetryIngestResponse:
    """Ingest normalized metrics, structured logs, and distributed trace spans."""
    res = await client.ingest_telemetry(
        correlation_id=correlation_id,
        metrics=payload.metrics,
        logs=payload.logs,
        spans=payload.spans,
    )
    return TelemetryIngestResponse(
        status="ACCEPTED",
        metrics_count=res.get("metrics_ingested", len(payload.metrics)),
        logs_count=res.get("logs_ingested", len(payload.logs)),
        spans_count=res.get("spans_ingested", len(payload.spans)),
        correlation_id=correlation_id,
    )

