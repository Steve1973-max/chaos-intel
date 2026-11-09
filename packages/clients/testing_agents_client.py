"""Typed client for Testing Agents service."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from .base import BaseServiceClient, ServiceClientError
from .loader import get_testing_agents_classes

TestPlanner, TestExecutionEngine, ExecutionApproval = get_testing_agents_classes()


class TestingAgentsClient(BaseServiceClient):
    """Client for generating test plans and executing test cases."""

    __test__ = False

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: float = 60.0,
        direct_adapter: Optional[Any] = None,
    ) -> None:
        super().__init__(
            service_name="testing-agents",
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            direct_adapter=direct_adapter or TestPlanner,
        )
        self._planner = TestPlanner() if TestPlanner else None
        self._engine = TestExecutionEngine() if TestExecutionEngine else None
        self._plans: Dict[str, Any] = {}
        self._executions: Dict[str, Any] = {}

    async def generate_test_plan(
        self,
        app: Any,
        correlation_id: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Generate structured test plan from application architecture and risk assessment."""
        if not app:
            raise ServiceClientError("Application model required for test planning", self.service_name, correlation_id=correlation_id)

        # In-process direct execution
        if self._planner is not None:
            try:
                plan = self._planner.create_test_plan(app)
                self._plans[plan.plan_id] = plan
                return plan
            except Exception as exc:
                raise ServiceClientError(
                    f"Test plan generation failed: {exc}",
                    self.service_name,
                    correlation_id=correlation_id,
                ) from exc

        # HTTP transport
        payload = {
            "application_id": getattr(app, "application_id", str(app)),
            "options": options or {},
        }
        res = await self._request("POST", "/api/v1/plans/generate", correlation_id=correlation_id, json_payload=payload)
        return res

    async def execute_test_plan(
        self,
        plan: Any,
        app: Any,
        correlation_id: str,
        options: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute approved test plan against application environment."""
        if not plan:
            raise ServiceClientError("Test plan required for execution", self.service_name, correlation_id=correlation_id)

        # In-process direct execution
        if self._engine is not None and ExecutionApproval is not None:
            try:
                plan_id = getattr(plan, "plan_id", "plan-01")
                app_id = getattr(app, "application_id", "app-01")
                approval = ExecutionApproval(
                    approval_id=f"appr-{plan_id[:8]}",
                    approved_by="operator-system",
                    plan_id=plan_id,
                    application_id=app_id,
                )
                report = await self._engine.execute_plan(plan, approval, correlation_id=correlation_id)
                exec_id = getattr(report, "plan_execution_id", getattr(report, "execution_id", "exec-01"))
                self._executions[exec_id] = report
                return report
            except Exception as exc:
                raise ServiceClientError(
                    f"Test plan execution failed: {exc}",
                    self.service_name,
                    correlation_id=correlation_id,
                ) from exc

        # HTTP transport
        payload = {
            "plan_id": getattr(plan, "plan_id", str(plan)),
            "application_id": getattr(app, "application_id", ""),
            "options": options or {},
        }
        res = await self._request("POST", "/api/v1/executions", correlation_id=correlation_id, json_payload=payload)
        return res

    async def get_test_plan(self, plan_id: str, correlation_id: str) -> Optional[Any]:
        """Retrieve test plan by ID."""
        if plan_id in self._plans:
            return self._plans[plan_id]
        if self.base_url:
            return await self._request("GET", f"/api/v1/plans/{plan_id}", correlation_id=correlation_id)
        return None

    async def get_execution_status(self, execution_id: str, correlation_id: str) -> Optional[Any]:
        """Retrieve execution report by ID."""
        if execution_id in self._executions:
            return self._executions[execution_id]
        if self.base_url:
            return await self._request("GET", f"/api/v1/executions/{execution_id}", correlation_id=correlation_id)
        return None
