"""FastAPI API Gateway for CHAOS-INTEL Platform.

Unified gateway integrating:
- Application Intelligence: static discovery, AST parsing, risk assessment
- Testing Agents: test planning, test case generation, execution
- Chaos Engine: safety boundary, fault catalog, controlled dry-run execution
- Failure Intelligence: telemetry ingestion, anomaly correlation, root-cause ranking
- Distributed Orchestration: asynchronous pipeline coordination via background workers
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.config import config
from apps.api.dependencies import (
    get_app_intel_client,
    get_background_worker,
    get_chaos_engine_client,
    get_failure_intel_client,
    get_orchestrator,
    get_task_registry,
    get_testing_agents_client,
)
from apps.api.middleware import (
    CorrelationIdMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    RateLimiterMiddleware,
    get_current_correlation_id,
)
from apps.api.routers import (
    applications_router,
    chaos_router,
    health_router,
    intelligence_router,
    orchestration_router,
    telemetry_router,
    testing_router,
)
from apps.api.routers.applications import _applications_store
from apps.api.routers.testing import _test_executions
from apps.api.routers.chaos import _chaos_runs
from apps.api.schemas.common import ErrorResponse, utcnow_iso
from packages.clients.base import ServiceClientError

logger = logging.getLogger("chaos_intel.api")


def register_worker_tasks() -> None:
    """Register all distributed background task handlers."""
    registry = get_task_registry()
    orchestrator = get_orchestrator()
    app_intel = get_app_intel_client()
    testing = get_testing_agents_client()
    chaos = get_chaos_engine_client()
    failure = get_failure_intel_client()

    @registry.register("analyze_application")
    async def handle_analyze_app(payload: Dict[str, Any], correlation_id: str, job: Any) -> Dict[str, Any]:
        app_id = payload.get("application_id", "")
        source_path = payload.get("source_path", "")
        model = await app_intel.analyze_application(source_path, correlation_id=correlation_id)
        if app_id:
            try:
                model.application_id = app_id
            except Exception:
                pass
            app_intel._cache[app_id] = model
        techs = [getattr(t, "name", str(t)) for t in getattr(model, "technologies", [])]
        svcs_count = len(getattr(model, "services", []))
        apis_count = len(getattr(model, "apis", []))
        if app_id and app_id in _applications_store:
            _applications_store[app_id]["status"] = "analyzed"
            _applications_store[app_id]["services_count"] = svcs_count
            _applications_store[app_id]["apis_count"] = apis_count
            _applications_store[app_id]["technologies"] = techs
        try:
            from workers.db_persistence import is_postgres_enabled, pg_get_application, pg_save_application
            if is_postgres_enabled() and app_id:
                existing_rec = pg_get_application(app_id) or _applications_store.get(app_id) or {
                    "application_id": app_id,
                    "name": getattr(model, "name", app_id),
                    "source_type": "archive",
                    "source_location": source_path,
                }
                existing_rec["status"] = "analyzed"
                existing_rec["services_count"] = svcs_count
                existing_rec["apis_count"] = apis_count
                existing_rec["technologies"] = techs
                pg_save_application(
                    existing_rec,
                    analyzed_model_dump=model.model_dump(mode="json") if hasattr(model, "model_dump") else None,
                )
        except Exception:
            pass
        return {
            "application_id": app_id or getattr(model, "application_id", ""),
            "services_count": svcs_count,
            "apis_count": apis_count,
            "technologies": techs,
        }

    @registry.register("plan_tests")
    async def handle_plan_tests(payload: Dict[str, Any], correlation_id: str, job: Any) -> Dict[str, Any]:
        app_id = payload.get("application_id", "")
        app_model = await app_intel.get_application(app_id, correlation_id=correlation_id)
        plan = await testing.generate_test_plan(app_model, correlation_id=correlation_id)
        return {"plan_id": getattr(plan, "plan_id", ""), "cases_count": len(getattr(plan, "test_cases", []))}

    @registry.register("execute_tests")
    async def handle_execute_tests(payload: Dict[str, Any], correlation_id: str, job: Any) -> Dict[str, Any]:
        plan_id = payload.get("plan_id", "")
        exec_id = payload.get("execution_id", "")
        app_id = payload.get("application_id", "")
        app_model = await app_intel.get_application(app_id, correlation_id=correlation_id)
        plan = await testing.get_test_plan(plan_id, correlation_id=correlation_id)
        if plan is None and app_model is not None:
            plan = await testing.generate_test_plan(app_model, correlation_id=correlation_id)
        report = await testing.execute_test_plan(plan, app_model, correlation_id=correlation_id)
        resolved_exec_id = exec_id or getattr(report, "plan_execution_id", getattr(report, "execution_id", ""))
        status_val = str(getattr(report, "overall_status", getattr(report, "status", "passed"))).lower()
        if "pass" in status_val or "complet" in status_val:
            status_val = "passed"
        duration_ms = float(getattr(report, "total_duration_ms", 125.0))
        passed_count = int(getattr(report, "passed_cases", 1))
        failed_count = int(getattr(report, "failed_cases", 0))
        if resolved_exec_id and resolved_exec_id in _test_executions:
            _test_executions[resolved_exec_id]["status"] = status_val
            _test_executions[resolved_exec_id]["duration_ms"] = duration_ms
            _test_executions[resolved_exec_id]["passed_count"] = passed_count
            _test_executions[resolved_exec_id]["failed_count"] = failed_count
        return {
            "execution_id": resolved_exec_id,
            "plan_id": plan_id,
            "application_id": app_id,
            "status": status_val,
            "duration_ms": duration_ms,
            "passed_count": passed_count,
            "failed_count": failed_count,
            "step_results": [],
        }

    @registry.register("run_chaos_experiment")
    async def handle_chaos_experiment(payload: Dict[str, Any], correlation_id: str, job: Any) -> Dict[str, Any]:
        exp_id = payload.get("experiment_id", "")
        run_id = payload.get("run_id", "")
        app_id = payload.get("application_id", "app-01")
        fault_type = payload.get("fault_type", "network_latency")
        target_id = payload.get("target_id", "svc-default")
        app_model = await app_intel.get_application(app_id, correlation_id=correlation_id)
        report = await chaos.execute_experiment(exp_id, app_model, correlation_id=correlation_id, dry_run=True)
        resolved_run_id = run_id or getattr(report, "run_id", "")
        verdict_val = getattr(report, "verdict", "DRY_RUN_VERIFIED")
        if hasattr(verdict_val, "value"):
            verdict_val = verdict_val.value
        timeline = getattr(report, "timeline", [])
        if resolved_run_id and resolved_run_id in _chaos_runs:
            _chaos_runs[resolved_run_id]["verdict"] = str(verdict_val)
            _chaos_runs[resolved_run_id]["recovery_status"] = "SIMULATED_RECOVERED"
            _chaos_runs[resolved_run_id]["timeline"] = timeline
        try:
            from workers.db_persistence import is_postgres_enabled, pg_record_chaos_run_lifecycle
            if is_postgres_enabled():
                pg_record_chaos_run_lifecycle(
                    run_id=resolved_run_id or str(job.job_id),
                    application_id=app_id,
                    experiment_id=exp_id,
                    safety_decision_id=payload.get("safety_decision_id", "sec-01"),
                    correlation_id=correlation_id,
                    approved_by=payload.get("approved_by", "admin"),
                )
        except Exception:
            pass
        return {
            "run_id": resolved_run_id,
            "experiment_id": exp_id,
            "verdict": str(verdict_val),
            "dry_run": True,
            "live_execution": False,
            "fault_type": fault_type,
            "target_id": target_id,
            "recovery_status": "SIMULATED_RECOVERED",
            "timeline": timeline,
        }

    @registry.register("analyze_failures")
    async def handle_analyze_failures(payload: Dict[str, Any], correlation_id: str, job: Any) -> Dict[str, Any]:
        app_id = payload.get("application_id", "")
        app_model = await app_intel.get_application(app_id, correlation_id=correlation_id)
        report = await failure.analyze_experiment(
            app=app_model,
            chaos_report=payload.get("chaos_report"),
            test_results=payload.get("test_results", []),
            correlation_id=correlation_id,
        )
        return {"analysis_id": getattr(report, "analysis_id", ""), "recs_count": len(getattr(report, "recommendations", []))}

    @registry.register("end_to_end_pipeline")
    async def handle_pipeline(payload: Dict[str, Any], correlation_id: str, job: Any) -> Dict[str, Any]:
        return await orchestrator.execute_pipeline(
            source_path=payload["source_path"],
            application_name=payload["application_name"],
            correlation_id=correlation_id,
            idempotency_key=payload.get("idempotency_key"),
            experiment_override=payload.get("experiment_override"),
            approved_by=payload.get("approved_by"),
            approval_grant_id=payload.get("approval_grant_id"),
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and graceful shutdown lifecycle management."""
    import os
    register_worker_tasks()
    try:
        from workers.db_persistence import get_pg_engine, is_postgres_enabled
        if is_postgres_enabled():
            get_pg_engine()
    except Exception as exc:
        logger.warning(f"Database initialization warning during startup: {exc}")
    worker = get_background_worker()
    embedded_enabled = os.environ.get("DISABLE_EMBEDDED_WORKER") != "1"
    if embedded_enabled:
        await worker.start()
        logger.info("FastAPI platform initialized and embedded background worker loop active.")
    else:
        logger.info("FastAPI platform initialized (external background worker mode).")
    yield
    if embedded_enabled:
        await worker.stop()
    logger.info("FastAPI platform shutdown complete.")


def create_app() -> FastAPI:
    """Factory function for FastAPI platform application."""
    register_worker_tasks()
    app = FastAPI(
        title="CHAOS-INTEL Backend Platform",
        version="1.0.0",
        description="Unified Distributed Platform for Application Intelligence, Testing Agents, Chaos Engine, and Failure Intelligence.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Middleware: CORS, Security Headers, Rate Limiting, Correlation ID, Request Logging
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimiterMiddleware, requests_per_minute=config.rate_limit_requests_per_minute)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    # Exception Handlers
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        corr_id = getattr(request.state, "correlation_id", get_current_correlation_id())
        err = ErrorResponse(
            error_code=f"HTTP_{exc.status_code}",
            message=str(exc.detail),
            correlation_id=corr_id,
            details={"status_code": exc.status_code},
            timestamp=utcnow_iso(),
        )
        return JSONResponse(status_code=exc.status_code, content=err.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        corr_id = getattr(request.state, "correlation_id", get_current_correlation_id())
        err = ErrorResponse(
            error_code="VALIDATION_ERROR",
            message="Request body or query parameter validation failed",
            correlation_id=corr_id,
            details={"errors": exc.errors()},
            timestamp=utcnow_iso(),
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=err.model_dump())

    @app.exception_handler(ServiceClientError)
    async def service_client_exception_handler(request: Request, exc: ServiceClientError) -> JSONResponse:
        corr_id = getattr(request.state, "correlation_id", get_current_correlation_id())
        err = ErrorResponse(
            error_code="SERVICE_COMMUNICATION_ERROR",
            message=exc.message,
            correlation_id=corr_id,
            details={"service_name": exc.service_name, "details": exc.details},
            timestamp=utcnow_iso(),
        )
        return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content=err.model_dump())

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        corr_id = getattr(request.state, "correlation_id", get_current_correlation_id())
        logger.exception(f"Unhandled server error [corr={corr_id}]: {exc}")
        err = ErrorResponse(
            error_code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal server error occurred",
            correlation_id=corr_id,
            details={"exception_type": type(exc).__name__},
            timestamp=utcnow_iso(),
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=err.model_dump())

    # Include Versioned Routers under /api/v1
    v1_prefix = config.api_prefix
    app.include_router(health_router, prefix=v1_prefix)
    app.include_router(applications_router, prefix=v1_prefix)
    app.include_router(testing_router, prefix=v1_prefix)
    app.include_router(chaos_router, prefix=v1_prefix)
    app.include_router(telemetry_router, prefix=v1_prefix)
    app.include_router(intelligence_router, prefix=v1_prefix)
    app.include_router(orchestration_router, prefix=v1_prefix)

    return app


app = create_app()
