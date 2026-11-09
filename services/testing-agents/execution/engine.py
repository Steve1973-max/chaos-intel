"""Automated Test Execution Engine for CHAOS-INTEL Phase 3B.

Executes explicitly approved functional, API, UI, and workflow test plans and
test cases with bounded concurrency, configurable timeouts, cancellation tokens,
isolated execution contexts, automatic LIFO cleanup after failures, secret
redaction, and deterministic schema-validated result normalization.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from adapters.base import AdapterExecutionOutput
from execution.execution_context import CancellationToken, IsolatedExecutionContext, utcnow_iso
from execution.execution_registry import ExecutionAdapterRegistry
from execution.result_collector import (
    ExecutionErrorDetail,
    PlanExecutionReport,
    ResultCollector,
    StepExecutionResult,
    TestExecutionResult,
)
from execution.sandbox import (
    ExecutionApproval,
    ExecutionCancelledError,
    ExecutionSafetyError,
    SandboxPolicy,
    TargetSandbox,
    UnauthorizedPlanError,
)
from schemas import SafetyDecision, TestCase, TestPlan


def _generate_execution_id(plan_id: str, test_case_id: str, nonce: str) -> str:
    digest = hashlib.sha256(f"{plan_id}:{test_case_id}:{nonce}".encode("utf-8")).hexdigest()[:16]
    return f"exec-{digest}"


class TestExecutionEngine:
    """Modular, safety-enforced async test execution engine."""

    __test__ = False

    def __init__(
        self,
        sandbox: Optional[TargetSandbox] = None,
        registry: Optional[ExecutionAdapterRegistry] = None,
        result_collector: Optional[ResultCollector] = None,
    ) -> None:
        self.sandbox = sandbox or TargetSandbox(SandboxPolicy())
        self.registry = registry or ExecutionAdapterRegistry(register_defaults=True)
        self.result_collector = result_collector if result_collector is not None else ResultCollector()
        self.current_active_executions: int = 0
        self.peak_active_executions: int = 0

    def _verify_test_case_approval(
        self,
        plan_id: str,
        application_id: str,
        approval: Any,
    ) -> None:
        """Verify explicit authorization before executing any single test case."""
        if approval is None:
            raise UnauthorizedPlanError(
                f"Execution blocked: Test case in plan '{plan_id}' has no execution approval."
            )

        if isinstance(approval, ExecutionApproval):
            if not approval.approved:
                raise UnauthorizedPlanError(
                    f"Execution blocked: ExecutionApproval '{approval.approval_id}' is not approved."
                )
            if approval.plan_id != plan_id:
                raise UnauthorizedPlanError(
                    f"Execution blocked: ExecutionApproval plan_id '{approval.plan_id}' does not match '{plan_id}'."
                )
            if approval.application_id != application_id:
                raise UnauthorizedPlanError(
                    f"Execution blocked: ExecutionApproval application_id '{approval.application_id}' "
                    f"does not match '{application_id}'."
                )
            return

        if isinstance(approval, SafetyDecision):
            if not approval.allowed or approval.decision != "approved":
                raise UnauthorizedPlanError(
                    f"SafetyDecision '{approval.decision_id}' has decision='{approval.decision}' "
                    f"(allowed={approval.allowed}); execution is blocked."
                )
            if approval.application_id != application_id:
                raise UnauthorizedPlanError(
                    f"SafetyDecision application_id '{approval.application_id}' does not match '{application_id}'."
                )
            return

        raise UnauthorizedPlanError(f"Unsupported approval object type: {type(approval).__name__}")

    async def execute_test_case(
        self,
        test_case: TestCase,
        plan_id: str,
        approval: Any,
        *,
        application_id: str = "app-default",
        correlation_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        cancellation_token: Optional[CancellationToken] = None,
        initial_variables: Optional[Dict[str, Any]] = None,
        setup_hook: Optional[Callable[[IsolatedExecutionContext], Any]] = None,
        raise_on_safety_error: bool = True,
    ) -> TestExecutionResult:
        """Execute a single approved TestCase inside an isolated execution context.

        Guarantees:
        - Requires explicit `approval` (`ExecutionApproval` or `SafetyDecision`).
        - Enforces `timeout_seconds`.
        - Honors `cancellation_token` before and during execution.
        - Never automatically replays uncertain external operations.
        - Always executes registered cleanup callbacks in LIFO order inside `finally:`.
        - Validates and normalizes the resulting `TestExecutionResult` against `test-run.schema.json`.
        """
        # Resolve application_id from approval if not explicitly provided
        resolved_app_id = application_id
        if resolved_app_id == "app-default" and hasattr(approval, "application_id") and approval.application_id:
            resolved_app_id = str(approval.application_id)

        # 1. Verify plan / test-case authorization first
        self._verify_test_case_approval(
            plan_id=plan_id,
            application_id=resolved_app_id,
            approval=approval,
        )

        # 2. Compute timeout
        policy = self.sandbox.policy
        effective_timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(policy.default_timeout_seconds)
        )

        corr_id = correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        exec_id = execution_id or _generate_execution_id(plan_id, test_case.test_case_id, uuid.uuid4().hex)
        token = cancellation_token or CancellationToken()

        context = IsolatedExecutionContext(
            plan_id=plan_id,
            test_case_id=test_case.test_case_id,
            application_id=resolved_app_id,
            sandbox=self.sandbox,
            correlation_id=corr_id,
            execution_id=exec_id,
            timeout_seconds=effective_timeout,
            cancellation_token=token,
            initial_variables=initial_variables,
        )

        adapter = self.registry.resolve_for_test_case(test_case)
        adapter_meta = adapter.metadata()

        started_at = utcnow_iso()
        t_start = time.perf_counter()

        status: str = "unknown"
        step_results: List[StepExecutionResult] = []
        error_details: Optional[ExecutionErrorDetail] = None
        output_meta: Dict[str, Any] = {}
        pending_safety_error: Optional[ExecutionSafetyError] = None

        self.current_active_executions += 1
        if self.current_active_executions > self.peak_active_executions:
            self.peak_active_executions = self.current_active_executions

        try:
            if setup_hook is not None:
                hook_res = setup_hook(context)
                if asyncio.iscoroutine(hook_res):
                    await hook_res

            # Check cancellation prior to adapter invocation
            context.check_cancelled()

            context.log(
                "INFO",
                "test_case_execution_started",
                adapter_id=adapter_meta.adapter_id,
                target_id=test_case.target_id,
                timeout_seconds=effective_timeout,
            )

            output: AdapterExecutionOutput = await asyncio.wait_for(
                adapter.execute(test_case, context),
                timeout=effective_timeout,
            )

            status = output.status
            step_results = list(output.step_results)
            error_details = output.error_details
            output_meta = dict(output.metadata)

        except ExecutionCancelledError as exc:
            status = "cancelled"
            context.log("WARNING", "test_case_execution_cancelled", reason=str(exc))
            error_details = ExecutionErrorDetail(
                error_type="ExecutionCancelledError",
                message=str(exc),
                failed_stage="step",
                failed_target=test_case.target_id,
                outcome_uncertain=False,
            )

        except asyncio.CancelledError as exc:
            status = "cancelled"
            context.log("WARNING", "test_case_task_cancelled", reason=str(exc))
            error_details = ExecutionErrorDetail(
                error_type="CancelledError",
                message=str(exc) or "Execution task was cancelled.",
                failed_stage="step",
                failed_target=test_case.target_id,
                outcome_uncertain=False,
            )

        except asyncio.TimeoutError:
            status = "timed_out"
            msg = f"Test case '{test_case.test_case_id}' timed out after {effective_timeout}s."
            context.log("ERROR", "test_case_execution_timed_out", timeout_seconds=effective_timeout)
            error_details = ExecutionErrorDetail(
                error_type="ExecutionTimeoutError",
                message=msg,
                failed_stage="step",
                failed_target=test_case.target_id,
                outcome_uncertain=True,
            )
            step_results.append(
                StepExecutionResult(
                    step_number=len(step_results) + 1,
                    step_name="execution_timeout_guard",
                    stage="step",
                    status="timed_out",
                    started_at=started_at,
                    ended_at=utcnow_iso(),
                    duration_ms=round((time.perf_counter() - t_start) * 1000.0, 3),
                    details={"timeout_seconds": effective_timeout},
                    error=error_details,
                    evidence_refs=[],
                )
            )

        except ExecutionSafetyError as exc:
            status = "failed"
            context.log("ERROR", "safety_violation_blocked_execution", error_type=type(exc).__name__, error=str(exc))
            error_details = ExecutionErrorDetail(
                error_type=type(exc).__name__,
                message=str(exc),
                failed_stage="precondition",
                failed_target=test_case.target_id,
                outcome_uncertain=False,
            )
            if raise_on_safety_error:
                pending_safety_error = exc

        except Exception as exc:
            status = "failed"
            context.log("ERROR", "unhandled_adapter_exception", error_type=type(exc).__name__, error=str(exc))
            error_details = ExecutionErrorDetail(
                error_type=type(exc).__name__,
                message=str(exc),
                failed_stage="step",
                failed_target=test_case.target_id,
                outcome_uncertain=False,
            )

        finally:
            self.current_active_executions = max(0, self.current_active_executions - 1)
            # Cleanup MUST run safely even on failure, timeout, safety violation, or cancellation
            await context.run_cleanup()

        ended_at = utcnow_iso()
        duration_ms = round((time.perf_counter() - t_start) * 1000.0, 3)

        result = TestExecutionResult(
            execution_id=exec_id,
            test_case_id=test_case.test_case_id,
            plan_id=plan_id,
            application_id=resolved_app_id,
            adapter_id=adapter_meta.adapter_id,
            status=status,  # type: ignore[arg-type]
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            correlation_id=corr_id,
            cleanup_completed=context.cleanup_completed,
            step_results=step_results,
            error_details=error_details,
            evidence_references=list(context.evidence_references),
            metadata={
                **output_meta,
                "test_type": test_case.test_type,
                "target_id": test_case.target_id,
                "log_count": len(context.logs),
                "cleanup_errors": list(context.cleanup_errors),
                "logs": [entry.model_dump() for entry in context.logs],
            },
        )

        normalized = self.result_collector.normalize_and_record(result)

        if pending_safety_error is not None:
            raise pending_safety_error

        return normalized

    async def execute_plan(
        self,
        plan: TestPlan,
        approval: Any,
        *,
        correlation_id: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        cancellation_token: Optional[CancellationToken] = None,
        initial_variables: Optional[Dict[str, Any]] = None,
        raise_on_safety_error: bool = False,
    ) -> PlanExecutionReport:
        """Execute all TestCases in an explicitly approved TestPlan with bounded concurrency."""
        self.sandbox.validate_plan_authorization(plan, approval)

        corr_id = (
            correlation_id
            or getattr(plan, "correlation_id", None)
            or (plan.metadata or {}).get("correlation_id")
            or f"corr-{uuid.uuid4().hex[:12]}"
        )
        token = cancellation_token or CancellationToken()
        max_concurrency = max(1, int(self.sandbox.policy.max_concurrency))
        semaphore = asyncio.Semaphore(max_concurrency)

        started_at = utcnow_iso()
        t_start = time.perf_counter()

        # Sort test cases deterministically by rank then test_case_id
        ordered_cases = sorted(
            plan.test_cases,
            key=lambda tc: (tc.rank if tc.rank is not None else 999999, tc.test_case_id),
        )

        async def _run_bounded(tc: TestCase) -> TestExecutionResult:
            async with semaphore:
                return await self.execute_test_case(
                    test_case=tc,
                    plan_id=plan.plan_id,
                    approval=approval,
                    application_id=plan.application_id,
                    correlation_id=corr_id,
                    timeout_seconds=timeout_seconds,
                    cancellation_token=token,
                    initial_variables=dict(initial_variables) if initial_variables else None,
                    raise_on_safety_error=raise_on_safety_error,
                )

        if ordered_cases:
            results = list(await asyncio.gather(*(_run_bounded(tc) for tc in ordered_cases)))
        else:
            results = []

        ended_at = utcnow_iso()
        duration_ms = round((time.perf_counter() - t_start) * 1000.0, 3)

        summary = ResultCollector.build_summary(results)
        if summary.cancelled > 0 and summary.passed == 0 and summary.failed == 0 and summary.timed_out == 0:
            plan_status = "cancelled"
        elif summary.failed == 0 and summary.timed_out == 0 and summary.unknown == 0 and summary.cancelled == 0:
            plan_status = "completed"
        elif summary.passed > 0:
            plan_status = "partial_failure"
        else:
            plan_status = "failed"

        plan_exec_id = f"plan-exec-{hashlib.sha256(f'{plan.plan_id}:{started_at}'.encode('utf-8')).hexdigest()[:12]}"

        return PlanExecutionReport(
            plan_execution_id=plan_exec_id,
            plan_id=plan.plan_id,
            application_id=plan.application_id,
            correlation_id=corr_id,
            status=plan_status,  # type: ignore[arg-type]
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            summary=summary,
            results=results,
            metadata={"max_concurrency": max_concurrency},
        )

    def execute_test_case_sync(
        self,
        test_case: TestCase,
        plan_id: str,
        approval: Any,
        **kwargs: Any,
    ) -> TestExecutionResult:
        """Synchronous convenience wrapper around `execute_test_case`."""
        return asyncio.run(
            self.execute_test_case(
                test_case=test_case,
                plan_id=plan_id,
                approval=approval,
                **kwargs,
            )
        )

    def execute_plan_sync(
        self,
        plan: TestPlan,
        approval: Any,
        **kwargs: Any,
    ) -> PlanExecutionReport:
        """Synchronous convenience wrapper around `execute_plan`."""
        return asyncio.run(
            self.execute_plan(
                plan=plan,
                approval=approval,
                **kwargs,
            )
        )
