import asyncio
import time
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable
from pydantic import BaseModel, Field

try:
    from ..execution.execution_context import IsolatedExecutionContext, utcnow_iso
    from ..execution.result_collector import ExecutionErrorDetail, StepExecutionResult
    from ..execution.sandbox import (
        ExecutionCancelledError,
        ExecutionSafetyError,
        SecretRedactor,
    )
    from ..schemas import TestCase
    from .base import (
        AdapterExecutionOutput,
        AdapterMetadata,
        BaseTestExecutionAdapter,
        UncertainOperationError,
    )
except ImportError:
    from execution.execution_context import IsolatedExecutionContext, utcnow_iso  # type: ignore[no-redef]
    from execution.result_collector import ExecutionErrorDetail, StepExecutionResult  # type: ignore[no-redef]
    from execution.sandbox import (  # type: ignore[no-redef]
        ExecutionCancelledError,
        ExecutionSafetyError,
        SecretRedactor,
    )
    from schemas import TestCase  # type: ignore[no-redef]
    from adapters.base import (  # type: ignore[no-redef]
        AdapterExecutionOutput,
        AdapterMetadata,
        BaseTestExecutionAdapter,
        UncertainOperationError,
    )


class NetworkFailureRecord(BaseModel):
    url: str
    method: str = "GET"
    status_code: Optional[int] = None
    failure_text: str = "net::ERR_FAILED"


@runtime_checkable
class BrowserPageSession(Protocol):
    """
    Playwright-compatible async browser page session protocol.
    """

    current_url: str
    is_closed: bool

    async def goto(self, url: str, timeout_ms: float = 5000.0) -> int:
        ...

    async def is_visible(self, selector: str) -> bool:
        ...

    async def click(self, selector: str) -> None:
        ...

    async def fill(self, selector: str, value: str) -> None:
        ...

    async def inner_text(self, selector: str) -> str:
        ...

    def get_console_errors(self) -> List[str]:
        ...

    def get_failed_network_requests(self) -> List[NetworkFailureRecord]:
        ...

    async def screenshot(self, label: str) -> bytes:
        ...

    async def close(self) -> None:
        ...


class SimulatedPlaywrightPage:
    """
    Deterministic Playwright-compatible page implementation for hermetic testing
    and environments where a real browser binary is not launched.
    """

    def __init__(
        self,
        elements: Optional[Dict[str, Dict[str, Any]]] = None,
        console_errors: Optional[List[str]] = None,
        failed_requests: Optional[List[Dict[str, Any]]] = None,
        navigation_status: int = 200,
    ) -> None:
        self.current_url: str = "about:blank"
        self.is_closed: bool = False
        self._navigation_status: int = navigation_status
        self._elements: Dict[str, Dict[str, Any]] = {
            "body": {"visible": True, "text": "Ready"},
            **(elements or {}),
        }
        self._console_errors: List[str] = list(console_errors or [])
        self._failed_requests: List[NetworkFailureRecord] = [
            NetworkFailureRecord(**r) if isinstance(r, dict) else r
            for r in (failed_requests or [])
        ]
        self.screenshots_taken: List[str] = []

    async def goto(self, url: str, timeout_ms: float = 5000.0) -> int:
        await asyncio.sleep(0)
        self.current_url = url
        return self._navigation_status

    async def is_visible(self, selector: str) -> bool:
        await asyncio.sleep(0)
        el = self._elements.get(selector)
        return bool(el and el.get("visible", True))

    async def click(self, selector: str) -> None:
        await asyncio.sleep(0)
        if not await self.is_visible(selector):
            raise RuntimeError(f"Element '{selector}' is not visible or does not exist for click.")
        el = self._elements[selector]
        el["clicked"] = True
        if "on_click_text" in el:
            target_sel = el.get("on_click_target", selector)
            self._elements.setdefault(target_sel, {"visible": True})["text"] = el["on_click_text"]

    async def fill(self, selector: str, value: str) -> None:
        await asyncio.sleep(0)
        if not await self.is_visible(selector):
            raise RuntimeError(f"Input element '{selector}' is not visible or does not exist for fill.")
        self._elements[selector]["value"] = value
        self._elements[selector]["text"] = value

    async def inner_text(self, selector: str) -> str:
        await asyncio.sleep(0)
        if selector not in self._elements:
            raise RuntimeError(f"Element '{selector}' not found on page.")
        return str(self._elements[selector].get("text", ""))

    def get_console_errors(self) -> List[str]:
        return list(self._console_errors)

    def get_failed_network_requests(self) -> List[NetworkFailureRecord]:
        return list(self._failed_requests)

    async def screenshot(self, label: str) -> bytes:
        await asyncio.sleep(0)
        self.screenshots_taken.append(label)
        # Valid minimal PNG header signature + label metadata bytes
        return b"\x89PNG\r\n\x1a\n" + label.encode("utf-8")

    async def close(self) -> None:
        await asyncio.sleep(0)
        self.is_closed = True


class UiTestAdapter(BaseTestExecutionAdapter):
    """
    Playwright-based UI test adapter supporting:
    - Page load and navigation checks (with TargetSandbox URL validation)
    - Element visibility and user interaction (click, fill, assert_text)
    - Browser console error and failed network request detection
    - Automatic screenshot evidence capture on any step or assertion failure
    - Guaranteed browser session cleanup
    """

    def __init__(
        self,
        page_factory: Optional[Callable[[Dict[str, Any]], BrowserPageSession]] = None,
    ) -> None:
        self._page_factory = page_factory or self._default_page_factory

    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(
            adapter_id="ui-adapter-v1",
            adapter_type="ui",
            version="1.0.0",
            supported_target_types=["ui", "frontend", "service"],
            supported_test_types=["availability", "degradation", "workflow_resilience"],
            supports_live_chaos=False,
        )

    @staticmethod
    def _default_page_factory(ui_spec: Dict[str, Any]) -> BrowserPageSession:
        mock_state = ui_spec.get("mock_page_state", {})
        return SimulatedPlaywrightPage(
            elements=mock_state.get("elements") or ui_spec.get("elements"),
            console_errors=(
                mock_state.get("console_errors")
                or ui_spec.get("console_errors")
                or ui_spec.get("simulated_console_errors")
            ),
            failed_requests=(
                mock_state.get("failed_network_requests")
                or ui_spec.get("failed_network_requests")
                or ui_spec.get("simulated_failed_requests")
            ),
            navigation_status=int(
                mock_state.get("navigation_status", ui_spec.get("navigation_status", 200))
            ),
        )

    async def _capture_failure_screenshot(
        self,
        page: BrowserPageSession,
        context: IsolatedExecutionContext,
        step_num: int,
        reason: str,
    ) -> str:
        label = f"{context.execution_id}-step-{step_num}"
        raw_bytes = await page.screenshot(label)
        ev = context.add_evidence(
            evidence_type="screenshot",
            uri=f"artifact://screenshots/{label}.png",
            summary=f"UI failure screenshot at step {step_num}: {reason}",
            metadata={
                "page_url": page.current_url,
                "step_number": step_num,
                "byte_length": len(raw_bytes),
                "reason": SecretRedactor.redact_string(reason),
            },
        )
        return ev.evidence_id

    async def execute(
        self, test_case: TestCase, context: IsolatedExecutionContext
    ) -> AdapterExecutionOutput:
        context.check_cancelled()
        ui_spec = dict(test_case.metadata.get("ui_spec", {}))
        url = str(ui_spec.get("url") or context.variables.get("base_url") or "http://localhost:3000")
        fail_on_console_error = bool(ui_spec.get("fail_on_console_error", True))
        fail_on_network_error = bool(ui_spec.get("fail_on_network_error", True))
        interactions: List[Dict[str, Any]] = list(
            ui_spec.get("interactions")
            or [{"action": "assert_visible", "selector": "body"}]
        )

        # Create isolated page session and immediately register cleanup
        page = self._page_factory(ui_spec)
        context.register_cleanup(page.close)
        context.register_cleanup(lambda: self.cleanup(context))

        step_results: List[StepExecutionResult] = []

        # Step 1: Validate URL and navigate to page
        s1_start = utcnow_iso()
        t_s1 = time.perf_counter()
        try:
            validated_url = context.sandbox.validate_url(url)
            nav_status = await page.goto(validated_url, timeout_ms=context.timeout_seconds * 1000.0)
            if nav_status >= 400:
                raise RuntimeError(f"Page navigation to '{validated_url}' returned HTTP {nav_status}.")
        except ExecutionSafetyError as safety_err:
            s1_end = utcnow_iso()
            dur_s1 = round((time.perf_counter() - t_s1) * 1000.0, 3)
            err_detail = ExecutionErrorDetail(
                error_type=type(safety_err).__name__,
                message=str(safety_err),
                failed_step_number=1,
                failed_stage="precondition",
                failed_target=url,
                outcome_uncertain=False,
            )
            step_results.append(
                StepExecutionResult(
                    step_number=1,
                    step_name=f"Navigate to {url}",
                    stage="precondition",
                    status="failed",
                    started_at=s1_start,
                    ended_at=s1_end,
                    duration_ms=dur_s1,
                    details={"url": url},
                    error=err_detail,
                    evidence_refs=[],
                )
            )
            raise
        except Exception as nav_exc:
            s1_end = utcnow_iso()
            dur_s1 = round((time.perf_counter() - t_s1) * 1000.0, 3)
            shot_id = await self._capture_failure_screenshot(page, context, 1, str(nav_exc))
            err_detail = ExecutionErrorDetail(
                error_type=type(nav_exc).__name__,
                message=str(nav_exc),
                failed_step_number=1,
                failed_stage="step",
                failed_target=url,
                outcome_uncertain=False,
            )
            step_results.append(
                StepExecutionResult(
                    step_number=1,
                    step_name=f"Navigate to {url}",
                    stage="step",
                    status="failed",
                    started_at=s1_start,
                    ended_at=s1_end,
                    duration_ms=dur_s1,
                    details={"url": url},
                    error=err_detail,
                    evidence_refs=[shot_id],
                )
            )
            return AdapterExecutionOutput(
                status="failed",
                step_results=step_results,
                error_details=err_detail,
                metadata={"page_url": page.current_url},
            )

        s1_end = utcnow_iso()
        dur_s1 = round((time.perf_counter() - t_s1) * 1000.0, 3)
        step_results.append(
            StepExecutionResult(
                step_number=1,
                step_name=f"Navigate to {validated_url}",
                stage="step",
                status="passed",
                started_at=s1_start,
                ended_at=s1_end,
                duration_ms=dur_s1,
                latency_ms=dur_s1,
                details={"url": validated_url, "navigation_status": nav_status},
                evidence_refs=[],
            )
        )

        # Step 2..N: Execute UI element checks and interactions
        step_num = 1
        for item in interactions:
            context.check_cancelled()
            step_num += 1
            action = str(item.get("action", "assert_visible")).strip().lower()
            selector = str(item.get("selector", "body"))
            destructive = bool(item.get("destructive", False))
            st_start = utcnow_iso()
            t_st = time.perf_counter()

            try:
                context.sandbox.validate_action(f"ui:{action}:{selector}", destructive=destructive)

                if action == "assert_visible":
                    visible = await page.is_visible(selector)
                    if not visible:
                        raise AssertionError(f"Expected UI element '{selector}' to be visible on '{page.current_url}'.")
                elif action == "click":
                    await page.click(selector)
                elif action == "fill":
                    val = str(item.get("value", ""))
                    await page.fill(selector, val)
                elif action == "assert_text":
                    expected_text = str(item.get("expected_text", ""))
                    actual_text = await page.inner_text(selector)
                    if expected_text not in actual_text:
                        raise AssertionError(
                            f"Expected text '{expected_text}' in '{selector}', found '{actual_text}'."
                        )
                elif action == "goto":
                    sub_url = context.sandbox.validate_url(str(item.get("url", "")))
                    sub_status = await page.goto(sub_url, timeout_ms=context.timeout_seconds * 1000.0)
                    if sub_status >= 400:
                        raise RuntimeError(f"Sub-navigation to '{sub_url}' failed with HTTP {sub_status}.")
                else:
                    raise ValueError(f"Unsupported UI interaction action '{action}'.")

                st_end = utcnow_iso()
                dur_st = round((time.perf_counter() - t_st) * 1000.0, 3)
                step_results.append(
                    StepExecutionResult(
                        step_number=step_num,
                        step_name=f"UI {action} on '{selector}'",
                        stage="step",
                        status="passed",
                        started_at=st_start,
                        ended_at=st_end,
                        duration_ms=dur_st,
                        details=SecretRedactor.redact({"action": action, "selector": selector}),
                        evidence_refs=[],
                    )
                )
            except ExecutionSafetyError:
                raise
            except ExecutionCancelledError:
                raise
            except Exception as ui_exc:
                st_end = utcnow_iso()
                dur_st = round((time.perf_counter() - t_st) * 1000.0, 3)
                shot_id = await self._capture_failure_screenshot(page, context, step_num, str(ui_exc))
                err_detail = ExecutionErrorDetail(
                    error_type=type(ui_exc).__name__,
                    message=str(ui_exc),
                    failed_step_number=step_num,
                    failed_stage="step",
                    failed_target=selector,
                    outcome_uncertain=False,
                )
                step_results.append(
                    StepExecutionResult(
                        step_number=step_num,
                        step_name=f"UI {action} on '{selector}'",
                        stage="step",
                        status="failed",
                        started_at=st_start,
                        ended_at=st_end,
                        duration_ms=dur_st,
                        details=SecretRedactor.redact({"action": action, "selector": selector}),
                        error=err_detail,
                        evidence_refs=[shot_id],
                    )
                )
                return AdapterExecutionOutput(
                    status="failed",
                    step_results=step_results,
                    error_details=err_detail,
                    metadata={"page_url": page.current_url},
                )

        # Final Step: Console errors and failed network request telemetry check
        step_num += 1
        diag_start = utcnow_iso()
        t_diag = time.perf_counter()
        console_errors = page.get_console_errors()
        failed_requests = page.get_failed_network_requests()
        diag_evidence_ids: List[str] = []
        diag_failures: List[str] = []

        if console_errors:
            ev_console = context.add_evidence(
                evidence_type="console_log",
                uri=f"log://browser-console/{context.execution_id}",
                summary=f"Captured {len(console_errors)} browser console error(s)",
                metadata={"console_errors": console_errors},
            )
            diag_evidence_ids.append(ev_console.evidence_id)
            if fail_on_console_error:
                diag_failures.append(f"Browser console errors detected: {console_errors}")

        if failed_requests:
            ev_net = context.add_evidence(
                evidence_type="network_log",
                uri=f"log://browser-network/{context.execution_id}",
                summary=f"Captured {len(failed_requests)} failed network request(s)",
                metadata={"failed_requests": [r.model_dump() for r in failed_requests]},
            )
            diag_evidence_ids.append(ev_net.evidence_id)
            if fail_on_network_error:
                diag_failures.append(
                    f"Failed browser network requests detected: {[r.url for r in failed_requests]}"
                )

        diag_end = utcnow_iso()
        dur_diag = round((time.perf_counter() - t_diag) * 1000.0, 3)

        if diag_failures:
            msg = "; ".join(diag_failures)
            shot_id = await self._capture_failure_screenshot(page, context, step_num, msg)
            diag_evidence_ids.append(shot_id)
            err_detail = ExecutionErrorDetail(
                error_type="UiTelemetryAssertionError",
                message=msg,
                failed_step_number=step_num,
                failed_stage="postcondition",
                failed_target=page.current_url,
                outcome_uncertain=False,
            )
            step_results.append(
                StepExecutionResult(
                    step_number=step_num,
                    step_name="Inspect browser console and network telemetry",
                    stage="postcondition",
                    status="failed",
                    started_at=diag_start,
                    ended_at=diag_end,
                    duration_ms=dur_diag,
                    details={
                        "console_error_count": len(console_errors),
                        "failed_network_request_count": len(failed_requests),
                    },
                    error=err_detail,
                    evidence_refs=diag_evidence_ids,
                )
            )
            return AdapterExecutionOutput(
                status="failed",
                step_results=step_results,
                error_details=err_detail,
                metadata={
                    "page_url": page.current_url,
                    "console_errors": console_errors,
                    "failed_network_requests": [r.model_dump() for r in failed_requests],
                },
            )

        step_results.append(
            StepExecutionResult(
                step_number=step_num,
                step_name="Inspect browser console and network telemetry",
                stage="postcondition",
                status="passed",
                started_at=diag_start,
                ended_at=diag_end,
                duration_ms=dur_diag,
                details={
                    "console_error_count": len(console_errors),
                    "failed_network_request_count": len(failed_requests),
                },
                evidence_refs=diag_evidence_ids,
            )
        )

        return AdapterExecutionOutput(
            status="passed",
            step_results=step_results,
            error_details=None,
            metadata={"page_url": page.current_url},
        )
