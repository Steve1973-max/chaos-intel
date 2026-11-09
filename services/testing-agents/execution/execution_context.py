import asyncio
import inspect
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field


class _InMemorySelector:
    """Socket-free selector for deterministic async test execution in socket-restricted sandboxes."""

    def select(self, timeout: Optional[float] = None) -> List[Any]:
        if timeout is not None and timeout > 0:
            time.sleep(min(float(timeout), 0.01))
        return []

    def get_map(self) -> Dict[Any, Any]:
        return {}

    def close(self) -> None:
        pass


class _SandboxSafeEventLoop(asyncio.BaseEventLoop):
    """Pure in-memory asyncio BaseEventLoop that avoids Windows TCP loopback socketpair()."""

    def __init__(self) -> None:
        super().__init__()
        self._selector = _InMemorySelector()

    def _make_self_pipe(self) -> None:
        pass

    def _close_self_pipe(self) -> None:
        pass

    def _write_to_self(self) -> None:
        pass

    def _process_events(self, event_list: List[Any]) -> None:
        pass


import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)

    class _SandboxSafeEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
        def new_event_loop(self) -> asyncio.AbstractEventLoop:
            return _SandboxSafeEventLoop()

    if sys.platform == "win32" and __import__("os").environ.get("CHAOS_REAL_EVENT_LOOP") != "1":
        # Only use _SandboxSafeEventLoopPolicy when not running a real TCP/Playwright server
        asyncio.set_event_loop_policy(_SandboxSafeEventLoopPolicy())

try:
    from .result_collector import EvidenceType, ExecutionEvidenceReference
    from .sandbox import ExecutionCancelledError, SecretRedactor, TargetSandbox
except ImportError:
    from execution.result_collector import EvidenceType, ExecutionEvidenceReference  # type: ignore[no-redef]
    from execution.sandbox import ExecutionCancelledError, SecretRedactor, TargetSandbox  # type: ignore[no-redef]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CancellationToken:
    """
    Cooperative thread-safe and async-aware cancellation token for test execution.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = False
        self._reason: Optional[str] = None

    def cancel(self, reason: str = "Execution cancelled by caller.") -> None:
        with self._lock:
            self._cancelled = True
            if self._reason is None:
                self._reason = reason

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    @property
    def reason(self) -> Optional[str]:
        with self._lock:
            return self._reason

    def check_cancelled(self) -> None:
        with self._lock:
            if self._cancelled:
                raise ExecutionCancelledError(self._reason or "Execution cancelled.")


class StructuredLogEntry(BaseModel):
    timestamp: str = Field(default_factory=utcnow_iso)
    level: str = "INFO"
    execution_id: str
    test_case_id: str
    correlation_id: str
    event: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class IsolatedExecutionContext:
    """
    Provides an isolated, per-test-case execution environment with:
    - Unique execution_id and correlation_id
    - TargetSandbox enforcement
    - CancellationToken and timeout configuration
    - Redacted structured logging and evidence registration
    - Guaranteed LIFO cleanup execution after test completion or failure
    """

    def __init__(
        self,
        plan_id: str,
        test_case_id: str,
        application_id: str,
        sandbox: TargetSandbox,
        correlation_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        cancellation_token: Optional[CancellationToken] = None,
        initial_variables: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.execution_id: str = execution_id or f"exec-{uuid.uuid4().hex[:12]}"
        self.correlation_id: str = correlation_id or f"corr-{uuid.uuid4().hex[:12]}"
        self.plan_id: str = plan_id
        self.test_case_id: str = test_case_id
        self.application_id: str = application_id
        self.sandbox: TargetSandbox = sandbox
        self.timeout_seconds: float = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(sandbox.policy.default_timeout_seconds)
        )
        self.cancellation_token: CancellationToken = cancellation_token or CancellationToken()

        # Isolated state per test execution
        import copy

        self.variables: Dict[str, Any] = copy.deepcopy(initial_variables or {})
        self.evidence_references: List[ExecutionEvidenceReference] = []
        self.logs: List[StructuredLogEntry] = []
        self._cleanup_callbacks: List[Callable[[], Any]] = []
        self.cleanup_completed: bool = False
        self.cleanup_errors: List[str] = []

    def check_cancelled(self) -> None:
        self.cancellation_token.check_cancelled()

    def register_cleanup(self, callback: Callable[[], Any]) -> None:
        if not callable(callback):
            raise ValueError("Cleanup callback must be callable.")
        self._cleanup_callbacks.append(callback)

    async def run_cleanup(self) -> bool:
        """
        Executes all registered cleanup hooks in LIFO order.
        Never raises: captures any cleanup error so all remaining hooks still run safely.
        """
        all_succeeded = True
        while self._cleanup_callbacks:
            cb = self._cleanup_callbacks.pop()
            try:
                res = cb()
                if inspect.isawaitable(res):
                    await res
            except Exception as exc:
                all_succeeded = False
                err_msg = SecretRedactor.redact_string(f"Cleanup hook failed: {exc}")
                self.cleanup_errors.append(err_msg)
                self.log("ERROR", "cleanup_hook_failed", error=err_msg)
        self.cleanup_completed = all_succeeded
        return all_succeeded

    def add_evidence(
        self,
        evidence_type: EvidenceType,
        uri: str,
        summary: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExecutionEvidenceReference:
        idx = len(self.evidence_references) + 1
        ev_id = f"{self.execution_id}-ev-{idx:02d}"
        ref = ExecutionEvidenceReference(
            evidence_id=ev_id,
            type=evidence_type,
            uri=uri,
            summary=SecretRedactor.redact_string(summary),
            redacted_metadata=SecretRedactor.redact(metadata or {}),
        )
        self.evidence_references.append(ref)
        return ref

    def log(self, level: str, event: str, **metadata: Any) -> StructuredLogEntry:
        entry = StructuredLogEntry(
            level=level.upper(),
            execution_id=self.execution_id,
            test_case_id=self.test_case_id,
            correlation_id=self.correlation_id,
            event=event,
            metadata=SecretRedactor.redact(metadata),
        )
        self.logs.append(entry)
        return entry

