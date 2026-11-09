import inspect
import time
from typing import Any, Callable, Dict, List, Optional

try:
    from ..execution.execution_context import IsolatedExecutionContext, utcnow_iso
    from ..execution.result_collector import ExecutionErrorDetail, StepExecutionResult
    from ..execution.sandbox import (
        ExecutionCancelledError,
        ExecutionSafetyError,
        SecretRedactor,
    )
    from ..schemas import TestCase
    from .api_adapter import ApiTestAdapter
    from .base import (
        AdapterExecutionOutput,
        AdapterMetadata,
        BaseTestExecutionAdapter,
        UncertainOperationError,
    )
    from .ui_adapter import UiTestAdapter
except ImportError:
    from execution.execution_context import IsolatedExecutionContext, utcnow_iso  # type: ignore[no-redef]
    from execution.result_collector import ExecutionErrorDetail, StepExecutionResult  # type: ignore[no-redef]
    from execution.sandbox import (  # type: ignore[no-redef]
        ExecutionCancelledError,
        ExecutionSafetyError,
        SecretRedactor,
    )
    from schemas import TestCase  # type: ignore[no-redef]
    from adapters.api_adapter import ApiTestAdapter  # type: ignore[no-redef]
    from adapters.base import (  # type: ignore[no-redef]
        AdapterExecutionOutput,
        AdapterMetadata,
        BaseTestExecutionAdapter,
        UncertainOperationError,
    )
    from adapters.ui_adapter import UiTestAdapter  # type: ignore[no-redef]


class WorkflowTestAdapter(BaseTestExecutionAdapter):
    """
    Executes multi-step user journeys with:
    - Explicit precondition evaluation
    - Multi-step execution across API, UI, and custom step handlers with state passing
    - Step-level execution results and skipped-step tracking on early failure
    - Postcondition evaluation
    - Exact failure localization (stage, step_number, step_name, service_id, target)
    - Zero automatic replay of uncertain operations
    """

    def __init__(
        self,
        api_adapter: Optional[ApiTestAdapter] = None,
        ui_adapter: Optional[UiTestAdapter] = None,
    ) -> None:
        self.api_adapter = api_adapter or ApiTestAdapter()
        self.ui_adapter = ui_adapter or UiTestAdapter()

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            adapter_id="workflow-adapter-v1",
            adapter_type="workflow",
            version="1.0.0",
            supported_target_types=["workflow", "service", "dependency"],
            supported_test_types=["workflow_resilience", "failover", "dependency_resilience", "degradation"],
            supports_live_chaos=False,
        )

    @staticmethod
    def _evaluate_condition(cond: Dict[str, Any], context: IsolatedExecutionContext) -> None:
        cond_name = str(cond.get("name", "condition"))
        if "required_variable" in cond:
            var_name = str(cond["required_variable"])
            if var_name not in context.variables or context.variables[var_name] is None:
                raise AssertionError(f"Condition '{cond_name}' failed: required variable '{var_name}' is missing.")
            if "expected_value" in cond and context.variables[var_name] != cond["expected_value"]:
                raise AssertionError(
                    f"Condition '{cond_name}' failed: variable '{var_name}' expected {cond['expected_value']!r}, got {context.variables[var_name]!r}."
                )
        if "check_fn" in cond and callable(cond["check_fn"]):
            ok = cond["check_fn"](context.variables)
            if not ok:
                raise AssertionError(f"Condition '{cond_name}' predicate returned False.")

    async def execute(
        self, test_case: TestCase, context: IsolatedExecutionContext
    ) -> AdapterExecutionOutput:
        context.register_cleanup(lambda: self.cleanup(context))
        context.check_cancelled()

        wf_spec = dict(test_case.metadata.get("workflow_spec", {}))
        preconditions: List[Dict[str, Any]] = list(wf_spec.get("preconditions") or [])
        steps: List[Dict[str, Any]] = list(
            wf_spec.get("steps")
            or [
                {
                    "name": s.action,
                    "service_id": test_case.target_id,
                    "target": test_case.target_id,
                    "type": "noop",
                }
                for s in test_case.test_steps
            ]
        )
        postconditions: List[Dict[str, Any]] = list(wf_spec.get("postconditions") or [])

        step_results: List[StepExecutionResult] = []
        seq_num = 0

        def _append_skipped_remaining(
            remaining_steps: List[Dict[str, Any]],
            remaining_postconditions: List[Dict[str, Any]],
        ) -> None:
            nonlocal seq_num
            now_iso = utcnow_iso()
            for rem_step in remaining_steps:
                seq_num += 1
                step_results.append(
                    StepExecutionResult(
                        step_number=seq_num,
                        step_name=str(rem_step.get("name", f"Workflow step {seq_num}")),
                        stage="step",
                        status="skipped",
                        started_at=now_iso,
                        ended_at=now_iso,
                        duration_ms=0.0,
                        details={"reason": "Skipped due to earlier failure in workflow."},
                        evidence_refs=[],
                    )
                )
            for rem_post in remaining_postconditions:
                seq_num += 1
                step_results.append(
                    StepExecutionResult(
                        step_number=seq_num,
                        step_name=str(rem_post.get("name", f"Postcondition {seq_num}")),
                        stage="postcondition",
                        status="skipped",
                        started_at=now_iso,
                        ended_at=now_iso,
                        duration_ms=0.0,
                        details={"reason": "Skipped due to earlier failure in workflow."},
                        evidence_refs=[],
                    )
                )

        # 1. Evaluate Preconditions
        for pre in preconditions:
            context.check_cancelled()
            seq_num += 1
            pre_name = str(pre.get("name", f"Precondition {seq_num}"))
            pre_target = str(pre.get("target", test_case.target_id))
            p_start = utcnow_iso()
            t0 = time.perf_counter()
            try:
                if "url" in pre:
                    context.sandbox.validate_url(str(pre["url"]))
                self._evaluate_condition(pre, context)
                p_end = utcnow_iso()
                dur = round((time.perf_counter() - t0) * 1000.0, 3)
                step_results.append(
                    StepExecutionResult(
                        step_number=seq_num,
                        step_name=pre_name,
                        stage="precondition",
                        status="passed",
                        started_at=p_start,
                        ended_at=p_end,
                        duration_ms=dur,
                        details={"precondition": pre_name},
                        evidence_refs=[],
                    )
                )
            except ExecutionSafetyError:
                raise
            except Exception as pre_exc:
                p_end = utcnow_iso()
                dur = round((time.perf_counter() - t0) * 1000.0, 3)
                err_detail = ExecutionErrorDetail(
                    error_type=type(pre_exc).__name__,
                    message=str(pre_exc),
                    failed_step_number=seq_num,
                    failed_stage="precondition",
                    failed_target=pre_target,
                    outcome_uncertain=False,
                )
                step_results.append(
                    StepExecutionResult(
                        step_number=seq_num,
                        step_name=pre_name,
                        stage="precondition",
                        status="failed",
                        started_at=p_start,
                        ended_at=p_end,
                        duration_ms=dur,
                        details={"precondition": pre_name},
                        error=err_detail,
                        evidence_refs=[],
                    )
                )
                _append_skipped_remaining(steps, postconditions)
                return AdapterExecutionOutput(
                    status="failed",
                    step_results=step_results,
                    error_details=err_detail,
                    metadata={
                        "failure_localization": {
                            "failed_stage": "precondition",
                            "failed_step_number": err_detail.failed_step_number,
                            "failed_step_name": pre_name,
                            "failed_target": pre_target,
                            "root_cause_summary": str(pre_exc),
                        }
                    },
                )

        # 2. Execute Multi-Step Journey
        for idx, step_cfg in enumerate(steps):
            context.check_cancelled()
            seq_num += 1
            step_name = str(step_cfg.get("name", f"Step {idx + 1}"))
            step_type = str(step_cfg.get("type", "action")).lower()
            service_id = str(step_cfg.get("service_id", test_case.target_id))
            step_target = str(step_cfg.get("target", service_id))
            destructive = bool(step_cfg.get("destructive", False))

            st_start = utcnow_iso()
            t0 = time.perf_counter()
            try:
                context.sandbox.validate_action(step_name, destructive=destructive)
                if "url" in step_cfg:
                    context.sandbox.validate_url(str(step_cfg["url"]))

                if step_type == "api":
                    sub_tc = test_case.model_copy(deep=True)
                    sub_tc.metadata = {**sub_tc.metadata, "api_spec": step_cfg.get("api_spec", {})}
                    sub_out = await self.api_adapter.execute(sub_tc, context)
                    if sub_out.status != "passed":
                        if sub_out.status == "unknown":
                            raise UncertainOperationError(
                                sub_out.error_details.message
                                if sub_out.error_details
                                else f"Uncertain API outcome in workflow step '{step_name}'."
                            )
                        raise RuntimeError(
                            sub_out.error_details.message
                            if sub_out.error_details
                            else f"API step '{step_name}' failed with status '{sub_out.status}'."
                        )
                elif step_type == "ui":
                    sub_tc = test_case.model_copy(deep=True)
                    sub_tc.metadata = {**sub_tc.metadata, "ui_spec": step_cfg.get("ui_spec", {})}
                    sub_out = await self.ui_adapter.execute(sub_tc, context)
                    if sub_out.status != "passed":
                        raise RuntimeError(
                            sub_out.error_details.message
                            if sub_out.error_details
                            else f"UI step '{step_name}' failed."
                        )
                elif "handler" in step_cfg and callable(step_cfg["handler"]):
                    res = step_cfg["handler"](context.variables)
                    if inspect.isawaitable(res):
                        res = await res
                    if isinstance(res, dict) and step_cfg.get("extract_to"):
                        context.variables[str(step_cfg["extract_to"])] = SecretRedactor.redact(res)
                elif "set_variable" in step_cfg and isinstance(step_cfg["set_variable"], dict):
                    for k, v in step_cfg["set_variable"].items():
                        context.variables[str(k)] = SecretRedactor.redact(v)

                st_end = utcnow_iso()
                dur = round((time.perf_counter() - t0) * 1000.0, 3)
                ev = context.add_evidence(
                    evidence_type="step_trace",
                    uri=f"trace://workflow/{context.execution_id}/step-{seq_num}",
                    summary=f"Workflow step '{step_name}' on '{service_id}' passed ({dur:.2f}ms)",
                    metadata={"step_number": seq_num, "step_name": step_name, "service_id": service_id},
                )
                step_results.append(
                    StepExecutionResult(
                        step_number=seq_num,
                        step_name=step_name,
                        stage="step",
                        status="passed",
                        started_at=st_start,
                        ended_at=st_end,
                        duration_ms=dur,
                        details={"service_id": service_id, "target": step_target, "step_type": step_type},
                        evidence_refs=[ev.evidence_id],
                    )
                )
            except ExecutionSafetyError:
                raise
            except ExecutionCancelledError:
                raise
            except UncertainOperationError as uoe:
                st_end = utcnow_iso()
                dur = round((time.perf_counter() - t0) * 1000.0, 3)
                failed_step_num = seq_num
                err_detail = ExecutionErrorDetail(
                    error_type="UncertainOperationError",
                    message=str(uoe),
                    failed_step_number=failed_step_num,
                    failed_stage="step",
                    failed_target=step_target,
                    outcome_uncertain=True,
                )
                step_results.append(
                    StepExecutionResult(
                        step_number=failed_step_num,
                        step_name=step_name,
                        stage="step",
                        status="unknown",
                        started_at=st_start,
                        ended_at=st_end,
                        duration_ms=dur,
                        details={"service_id": service_id, "target": step_target, "replayed": False},
                        error=err_detail,
                        evidence_refs=[],
                    )
                )
                _append_skipped_remaining(steps[idx + 1 :], postconditions)
                return AdapterExecutionOutput(
                    status="unknown",
                    step_results=step_results,
                    error_details=err_detail,
                    metadata={
                        "outcome_uncertain": True,
                        "automatic_replay": False,
                        "failure_localization": {
                            "failed_stage": "step",
                            "failed_step_number": failed_step_num,
                            "failed_step_name": step_name,
                            "failed_service_id": service_id,
                            "failed_target": step_target,
                            "root_cause_summary": str(uoe),
                        },
                    },
                )
            except Exception as step_exc:
                st_end = utcnow_iso()
                dur = round((time.perf_counter() - t0) * 1000.0, 3)
                failed_step_num = seq_num
                err_detail = ExecutionErrorDetail(
                    error_type=type(step_exc).__name__,
                    message=str(step_exc),
                    failed_step_number=failed_step_num,
                    failed_stage="step",
                    failed_target=step_target,
                    outcome_uncertain=False,
                )
                step_results.append(
                    StepExecutionResult(
                        step_number=failed_step_num,
                        step_name=step_name,
                        stage="step",
                        status="failed",
                        started_at=st_start,
                        ended_at=st_end,
                        duration_ms=dur,
                        details={"service_id": service_id, "target": step_target},
                        error=err_detail,
                        evidence_refs=[],
                    )
                )
                _append_skipped_remaining(steps[idx + 1 :], postconditions)
                return AdapterExecutionOutput(
                    status="failed",
                    step_results=step_results,
                    error_details=err_detail,
                    metadata={
                        "failure_localization": {
                            "failed_stage": "step",
                            "failed_step_number": failed_step_num,
                            "failed_step_name": step_name,
                            "failed_service_id": service_id,
                            "failed_target": step_target,
                            "root_cause_summary": str(step_exc),
                        }
                    },
                )

        # 3. Evaluate Postconditions
        for post_idx, post in enumerate(postconditions):
            context.check_cancelled()
            seq_num += 1
            post_name = str(post.get("name", f"Postcondition {post_idx + 1}"))
            post_target = str(post.get("target", test_case.target_id))
            po_start = utcnow_iso()
            t0 = time.perf_counter()
            try:
                self._evaluate_condition(post, context)
                po_end = utcnow_iso()
                dur = round((time.perf_counter() - t0) * 1000.0, 3)
                step_results.append(
                    StepExecutionResult(
                        step_number=seq_num,
                        step_name=post_name,
                        stage="postcondition",
                        status="passed",
                        started_at=po_start,
                        ended_at=po_end,
                        duration_ms=dur,
                        details={"postcondition": post_name},
                        evidence_refs=[],
                    )
                )
            except Exception as post_exc:
                po_end = utcnow_iso()
                dur = round((time.perf_counter() - t0) * 1000.0, 3)
                failed_step_num = seq_num
                err_detail = ExecutionErrorDetail(
                    error_type=type(post_exc).__name__,
                    message=str(post_exc),
                    failed_step_number=failed_step_num,
                    failed_stage="postcondition",
                    failed_target=post_target,
                    outcome_uncertain=False,
                )
                step_results.append(
                    StepExecutionResult(
                        step_number=failed_step_num,
                        step_name=post_name,
                        stage="postcondition",
                        status="failed",
                        started_at=po_start,
                        ended_at=po_end,
                        duration_ms=dur,
                        details={"postcondition": post_name},
                        error=err_detail,
                        evidence_refs=[],
                    )
                )
                _append_skipped_remaining([], postconditions[post_idx + 1 :])
                return AdapterExecutionOutput(
                    status="failed",
                    step_results=step_results,
                    error_details=err_detail,
                    metadata={
                        "failure_localization": {
                            "failed_stage": "postcondition",
                            "failed_step_number": failed_step_num,
                            "failed_step_name": post_name,
                            "failed_target": post_target,
                            "root_cause_summary": str(post_exc),
                        }
                    },
                )

        return AdapterExecutionOutput(
            status="passed",
            step_results=step_results,
            error_details=None,
            metadata={"completed_steps": len(steps)},
        )
