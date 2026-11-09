from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

try:
    from ..execution.execution_context import IsolatedExecutionContext
    from ..execution.result_collector import (
        ExecutionErrorDetail,
        ExecutionStatus,
        StepExecutionResult,
    )
    from ..schemas import SafetyViolationError, TestCase, TestingAgentError
except ImportError:
    from execution.execution_context import IsolatedExecutionContext  # type: ignore[no-redef]
    from execution.result_collector import (  # type: ignore[no-redef]
        ExecutionErrorDetail,
        ExecutionStatus,
        StepExecutionResult,
    )
    from schemas import SafetyViolationError, TestCase, TestingAgentError  # type: ignore[no-redef]


class UncertainOperationError(TestingAgentError):
    """
    Raised when an external request or step was dispatched but the outcome is unknown
    (e.g., connection reset after sending a non-idempotent mutation).
    Uncertain operations must NEVER be automatically replayed.
    """


class AdapterMetadata(BaseModel):
    adapter_id: str = Field(min_length=1)
    adapter_type: Literal["api", "ui", "workflow"]
    version: str = Field(default="1.0.0", min_length=1)
    supported_target_types: List[str] = Field(default_factory=list)
    supported_test_types: List[str] = Field(default_factory=list)
    supports_live_chaos: bool = False

    @field_validator("supports_live_chaos")
    @classmethod
    def _forbid_live_chaos(cls, v: bool) -> bool:
        if v is not False:
            raise SafetyViolationError("Phase 3B test execution adapters must not enable live chaos fault injection.")
        return False


class AdapterExecutionOutput(BaseModel):
    status: ExecutionStatus
    step_results: List[StepExecutionResult] = Field(default_factory=list)
    error_details: Optional[ExecutionErrorDetail] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseTestExecutionAdapter(ABC):
    """
    Abstract base class for modular test execution adapters (API, UI, Workflow).
    """

    @abstractmethod
    def metadata(self) -> AdapterMetadata:
        ...

    @abstractmethod
    async def execute(
        self, test_case: TestCase, context: IsolatedExecutionContext
    ) -> AdapterExecutionOutput:
        ...

    async def cleanup(self, context: IsolatedExecutionContext) -> None:
        """
        Optional adapter-level cleanup hook registered with the IsolatedExecutionContext.
        """
        context.log("INFO", "adapter_cleanup_completed", adapter_id=self.metadata().adapter_id)

