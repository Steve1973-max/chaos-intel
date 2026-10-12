from typing import Dict, Any
from datetime import datetime, timezone
import uuid
from .base import ExecutionAdapter
from .capabilities import AdapterCapabilities
from .context import ExecutionContext
from .result import ExecutionResult
from ..recovery import RecoveryResult, RecoveryResultVariant

class DryRunAdapter(ExecutionAdapter):
    @classmethod
    def capabilities(cls) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id="dry-run-adapter",
            adapter_name="Dry Run Adapter",
            supported_fault_types=["availability", "latency", "network_partition", "packet_loss", "connection_exhaustion", "resource_cpu", "resource_memory", "dependency_unavailable", "dependency_slow", "queue_backlog"],
            supported_target_types=["service", "api", "dependency", "external_dependency", "infrastructure", "database", "queue"],
            required_capabilities=[],
            version="1.0.0"
        )
        
    def _make_result(self, context: ExecutionContext, status: str) -> ExecutionResult:
        return ExecutionResult(
            result_id=str(uuid.uuid4()),
            run_id=context.run.run_id,
            plan_id="dry-run-plan",
            adapter_id=self.capabilities().adapter_id,
            status=status,
            mode="dry_run",
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            steps=[],
            metadata={"simulated": True}
        )
        
    def prepare(self, context: ExecutionContext) -> ExecutionResult:
        return self._make_result(context, "prepared")
        
    def execute(self, context: ExecutionContext) -> ExecutionResult:
        return self._make_result(context, "executed")
        
    def observe(self, context: ExecutionContext) -> ExecutionResult:
        return self._make_result(context, "observed")
        
    def abort(self, context: ExecutionContext) -> ExecutionResult:
        return self._make_result(context, "aborted")
        
    def rollback(self, context: ExecutionContext) -> ExecutionResult:
        return self._make_result(context, "rolled_back")
        
    def verify_recovery(self, context: ExecutionContext) -> RecoveryResult:
        # Dry run cannot reconcile remote state, so it always yields INCONCLUSIVE if invoked.
        return RecoveryResult(
            variant=RecoveryResultVariant.INCONCLUSIVE,
            run_id=context.run.run_id,
            message="Dry run adapter cannot perform read-only remote reconciliation"
        )
        
    def cleanup(self, context: ExecutionContext) -> ExecutionResult:
        return self._make_result(context, "completed")
