"""Execution Adapter Registry for CHAOS-INTEL Phase 3B.

Manages test execution adapters (API, UI, Workflow) and deterministically
routes approved test cases to the appropriate execution adapter while enforcing
that no adapter enables live chaos execution or fault injection.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from adapters.api_adapter import ApiTestAdapter
from adapters.base import AdapterMetadata, BaseTestExecutionAdapter
from adapters.ui_adapter import UiTestAdapter
from adapters.workflow_adapter import WorkflowTestAdapter
from schemas import TestCase


class ExecutionAdapterRegistry:
    """Registry of approved functional, API, UI, and workflow execution adapters."""

    def __init__(self, register_defaults: bool = True) -> None:
        self._adapters: Dict[str, BaseTestExecutionAdapter] = {}
        if register_defaults:
            self.register_default_adapters()

    def register_default_adapters(self) -> None:
        """Register the built-in API, UI, and Workflow adapters."""
        api_adapter = ApiTestAdapter()
        ui_adapter = UiTestAdapter()
        workflow_adapter = WorkflowTestAdapter(api_adapter=api_adapter, ui_adapter=ui_adapter)

        self.register(api_adapter, overwrite=True)
        self.register(ui_adapter, overwrite=True)
        self.register(workflow_adapter, overwrite=True)

    def register(self, adapter: BaseTestExecutionAdapter, overwrite: bool = False) -> AdapterMetadata:
        """Register an execution adapter after verifying safety constraints."""
        if not isinstance(adapter, BaseTestExecutionAdapter):
            raise TypeError("Adapter must inherit from BaseTestExecutionAdapter.")

        meta = adapter.metadata()
        if meta.supports_live_chaos:
            raise ValueError(
                f"Safety violation: Adapter '{meta.adapter_id}' declares supports_live_chaos=True, "
                "which is prohibited in Phase 3B."
            )

        if meta.adapter_id in self._adapters and not overwrite:
            raise ValueError(f"Execution adapter '{meta.adapter_id}' is already registered.")

        self._adapters[meta.adapter_id] = adapter
        return meta

    def get_adapter(self, adapter_id: str) -> BaseTestExecutionAdapter:
        """Retrieve a registered adapter by its unique ID."""
        if adapter_id not in self._adapters:
            raise KeyError(f"Execution adapter '{adapter_id}' is not registered.")
        return self._adapters[adapter_id]

    def list_adapters(self) -> List[AdapterMetadata]:
        """Return metadata for all registered adapters in deterministic order."""
        return [
            self._adapters[adapter_id].metadata()
            for adapter_id in sorted(self._adapters.keys())
        ]

    def resolve_for_test_case(self, test_case: TestCase) -> BaseTestExecutionAdapter:
        """Deterministically resolve the execution adapter for a given TestCase."""
        meta = test_case.metadata or {}

        # 1. Explicit adapter_id override in metadata
        explicit_id = meta.get("adapter_id")
        if explicit_id:
            return self.get_adapter(str(explicit_id))

        # 2. Explicit spec keys in metadata
        if "workflow_spec" in meta:
            return self.get_adapter("workflow-adapter-v1")
        if "ui_spec" in meta:
            return self.get_adapter("ui-adapter-v1")
        if "api_spec" in meta:
            return self.get_adapter("api-adapter-v1")

        # 3. Target type / test type routing
        target_type = str(test_case.target_type).lower()
        test_type = str(test_case.test_type).lower()

        if target_type in ("ui", "frontend"):
            return self.get_adapter("ui-adapter-v1")

        if target_type == "workflow" or test_type == "workflow_resilience":
            return self.get_adapter("workflow-adapter-v1")

        if target_type == "api" or test_type == "api_resilience":
            return self.get_adapter("api-adapter-v1")

        # 4. Default deterministic fallback for service/dependency functional tests
        return self.get_adapter("api-adapter-v1")

