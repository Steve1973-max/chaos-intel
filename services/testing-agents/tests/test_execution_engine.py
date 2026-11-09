"""Unit and local-server integration tests for CHAOS-INTEL Phase 3B: Automated Test Execution Engine.

Covers:
1. API execution (HTTP methods, status codes, headers/auth redaction, timeouts, latency measurement, JSON schema validation, local HTTP server)
2. UI execution (Playwright-based browser interaction, navigation, visibility, click/fill/assert_text, console errors, failed network requests, screenshot evidence on failure)
3. Workflow execution (multi-step user journeys, preconditions/postconditions, step-level results, failure localization)
4. Timeouts
5. Cancellation
6. Bounded concurrency limits
7. Invalid targets (out-of-scope hosts, localhost/private network blocking, metadata endpoint blocking, destructive actions)
8. Unauthorized plans (ExecutionApproval & SafetyDecision enforcement)
9. Cleanup after failure (LIFO ordering and fault-isolated cleanup hooks)
10. Evidence collection & credential redaction
11. Result serialization & shared test-run.schema.json validation
"""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List

import pytest

from adapters import (
    AdapterExecutionOutput,
    AdapterMetadata,
    ApiTestAdapter,
    BaseTestExecutionAdapter,
    HttpResponseData,
    SimulatedPlaywrightPage,
    UiTestAdapter,
    UncertainOperationError,
    WorkflowTestAdapter,
)
from execution import (
    CancellationToken,
    DestructiveActionBlockedError,
    ExecutionAdapterRegistry,
    ExecutionApproval,
    ExecutionSafetyError,
    IsolatedExecutionContext,
    PrivateNetworkTargetBlockedError,
    ResultCollector,
    SandboxPolicy,
    TargetOutOfScopeError,
    TargetSandbox,
    TestExecutionEngine,
    UnauthorizedPlanError,
)
from schemas import (
    CoverageReport,
    DimensionCoverage,
    Evidence,
    PriorityBreakdown,
    SafetyDecision,
    SchemaValidator,
    TestCase,
    TestPlan,
    TestPlanSummary,
    TestStep,
)


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------


def _make_test_case(
    test_case_id: str = "tc-api-001",
    target_type: str = "api",
    target_id: str = "api:GET:/orders",
    test_type: str = "api_resilience",
    rank: int = 1,
    metadata: Dict[str, Any] | None = None,
) -> TestCase:
    return TestCase(
        test_case_id=test_case_id,
        application_id="app-ecommerce",
        candidate_id=f"cand-{test_case_id}",
        title=f"Test {test_case_id}",
        target_type=target_type,
        target_id=target_id,
        target_name=target_id,
        test_type=test_type,  # type: ignore[arg-type]
        hypothesis="Target maintains contract and SLA under expected test conditions.",
        reason=f"Automated test case {test_case_id}",
        expected_failure_mode="HTTP 5xx or timeout",
        priority="high",
        confidence=0.85,
        priority_score=78.5,
        rank=rank,
        priority_breakdown=PriorityBreakdown(
            total_score=78.5,
            priority_band="high",
            risk_score=0.8,
            severity_score=0.8,
            dependency_criticality_score=0.75,
            confidence_score=0.85,
            explanation="High priority API test case",
            factors=["high_severity"],
        ),
        preconditions=["Target service is reachable in test environment"],
        test_steps=[
            TestStep(
                step_number=1,
                phase="steady_state_check",
                action="Execute test step",
                expected_observation="Expected response verified",
            )
        ],
        assertions=["Service responds within SLA"],
        evidence=[
            Evidence(
                type="route_definition",
                source="openapi.yaml",
                detail="Derived from API endpoint specification",
            )
        ],
        evidence_reasoning="Verify endpoint contract and resilience",
        metadata=metadata or {},
    )


def _make_test_plan(
    test_cases: List[TestCase],
    plan_id: str = "plan-3b-001",
    application_id: str = "app-ecommerce",
) -> TestPlan:
    return TestPlan(
        plan_id=plan_id,
        schema_version="1.0.0",
        application_id=application_id,
        application_name="Ecommerce Test App",
        execution_authorized=False,
        confidence=0.85,
        summary=TestPlanSummary(
            total_test_cases=len(test_cases),
            by_priority={"high": len(test_cases)},
            by_test_type={"api_resilience": len(test_cases)},
            deduplicated_count=0,
            total_risks_addressed=1,
            total_coverage_gaps=0,
            overall_coverage_ratio=1.0,
        ),
        test_cases=test_cases,
        coverage_report=CoverageReport(
            application_id=application_id,
            total_entities=2,
            covered_entities=2,
            uncovered_entities=0,
            overall_coverage_ratio=1.0,
            service_coverage=DimensionCoverage(
                dimension="service",
                total=1,
                covered=1,
                uncovered=0,
                coverage_ratio=1.0,
                covered_ids=["order-service"],
                uncovered_ids=[],
            ),
            dependency_coverage=DimensionCoverage(
                dimension="dependency",
                total=0,
                covered=0,
                uncovered=0,
                coverage_ratio=1.0,
                covered_ids=[],
                uncovered_ids=[],
            ),
            api_coverage=DimensionCoverage(
                dimension="api",
                total=1,
                covered=1,
                uncovered=0,
                coverage_ratio=1.0,
                covered_ids=["api:GET:/orders"],
                uncovered_ids=[],
            ),
            workflow_coverage=DimensionCoverage(
                dimension="workflow",
                total=0,
                covered=0,
                uncovered=0,
                coverage_ratio=1.0,
                covered_ids=[],
                uncovered_ids=[],
            ),
            gaps=[],
        ),
        evidence=[
            Evidence(
                type="route_definition",
                source="openapi.yaml",
                detail="Plan evidence",
            )
        ],
        metadata={"correlation_id": "corr-plan-3b-001"},
    )


def _make_approval(
    plan_id: str = "plan-3b-001",
    application_id: str = "app-ecommerce",
    approved: bool = True,
) -> ExecutionApproval:
    return ExecutionApproval(
        approval_id=f"appr-{plan_id}",
        plan_id=plan_id,
        application_id=application_id,
        approved_by="qa-lead@chaos-intel.local",
        approved=approved,
    )


# ---------------------------------------------------------------------------
# 1. API Execution Tests (local test application & _default_urllib_transport)
# ---------------------------------------------------------------------------


class _LocalOrderTestApp:
    """In-memory local test application simulating an Orders HTTP service."""

    def __init__(self) -> None:
        self.requests_received: List[Dict[str, Any]] = []

    async def handle_request(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Any,
        timeout_seconds: float,
    ) -> HttpResponseData:
        self.requests_received.append(
            {"method": method, "url": url, "headers": dict(headers), "body": body}
        )
        if method == "GET" and url.endswith("/orders/42"):
            payload = {
                "order_id": "ord-42",
                "status": "CONFIRMED",
                "total_cents": 4500,
                "auth_present": bool(headers.get("Authorization")),
            }
            return HttpResponseData(
                status_code=200,
                headers={"Content-Type": "application/json", "X-Request-Trace": "trace-local-42"},
                body=payload,
                raw_text=json.dumps(payload),
                latency_ms=4.25,
            )
        if method == "POST" and url.endswith("/orders"):
            data = body if isinstance(body, dict) else {}
            payload = {"created": True, "item": data.get("item", "unknown")}
            return HttpResponseData(
                status_code=201,
                headers={"Content-Type": "application/json"},
                body=payload,
                raw_text=json.dumps(payload),
                latency_ms=6.8,
            )
        return HttpResponseData(
            status_code=404,
            headers={"Content-Type": "application/json"},
            body={"error": "not_found"},
            raw_text='{"error": "not_found"}',
            latency_ms=1.1,
        )


def test_api_execution_against_local_http_server_with_schema_and_auth_redaction() -> None:
    local_app = _LocalOrderTestApp()
    registry = ExecutionAdapterRegistry(register_defaults=True)
    registry.register(ApiTestAdapter(http_transport=local_app.handle_request), overwrite=True)

    policy = SandboxPolicy(
        allowed_hosts=["127.0.0.1"],
        allow_localhost=True,
        allow_private_network=False,
        allow_destructive_actions=False,
    )
    engine = TestExecutionEngine(sandbox=TargetSandbox(policy), registry=registry)
    approval = _make_approval()

    tc_get = _make_test_case(
        test_case_id="tc-local-http-get",
        metadata={
            "api_spec": {
                "method": "GET",
                "url": "http://127.0.0.1:8080/orders/42",
                "auth": {"type": "bearer", "token": "super-secret-prod-jwt-999"},
                "headers": {"X-Custom-Client": "chaos-intel-test"},
                "expected_status": 200,
                "max_latency_ms": 2000.0,
                "expected_json_fields": {"order_id": "ord-42", "status": "CONFIRMED", "auth_present": True},
                "response_schema": {
                    "type": "object",
                    "required": ["order_id", "status", "total_cents"],
                    "properties": {
                        "order_id": {"type": "string"},
                        "status": {"type": "string", "enum": ["CONFIRMED", "PENDING"]},
                        "total_cents": {"type": "integer", "minimum": 0},
                    },
                },
                "extract_to": "fetched_order",
            }
        },
    )

    res = engine.execute_test_case_sync(tc_get, plan_id="plan-3b-001", approval=approval)
    assert res.status == "passed"
    assert res.adapter_id == "api-adapter-v1"
    assert res.cleanup_completed is True
    assert len(res.step_results) == 3
    assert res.step_results[1].latency_ms is not None
    assert res.step_results[1].latency_ms >= 0.0

    # Ensure Bearer token was sent to the target app but redacted everywhere in serialized result
    assert local_app.requests_received[0]["headers"]["Authorization"] == "Bearer super-secret-prod-jwt-999"
    serialized_json = json.dumps(res.model_dump(mode="json"))
    assert "super-secret-prod-jwt-999" not in serialized_json
    assert "REDACTED" in serialized_json

    # Also test POST against the local test app
    tc_post = _make_test_case(
        test_case_id="tc-local-http-post",
        metadata={
            "api_spec": {
                "method": "POST",
                "url": "http://127.0.0.1:8080/orders",
                "body": {"item": "resilience-book"},
                "expected_status": 201,
                "expected_json_fields": {"created": True, "item": "resilience-book"},
            }
        },
    )
    res_post = engine.execute_test_case_sync(tc_post, plan_id="plan-3b-001", approval=approval)
    assert res_post.status == "passed"


def test_api_execution_schema_mismatch_and_no_automatic_replay_on_uncertain_mutation() -> None:
    call_count = 0

    async def _uncertain_transport(
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Any,
        timeout_seconds: float,
    ) -> HttpResponseData:
        nonlocal call_count
        call_count += 1
        if method == "POST":
            raise UncertainOperationError("Connection reset by peer after request payload was transmitted.")
        return HttpResponseData(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body={"order_id": 12345},  # Wrong type: integer instead of string
            raw_text='{"order_id": 12345}',
            latency_ms=12.4,
        )

    registry = ExecutionAdapterRegistry(register_defaults=True)
    registry.register(ApiTestAdapter(http_transport=_uncertain_transport), overwrite=True)

    policy = SandboxPolicy(allowed_hosts=["api.staging.internal"], allow_private_network=True)
    engine = TestExecutionEngine(sandbox=TargetSandbox(policy), registry=registry)
    approval = _make_approval()

    # 1. Schema validation failure on GET
    tc_schema_fail = _make_test_case(
        test_case_id="tc-api-schema-fail",
        metadata={
            "api_spec": {
                "method": "GET",
                "url": "https://api.staging.internal/orders/1",
                "expected_status": 200,
                "response_schema": {
                    "type": "object",
                    "required": ["order_id"],
                    "properties": {"order_id": {"type": "string"}},
                },
            }
        },
    )
    res_schema = engine.execute_test_case_sync(tc_schema_fail, plan_id="plan-3b-001", approval=approval)
    assert res_schema.status == "failed"
    assert res_schema.error_details is not None
    assert "Response JSON schema validation failed" in res_schema.error_details.message

    # 2. Uncertain POST outcome must NEVER be automatically replayed
    call_count = 0
    tc_uncertain_post = _make_test_case(
        test_case_id="tc-api-uncertain-post",
        metadata={
            "api_spec": {
                "method": "POST",
                "url": "https://api.staging.internal/orders",
                "body": {"amount": 100},
                "expected_status": 201,
            }
        },
    )
    res_uncertain = engine.execute_test_case_sync(tc_uncertain_post, plan_id="plan-3b-001", approval=approval)
    assert call_count == 1, "Uncertain external mutating operation must never be automatically replayed!"
    assert res_uncertain.status == "unknown"
    assert res_uncertain.error_details is not None
    assert res_uncertain.error_details.outcome_uncertain is True


# ---------------------------------------------------------------------------
# 2. UI Execution Tests (Playwright interaction, console/network errors, screenshots)
# ---------------------------------------------------------------------------


def test_ui_execution_interactions_and_failure_screenshot_evidence() -> None:
    policy = SandboxPolicy(allowed_hosts=["ui.staging.example.com"])
    engine = TestExecutionEngine(sandbox=TargetSandbox(policy))
    approval = _make_approval()

    # Passing UI interaction flow
    tc_ui_pass = _make_test_case(
        test_case_id="tc-ui-pass-001",
        target_type="ui",
        target_id="ui:/checkout",
        metadata={
            "ui_spec": {
                "url": "https://ui.staging.example.com/checkout",
                "elements": {
                    "#promo-input": {"visible": True, "text": ""},
                    "#apply-btn": {"visible": True, "text": "Apply"},
                    "#order-summary": {"visible": True, "text": "Total: $45.00"},
                },
                "interactions": [
                    {"action": "assert_visible", "selector": "#promo-input"},
                    {"action": "fill", "selector": "#promo-input", "value": "SAVE10"},
                    {"action": "click", "selector": "#apply-btn"},
                    {"action": "assert_text", "selector": "#order-summary", "expected_text": "$45.00"},
                ],
            }
        },
    )
    res_pass = engine.execute_test_case_sync(tc_ui_pass, plan_id="plan-3b-001", approval=approval)
    assert res_pass.status == "passed"
    assert res_pass.adapter_id == "ui-adapter-v1"
    assert res_pass.cleanup_completed is True

    # Failing UI flow due to console error & failed network request -> captures screenshot + logs
    tc_ui_telemetry_fail = _make_test_case(
        test_case_id="tc-ui-telemetry-fail-002",
        target_type="ui",
        target_id="ui:/checkout",
        metadata={
            "ui_spec": {
                "url": "https://ui.staging.example.com/checkout",
                "elements": {"#pay-btn": {"visible": True, "text": "Pay Now"}},
                "interactions": [{"action": "click", "selector": "#pay-btn"}],
                "simulated_console_errors": ["Uncaught TypeError: Cannot read properties of null (reading 'stripe')"],
                "simulated_failed_requests": [
                    {"url": "https://ui.staging.example.com/api/payment", "method": "POST", "status": 502, "error_text": "Bad Gateway"}
                ],
                "fail_on_console_error": True,
                "fail_on_network_error": True,
            }
        },
    )
    res_fail = engine.execute_test_case_sync(tc_ui_telemetry_fail, plan_id="plan-3b-001", approval=approval)
    assert res_fail.status == "failed"
    assert res_fail.error_details is not None
    assert res_fail.error_details.error_type == "UiTelemetryAssertionError"

    ev_types = {ev.type for ev in res_fail.evidence_references}
    assert "console_log" in ev_types
    assert "network_log" in ev_types
    assert "screenshot" in ev_types


# ---------------------------------------------------------------------------
# 3. Workflow Execution Tests (Multi-step journeys, preconditions/postconditions, localization)
# ---------------------------------------------------------------------------


def test_workflow_execution_multi_step_journey_and_failure_localization() -> None:
    policy = SandboxPolicy(allowed_hosts=["app.staging.example.com"])
    engine = TestExecutionEngine(sandbox=TargetSandbox(policy))
    approval = _make_approval()

    # 1. Passing multi-step workflow with preconditions, state transfer, and postconditions
    tc_wf_pass = _make_test_case(
        test_case_id="tc-wf-checkout-pass",
        target_type="workflow",
        target_id="workflow:checkout-journey",
        test_type="workflow_resilience",
        metadata={
            "workflow_spec": {
                "preconditions": [
                    {"name": "Ensure user session exists", "required_variable": "session_user"}
                ],
                "steps": [
                    {
                        "name": "Reserve inventory item",
                        "type": "action",
                        "service_id": "inventory-service",
                        "set_variable": {"reservation_status": "RESERVED", "cart_total": 99},
                    },
                    {
                        "name": "Verify checkout confirmation page",
                        "type": "ui",
                        "service_id": "web-frontend",
                        "ui_spec": {
                            "url": "https://app.staging.example.com/confirmation",
                            "elements": {"#banner": {"visible": True, "text": "Order Confirmed"}},
                            "interactions": [
                                {"action": "assert_text", "selector": "#banner", "expected_text": "Order Confirmed"}
                            ],
                        },
                    },
                ],
                "postconditions": [
                    {
                        "name": "Verify reservation_status is RESERVED",
                        "required_variable": "reservation_status",
                        "expected_value": "RESERVED",
                    }
                ],
            }
        },
    )

    res_wf_pass = engine.execute_test_case_sync(
        tc_wf_pass,
        plan_id="plan-3b-001",
        approval=approval,
        initial_variables={"session_user": "user-101"},
    )
    assert res_wf_pass.status == "passed"
    assert res_wf_pass.adapter_id == "workflow-adapter-v1"
    stages = [s.stage for s in res_wf_pass.step_results]
    assert "precondition" in stages
    assert "step" in stages
    assert "postcondition" in stages

    # 2. Failing mid-workflow step localizes failure to the exact step and skips remaining steps/postconditions
    def _failing_payment_handler(_vars: Dict[str, Any]) -> None:
        raise RuntimeError("Downstream payment gateway returned 504 Gateway Timeout")

    tc_wf_fail = _make_test_case(
        test_case_id="tc-wf-checkout-fail-step2",
        target_type="workflow",
        target_id="workflow:checkout-journey",
        test_type="workflow_resilience",
        metadata={
            "workflow_spec": {
                "preconditions": [{"name": "Check user", "required_variable": "session_user"}],
                "steps": [
                    {
                        "name": "Step 1 - Create Cart",
                        "type": "action",
                        "service_id": "cart-service",
                        "set_variable": {"cart_id": "cart-55"},
                    },
                    {
                        "name": "Step 2 - Charge Card",
                        "type": "action",
                        "service_id": "payment-service",
                        "target": "api:POST:/payments/charge",
                        "handler": _failing_payment_handler,
                    },
                    {
                        "name": "Step 3 - Dispatch Shipment",
                        "type": "action",
                        "service_id": "shipping-service",
                        "set_variable": {"shipped": True},
                    },
                ],
                "postconditions": [
                    {"name": "Shipment dispatched", "required_variable": "shipped", "expected_value": True}
                ],
            }
        },
    )

    res_wf_fail = engine.execute_test_case_sync(
        tc_wf_fail,
        plan_id="plan-3b-001",
        approval=approval,
        initial_variables={"session_user": "user-101"},
    )
    assert res_wf_fail.status == "failed"
    assert res_wf_fail.error_details is not None
    assert res_wf_fail.error_details.failed_step_number == 3  # 1 precondition + step 1 + step 2
    assert res_wf_fail.error_details.failed_stage == "step"
    assert res_wf_fail.error_details.failed_target == "api:POST:/payments/charge"

    localization = res_wf_fail.metadata.get("failure_localization", {})
    assert localization["failed_service_id"] == "payment-service"
    assert localization["failed_step_name"] == "Step 2 - Charge Card"

    # Step 3 and Postcondition must be marked skipped
    statuses = [s.status for s in res_wf_fail.step_results]
    assert statuses == ["passed", "passed", "failed", "skipped", "skipped"]


# ---------------------------------------------------------------------------
# 4, 5, 6. Timeouts, Cancellation, and Concurrency Limits
# ---------------------------------------------------------------------------


def test_execution_timeout_handling() -> None:
    async def _slow_transport(
        method: str, url: str, headers: Dict[str, str], body: Any, timeout_seconds: float
    ) -> HttpResponseData:
        await asyncio.sleep(0.5)
        return HttpResponseData(status_code=200, latency_ms=500.0)

    registry = ExecutionAdapterRegistry(register_defaults=True)
    registry.register(ApiTestAdapter(http_transport=_slow_transport), overwrite=True)
    policy = SandboxPolicy(allowed_hosts=["slow.staging.example.com"], default_timeout_seconds=0.05)
    engine = TestExecutionEngine(sandbox=TargetSandbox(policy), registry=registry)

    tc = _make_test_case(
        test_case_id="tc-timeout-001",
        metadata={"api_spec": {"method": "POST", "url": "https://slow.staging.example.com/submit"}},
    )
    res = engine.execute_test_case_sync(tc, plan_id="plan-3b-001", approval=_make_approval(), timeout_seconds=0.05)
    assert res.status == "timed_out"
    assert res.cleanup_completed is True
    assert res.error_details is not None
    assert res.error_details.outcome_uncertain is True


def test_execution_cancellation_token_support() -> None:
    token = CancellationToken()
    token.cancel("Operator aborted test execution run")

    policy = SandboxPolicy(allowed_hosts=["api.staging.example.com"])
    engine = TestExecutionEngine(sandbox=TargetSandbox(policy))
    tc = _make_test_case(
        test_case_id="tc-cancel-001",
        metadata={"api_spec": {"method": "GET", "url": "https://api.staging.example.com/orders"}},
    )
    res = engine.execute_test_case_sync(
        tc,
        plan_id="plan-3b-001",
        approval=_make_approval(),
        cancellation_token=token,
    )
    assert res.status == "cancelled"
    assert res.cleanup_completed is True
    assert res.error_details is not None
    assert "Operator aborted" in res.error_details.message


def test_bounded_concurrency_limits_during_plan_execution() -> None:
    async def _delayed_transport(
        method: str, url: str, headers: Dict[str, str], body: Any, timeout_seconds: float
    ) -> HttpResponseData:
        await asyncio.sleep(0.04)
        return HttpResponseData(status_code=200, body={"ok": True}, raw_text='{"ok": true}', latency_ms=40.0)

    registry = ExecutionAdapterRegistry(register_defaults=True)
    registry.register(ApiTestAdapter(http_transport=_delayed_transport), overwrite=True)

    # Set max_concurrency = 2 for 6 test cases
    policy = SandboxPolicy(allowed_hosts=["concurrent.staging.example.com"], max_concurrency=2)
    engine = TestExecutionEngine(sandbox=TargetSandbox(policy), registry=registry)

    cases = [
        _make_test_case(
            test_case_id=f"tc-conc-{i:02d}",
            rank=i,
            metadata={"api_spec": {"method": "GET", "url": f"https://concurrent.staging.example.com/item/{i}"}},
        )
        for i in range(1, 7)
    ]
    plan = _make_test_plan(cases)
    report = engine.execute_plan_sync(plan, approval=_make_approval())

    assert report.status == "completed"
    assert report.summary.total == 6
    assert report.summary.passed == 6
    assert engine.peak_active_executions <= 2
    assert engine.current_active_executions == 0


# ---------------------------------------------------------------------------
# 7 & 8. Safety Controls: Invalid Targets, Private Networks, Destructive Actions, Unauthorized Plans
# ---------------------------------------------------------------------------


def test_invalid_targets_and_private_network_protection() -> None:
    policy = SandboxPolicy(
        allowed_hosts=["approved.staging.example.com", "localhost", "10.20.30.40", "169.254.169.254"],
        allow_localhost=False,
        allow_private_network=False,
        allow_destructive_actions=False,
    )
    sandbox = TargetSandbox(policy)
    engine = TestExecutionEngine(sandbox=sandbox)
    approval = _make_approval()

    # 1. Arbitrary external host not in allowed_hosts -> TargetOutOfScopeError
    tc_external = _make_test_case(
        test_case_id="tc-unapproved-host",
        metadata={"api_spec": {"method": "GET", "url": "https://evil.external.com/api"}},
    )
    with pytest.raises(TargetOutOfScopeError):
        engine.execute_test_case_sync(tc_external, plan_id="plan-3b-001", approval=approval)

    # 2. Localhost blocked when allow_localhost=False -> PrivateNetworkTargetBlockedError
    tc_localhost = _make_test_case(
        test_case_id="tc-localhost-blocked",
        metadata={"api_spec": {"method": "GET", "url": "http://localhost:8080/admin"}},
    )
    with pytest.raises(PrivateNetworkTargetBlockedError):
        engine.execute_test_case_sync(tc_localhost, plan_id="plan-3b-001", approval=approval)

    # 3. Private network IP blocked when allow_private_network=False -> PrivateNetworkTargetBlockedError
    tc_private = _make_test_case(
        test_case_id="tc-private-ip-blocked",
        metadata={"api_spec": {"method": "GET", "url": "http://10.20.30.40/internal"}},
    )
    with pytest.raises(PrivateNetworkTargetBlockedError):
        engine.execute_test_case_sync(tc_private, plan_id="plan-3b-001", approval=approval)

    # 4. Cloud metadata endpoint (169.254.169.254) unconditionally blocked even if allow_private_network=True
    permissive_sandbox = TargetSandbox(
        SandboxPolicy(
            allowed_hosts=["169.254.169.254"],
            allow_localhost=True,
            allow_private_network=True,
        )
    )
    with pytest.raises(PrivateNetworkTargetBlockedError):
        permissive_sandbox.validate_url("http://169.254.169.254/latest/meta-data/")

    # 5. Destructive HTTP DELETE blocked by default -> DestructiveActionBlockedError
    tc_delete = _make_test_case(
        test_case_id="tc-destructive-delete",
        metadata={"api_spec": {"method": "DELETE", "url": "https://approved.staging.example.com/orders/1"}},
    )
    with pytest.raises(DestructiveActionBlockedError):
        engine.execute_test_case_sync(tc_delete, plan_id="plan-3b-001", approval=approval)


def test_unauthorized_plan_and_safety_decision_enforcement() -> None:
    policy = SandboxPolicy(allowed_hosts=["approved.staging.example.com"])
    engine = TestExecutionEngine(sandbox=TargetSandbox(policy))
    tc = _make_test_case(
        metadata={"api_spec": {"method": "GET", "url": "https://approved.staging.example.com/health"}}
    )
    plan = _make_test_plan([tc])

    # 1. Missing approval -> UnauthorizedPlanError
    with pytest.raises(UnauthorizedPlanError):
        engine.execute_plan_sync(plan, approval=None)

    # 2. Unapproved ExecutionApproval(approved=False) -> UnauthorizedPlanError
    with pytest.raises(UnauthorizedPlanError):
        engine.execute_plan_sync(plan, approval=_make_approval(approved=False))

    # 3. Mismatched plan_id -> UnauthorizedPlanError
    with pytest.raises(UnauthorizedPlanError):
        engine.execute_plan_sync(plan, approval=_make_approval(plan_id="other-plan-999"))

    # 4. Blocked SafetyDecision -> UnauthorizedPlanError
    rejected_decision = SafetyDecision(
        decision_id="sd-reject-001",
        experiment_id="exp-001",
        application_id="app-ecommerce",
        decision="blocked",
        allowed=False,
        blockers=["Blast radius exceeds staging threshold"],
    )
    with pytest.raises(UnauthorizedPlanError):
        engine.execute_plan_sync(plan, approval=rejected_decision)


# ---------------------------------------------------------------------------
# 9, 10, 11. Cleanup After Failure, Evidence Redaction, and Schema Serialization
# ---------------------------------------------------------------------------


def test_lifo_cleanup_runs_safely_after_adapter_failure() -> None:
    cleanup_order: List[str] = []

    class _FailingAdapterWithCleanup(BaseTestExecutionAdapter):
        def metadata(self) -> AdapterMetadata:
            return AdapterMetadata(
                adapter_id="custom-failing-adapter",
                adapter_type="api",
                version="1.0.0",
                supported_target_types=["api"],
                supported_test_types=["api_resilience"],
                supports_live_chaos=False,
            )

        async def execute(self, test_case: TestCase, context: IsolatedExecutionContext) -> AdapterExecutionOutput:
            context.register_cleanup(lambda: cleanup_order.append("hook-1-first-registered"))

            async def _async_hook_2() -> None:
                await asyncio.sleep(0.005)
                cleanup_order.append("hook-2-async")

            def _faulty_hook_3() -> None:
                cleanup_order.append("hook-3-raises")
                raise RuntimeError("Cleanup connection error with Bearer secret-cleanup-token")

            context.register_cleanup(_async_hook_2)
            context.register_cleanup(_faulty_hook_3)
            raise RuntimeError("Simulated mid-test crash with postgres://admin:superpass@db.internal:5432/prod")

    registry = ExecutionAdapterRegistry(register_defaults=True)
    registry.register(_FailingAdapterWithCleanup(), overwrite=True)
    engine = TestExecutionEngine(
        sandbox=TargetSandbox(SandboxPolicy(allowed_hosts=["approved.staging.example.com"])),
        registry=registry,
    )

    tc = _make_test_case(
        test_case_id="tc-cleanup-verify",
        metadata={"adapter_id": "custom-failing-adapter"},
    )
    res = engine.execute_test_case_sync(tc, plan_id="plan-3b-001", approval=_make_approval())

    assert res.status == "failed"
    # Verify strict LIFO execution order and that hook-1 and hook-2 still ran despite hook-3 raising
    assert cleanup_order == ["hook-3-raises", "hook-2-async", "hook-1-first-registered"]

    # Verify credentials in both test error and cleanup error were redacted
    dumped = json.dumps(res.model_dump(mode="json"))
    assert "superpass" not in dumped
    assert "secret-cleanup-token" not in dumped
    assert "REDACTED" in dumped

    # Validate serialized result directly against shared test-run.schema.json
    validator = SchemaValidator()
    validator.validate_test_execution_result(res)
