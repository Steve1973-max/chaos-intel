"""Unit and integration test suite for CHAOS-INTEL Phase 3C: Controlled Chaos Experiment Engine.

Covers:
 1. Fault catalog specifications (12 faults, parameter validation, ranges)
 2. Target validation, scope mismatch, and unknown target rejection
 3. Blast-radius assessment, caller propagation, and SPOF detection
 4. Steady-state probes and threshold breach abort conditions
 5. Target environment & duration guardrail enforcement
 6. Safety approval handling and human approver enforcement
 7. Dry-run execution with zero side-effects and declarative manifests
 8. Mock fault execution with full transition to COMPLETED
 9. Safety threshold breach automatic abort, rollback, and recovery
10. Cooperative cancellation (pre-execution & mid-observation)
11. Rollback failure handling with zero automatic replay
12. Recovery verification independent steady-state gating
13. Uncertain external fault operations handling (zero automatic replay)
14. Live execution hard prohibition
15. Complete audit event logging
16. Batch scheduling with early abort
17. JSON schema compliance against experiment-run.schema.json
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

_CHAOS_ENGINE_ROOT = Path(__file__).resolve().parents[1]
_APP_INTEL_ROOT = Path(__file__).resolve().parents[2] / "application-intelligence"

for p in (_CHAOS_ENGINE_ROOT, _APP_INTEL_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from src.execution.adapters.capabilities import AdapterCapabilities
from src.execution.adapters.context import ExecutionContext
from src.execution.adapters.result import ExecutionResult
from src.execution.recovery import RecoveryResult, RecoveryResultVariant
from src.execution.states import LifecycleState
from src.models.application import ApplicationModel
from src.models.architecture import ArchitectureGraph, GraphEdge, GraphNode
from src.models.experiment import Target
from src.models.risk import RiskFinding
from src.models.service import Service

from adapters.base import ChaosFaultAdapter, DeclarativeSpecTranslator, UncertainFaultOperationError
from adapters.dry_run import ChaosDryRunAdapter, MockFaultAdapter
from adapters.lifecycle_proxy import LifecycleAdapterProxy
from blast_radius import BlastRadiusAnalyzer
from engine_models import (
    LIVE_EXECUTION_ENABLED,
    ApprovalGrant,
    ChaosEngineSettings,
    ExperimentCancellationToken,
    LiveExecutionDisabledError,
)
from experiment_observer import ExperimentObserver
from experiment_registry import ExperimentRegistry
from experiment_scheduler import ExperimentScheduler
from experiment_validator import ExperimentValidator
from fault_catalog import DEFAULT_FAULT_CATALOG, FaultCatalog, FaultCatalogError
from fault_injector import FaultInjector
from rollback_manager import RollbackManager
from steady_state import SteadyStateEvaluator, TriggeredAbortCondition


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def sample_app() -> ApplicationModel:
    """Standard 3-tier microservice application model for chaos testing."""
    return ApplicationModel(
        application_id="app-ecommerce-01",
        name="E-Commerce Backend",
        version="1.2.0",
        services=[
            Service(
                service_id="srv-web",
                application_id="app-ecommerce-01",
                name="web-frontend",
                type="frontend",
                source_path="services/frontend",
            ),
            Service(
                service_id="srv-order",
                application_id="app-ecommerce-01",
                name="order-service",
                type="backend",
                source_path="services/order",
            ),
            Service(
                service_id="srv-db",
                application_id="app-ecommerce-01",
                name="order-database",
                type="database",
                source_path="services/db",
            ),
        ],
        architecture=ArchitectureGraph(
            nodes=[
                GraphNode(node_id="n-web", service_id="srv-web", name="web", node_type="frontend"),
                GraphNode(node_id="n-order", service_id="srv-order", name="order", node_type="service"),
                GraphNode(node_id="n-db", service_id="srv-db", name="database", node_type="database"),
            ],
            edges=[
                GraphEdge(edge_id="e-web-order", source_node_id="n-web", target_node_id="n-order", edge_type="calls"),
                GraphEdge(edge_id="e-order-db", source_node_id="n-order", target_node_id="n-db", edge_type="calls"),
            ],
        ),
        risks=[
            RiskFinding(
                risk_id="risk-spof-db",
                application_id="app-ecommerce-01",
                title="SPOF Database Risk",
                target_id="srv-db",
                target_type="service",
                category="architecture",
                risk_type="spof_database",
                severity="high",
                description="Database has no replica and is a Single Point of Failure.",
            )
        ],
    )


@pytest.fixture
def cpu_stress_spec():
    """Standard valid CPU stress experiment specification."""
    return DEFAULT_FAULT_CATALOG.create_experiment_specification(
        fault_type="cpu_stress",
        target=Target(id="srv-order", name="order-service", type="service"),
        application_id="app-ecommerce-01",
        environment="test",
        parameters={"load_percent": 75, "cores": 2},
        duration_seconds=30,
    )


# -----------------------------------------------------------------------------
# 1. Fault Catalog Tests
# -----------------------------------------------------------------------------

def test_fault_catalog_declarations_and_spec_creation():
    catalog = FaultCatalog()
    definitions = catalog.list_definitions()
    assert len(definitions) == 12

    infra_types = {d.fault_type for d in definitions if d.category == "infrastructure"}
    service_types = {d.fault_type for d in definitions if d.category == "service"}

    assert infra_types == {
        "cpu_stress",
        "memory_pressure",
        "disk_io_pressure",
        "network_latency",
        "packet_loss",
        "network_disconnection",
    }
    assert service_types == {
        "service_unavailability",
        "process_termination_simulation",
        "dependency_unavailability",
        "api_latency",
        "http_error_injection",
        "connection_failures",
    }

    # Parameter validation: valid cpu_percent
    params, errs = catalog.validate_parameters("cpu_stress", {"cpu_percent": 80, "cores": 4})
    assert len(errs) == 0
    assert params["cpu_percent"] == 80
    assert params["cores"] == 4

    # Parameter validation: out-of-bounds cpu_percent rejected with error
    _, errs_high = catalog.validate_parameters("cpu_stress", {"cpu_percent": 150})
    assert len(errs_high) > 0

    # Parameter validation: negative/below min value rejected with error
    _, errs_neg = catalog.validate_parameters("cpu_stress", {"cpu_percent": 5})
    assert len(errs_neg) > 0

    # Unknown fault rejected
    with pytest.raises(FaultCatalogError):
        catalog.resolve("non_existent_fault")


# -----------------------------------------------------------------------------
# 2. Blast Radius Analyzer Tests
# -----------------------------------------------------------------------------

def test_blast_radius_analysis_and_spof_detection(sample_app, cpu_stress_spec):
    analyzer = BlastRadiusAnalyzer()
    assessment = analyzer.assess(cpu_stress_spec, sample_app)

    assert assessment.within_limits is True
    assert assessment.directly_affected_components == ["srv-order"]
    # Reverse call graph traversal: srv-web calls srv-order
    assert "srv-web" in assessment.transitively_impacted_callers
    assert assessment.hits_single_point_of_failure is False

    # Target the database, which has a SPOF risk finding
    db_spec = DEFAULT_FAULT_CATALOG.create_experiment_specification(
        fault_type="service_unavailability",
        target=Target(id="srv-db", name="order-database", type="service"),
        application_id="app-ecommerce-01",
        environment="test",
        duration_seconds=30,
    )
    db_assessment = analyzer.assess(db_spec, sample_app)
    assert db_assessment.hits_single_point_of_failure is True
    assert "srv-order" in db_assessment.transitively_impacted_callers
    assert "srv-web" in db_assessment.transitively_impacted_callers


def test_blast_radius_limit_exceeded(sample_app):
    # max_affected_components exceeding policy limit for multiple_services scope (policy limit = 2)
    spec = DEFAULT_FAULT_CATALOG.create_experiment_specification(
        fault_type="cpu_stress",
        target=Target(id="srv-order", name="order-service", type="service"),
        application_id="app-ecommerce-01",
        blast_scope="multiple_services",
        max_affected_components=5,  # exceeds policy limit of 2
    )
    analyzer = BlastRadiusAnalyzer()
    res = analyzer.assess(spec, sample_app)
    assert res.within_limits is False
    assert any("exceeds policy limit" in v for v in res.violations)


# -----------------------------------------------------------------------------
# 3. Steady State and Abort Conditions
# -----------------------------------------------------------------------------

def test_steady_state_and_abort_condition_evaluation(cpu_stress_spec):
    evaluator = SteadyStateEvaluator()

    # Normal healthy metrics: no abort condition triggered
    healthy_metrics = {"error_rate": 0.01, "latency_p95_ms": 120.0, "availability_ratio": 0.999}
    triggered = evaluator.evaluate_abort_conditions(cpu_stress_spec.abort_conditions, healthy_metrics)
    assert len(triggered) == 0

    # Degraded metrics: error_rate breaches threshold (0.50 > 0.25)
    unhealthy_metrics = {"error_rate": 0.50, "latency_p95_ms": 5000.0, "availability_ratio": 0.60}
    triggered = evaluator.evaluate_abort_conditions(cpu_stress_spec.abort_conditions, unhealthy_metrics)
    assert len(triggered) > 0
    assert any(t.metric == "error_rate" for t in triggered)


# -----------------------------------------------------------------------------
# 4. Specification Validation Tests
# -----------------------------------------------------------------------------

def test_experiment_validator_target_not_found(sample_app, cpu_stress_spec):
    validator = ExperimentValidator()

    # Target exists
    report = validator.validate(cpu_stress_spec, sample_app)
    assert report.valid is True

    # Target does not exist in ApplicationModel
    invalid_spec = cpu_stress_spec.model_copy(deep=True)
    invalid_spec.target.id = "srv-ghost"
    invalid_spec.target.name = "ghost-service"
    report_invalid = validator.validate(invalid_spec, sample_app)
    assert report_invalid.valid is False
    assert any("srv-ghost" in err for err in report_invalid.errors)


def test_experiment_validator_production_environment_rejected(sample_app, cpu_stress_spec):
    validator = ExperimentValidator()

    prod_spec = cpu_stress_spec.model_copy(deep=True)
    prod_spec.safety.environment_required = "production"
    prod_report = validator.validate(prod_spec, sample_app)
    assert prod_report.valid is False
    assert any("production" in err.lower() for err in prod_report.errors)


def test_experiment_validator_duration_exceeded(sample_app, cpu_stress_spec):
    validator = ExperimentValidator()

    long_spec = cpu_stress_spec.model_copy(deep=True)
    long_spec.duration_seconds = 1000  # catalog max is 300
    report = validator.validate(long_spec, sample_app)
    assert report.valid is False
    assert any("duration" in err.lower() for err in report.errors)


# -----------------------------------------------------------------------------
# 5. Target Authorization and Guardrail Tests
# -----------------------------------------------------------------------------

def test_target_authorization_unauthorized_environment(sample_app, cpu_stress_spec):
    scheduler = ExperimentScheduler(
        settings=ChaosEngineSettings(authorized_environments={"development", "staging"})
    )
    # spec has environment="test" which is not in authorized_environments
    report = scheduler.run_experiment(spec=cpu_stress_spec, app=sample_app)
    assert report.verdict == "rejected"
    assert any("not authorized" in err for err in report.errors)


def test_target_authorization_production_rejected():
    with pytest.raises(ValueError):
        ChaosEngineSettings(authorized_environments={"production", "test"})


# -----------------------------------------------------------------------------
# 6. Safety Approval Enforcement Tests
# -----------------------------------------------------------------------------

def test_missing_approval_grant_rejects_execution(sample_app, cpu_stress_spec):
    scheduler = ExperimentScheduler()
    # No ApprovalGrant provided
    report = scheduler.run_experiment(spec=cpu_stress_spec, app=sample_app, approval_grant=None)
    assert report.verdict == "rejected"
    assert any("approval" in err.lower() for err in report.errors)


def test_non_human_approver_rejected(cpu_stress_spec):
    with pytest.raises(ValueError):
        ApprovalGrant(experiment_id=cpu_stress_spec.experiment_id, approver="ai")

    with pytest.raises(ValueError):
        ApprovalGrant(experiment_id=cpu_stress_spec.experiment_id, approver="chaos-engine")


def test_unapproved_grant_rejected(sample_app, cpu_stress_spec):
    scheduler = ExperimentScheduler()
    grant = ApprovalGrant(
        experiment_id=cpu_stress_spec.experiment_id,
        approver="bob-engineer",
        approved=False,
    )
    report = scheduler.run_experiment(spec=cpu_stress_spec, app=sample_app, approval_grant=grant)
    assert report.verdict == "rejected"


# -----------------------------------------------------------------------------
# 7. Dry-Run Execution Tests
# -----------------------------------------------------------------------------

def test_dry_run_execution_generates_manifests_and_unresolved_verdict(sample_app, cpu_stress_spec):
    scheduler = ExperimentScheduler()
    grant = ApprovalGrant(experiment_id=cpu_stress_spec.experiment_id, approver="alice-sre")

    report = scheduler.run_experiment(spec=cpu_stress_spec, app=sample_app, approval_grant=grant)

    # Dry-run recovery is inconclusive by definition -> unresolved verdict, stays in RECOVERY_CHECK
    assert report.verdict == "unresolved"
    assert report.final_lifecycle_state == "RECOVERY_CHECK"
    assert report.outcome_uncertain is True
    assert report.automatic_replay_attempted is False

    # Declarative manifests generated for all 4 engines
    assert set(report.declarative_manifests.keys()) == {"pumba", "tc_netem", "chaos_mesh", "litmus_chaos"}
    assert report.declarative_manifests["pumba"]["engine_family"] == "pumba"
    assert report.declarative_manifests["chaos_mesh"]["engine_family"] == "chaos_mesh"

    # Strict JSON Schema compliance
    assert report.run_schema_errors == []

    # Invocations
    assert report.adapter_invocations["prepare"] == 1
    assert report.adapter_invocations["execute"] == 1
    assert report.adapter_invocations["observe"] == 1
    assert report.adapter_invocations["rollback"] == 1
    assert report.adapter_invocations["verify_recovery"] == 1


# -----------------------------------------------------------------------------
# 8. Mock Fault Execution Tests (Successful Flow)
# -----------------------------------------------------------------------------

def test_mock_fault_execution_passes_cleanly(sample_app, cpu_stress_spec):
    scheduler = ExperimentScheduler()
    grant = ApprovalGrant(experiment_id=cpu_stress_spec.experiment_id, approver="alice-sre")
    mock_adapter = MockFaultAdapter()

    report = scheduler.run_experiment(
        spec=cpu_stress_spec,
        app=sample_app,
        adapter=mock_adapter,
        approval_grant=grant,
    )

    assert report.verdict == "passed"
    assert report.hypothesis_held is True
    assert report.final_lifecycle_state == "COMPLETED"
    assert report.outcome_uncertain is False
    assert report.automatic_replay_attempted is False
    assert report.run_schema_errors == []


# -----------------------------------------------------------------------------
# 9. Safety Threshold Breach & Automatic Abort Tests
# -----------------------------------------------------------------------------

def test_safety_threshold_breach_triggers_emergency_abort_and_rollback(sample_app, cpu_stress_spec):
    scheduler = ExperimentScheduler()
    grant = ApprovalGrant(experiment_id=cpu_stress_spec.experiment_id, approver="alice-sre")
    mock_adapter = MockFaultAdapter()

    # Observation metric breaches error_rate threshold (0.45 > 0.05)
    breaching_window = [{"error_rate": 0.45, "latency_p95_ms": 3000.0, "availability_ratio": 0.70}]

    report = scheduler.run_experiment(
        spec=cpu_stress_spec,
        app=sample_app,
        adapter=mock_adapter,
        approval_grant=grant,
        observation_metrics=breaching_window,
    )

    assert report.verdict == "aborted"
    assert report.hypothesis_held is False
    assert report.final_lifecycle_state == "ABORTED"
    assert report.abort.triggered is True
    assert report.abort.source == "safety_threshold"
    assert len(report.abort.triggered_conditions) > 0
    # Rollback must still have executed cleanly
    assert report.adapter_invocations["rollback"] == 1
    assert report.adapter_invocations["verify_recovery"] == 1


# -----------------------------------------------------------------------------
# 10. Cooperative Cancellation Tests
# -----------------------------------------------------------------------------

def test_cancellation_preflight(sample_app, cpu_stress_spec):
    scheduler = ExperimentScheduler()
    grant = ApprovalGrant(experiment_id=cpu_stress_spec.experiment_id, approver="alice-sre")
    token = ExperimentCancellationToken()
    token.cancel(reason="Emergency stop by SRE.")

    report = scheduler.run_experiment(
        spec=cpu_stress_spec,
        app=sample_app,
        approval_grant=grant,
        cancellation_token=token,
    )

    assert report.verdict == "cancelled"
    assert report.final_lifecycle_state == "FAILED"
    assert report.adapter_invocations.get("execute", 0) == 0


class CancellingAdapter(MockFaultAdapter):
    def __init__(self, token: ExperimentCancellationToken) -> None:
        super().__init__()
        self.token = token

    def observe(self, context: ExecutionContext) -> ExecutionResult:
        self.token.cancel(reason="Operator cancelled mid-run.")
        return super().observe(context)


def test_cancellation_during_observation(sample_app, cpu_stress_spec):
    scheduler = ExperimentScheduler()
    grant = ApprovalGrant(experiment_id=cpu_stress_spec.experiment_id, approver="alice-sre")
    token = ExperimentCancellationToken()
    mock_adapter = CancellingAdapter(token)

    report = scheduler.run_experiment(
        spec=cpu_stress_spec,
        app=sample_app,
        adapter=mock_adapter,
        approval_grant=grant,
        cancellation_token=token,
    )

    assert report.verdict == "cancelled"
    assert report.abort.triggered is True
    assert report.abort.source == "cancellation"
    assert report.adapter_invocations["rollback"] == 1


# -----------------------------------------------------------------------------
# 11. Rollback Failure & Zero Replay Tests
# -----------------------------------------------------------------------------

def test_rollback_failure_transitions_to_rollback_failed_without_replay(sample_app, cpu_stress_spec):
    scheduler = ExperimentScheduler()
    grant = ApprovalGrant(experiment_id=cpu_stress_spec.experiment_id, approver="alice-sre")
    failing_adapter = MockFaultAdapter(fail_on_rollback=RuntimeError("Rollback network timeout"))

    report = scheduler.run_experiment(
        spec=cpu_stress_spec,
        app=sample_app,
        adapter=failing_adapter,
        approval_grant=grant,
    )

    assert report.verdict == "failed"
    assert report.final_lifecycle_state == "ROLLBACK_FAILED"
    # Must attempt rollback exactly once (NO automatic replay)
    assert report.adapter_invocations["rollback"] == 1
    assert report.automatic_replay_attempted is False
    assert report.outcome_uncertain is True


# -----------------------------------------------------------------------------
# 12. Recovery Verification Gating Tests
# -----------------------------------------------------------------------------

def test_recovery_verification_downgraded_when_steady_state_unhealthy(sample_app, cpu_stress_spec):
    scheduler = ExperimentScheduler()
    grant = ApprovalGrant(experiment_id=cpu_stress_spec.experiment_id, approver="alice-sre")
    mock_adapter = MockFaultAdapter()

    # Post-recovery metrics indicate system did not actually heal (error rate = 0.35)
    unhealthy_post_recovery = {"error_rate": 0.35, "latency_p95_ms": 2500.0, "availability_ratio": 0.85}

    report = scheduler.run_experiment(
        spec=cpu_stress_spec,
        app=sample_app,
        adapter=mock_adapter,
        approval_grant=grant,
        post_recovery_metrics=unhealthy_post_recovery,
    )

    # Independent gating downgrades adapter-reported success to FAILED
    assert report.verdict == "failed"
    assert report.final_lifecycle_state == "FAILED"
    assert report.hypothesis_held is False


# -----------------------------------------------------------------------------
# 13. Uncertain External Operations Tests
# -----------------------------------------------------------------------------

def test_uncertain_fault_operation_aborts_without_replay(sample_app, cpu_stress_spec):
    scheduler = ExperimentScheduler()
    grant = ApprovalGrant(experiment_id=cpu_stress_spec.experiment_id, approver="alice-sre")
    uncertain_adapter = MockFaultAdapter(
        fail_on_execute=UncertainFaultOperationError("Injected fault state unknown due to gateway timeout")
    )

    report = scheduler.run_experiment(
        spec=cpu_stress_spec,
        app=sample_app,
        adapter=uncertain_adapter,
        approval_grant=grant,
    )

    assert report.verdict == "aborted"
    assert report.outcome_uncertain is True
    assert report.automatic_replay_attempted is False
    # Execute was called exactly once
    assert report.adapter_invocations["execute"] == 1
    # Rollback must still have been attempted once
    assert report.adapter_invocations["rollback"] == 1


# -----------------------------------------------------------------------------
# 14. Live Execution Hard Prohibition Tests
# -----------------------------------------------------------------------------

class LiveCapableAdapter(ChaosFaultAdapter):
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(
            adapter_id="live-pumba-adapter",
            supported_fault_types=["cpu_stress"],
            requires_live_target=True,
            supports_dry_run=False,
        )

    @property
    def supports_live_execution(self) -> bool:
        return True

    def prepare(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(run_id=context.run.run_id, adapter_id="live-pumba", status="success")

    def execute(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(run_id=context.run.run_id, adapter_id="live-pumba", status="success")

    def observe(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(run_id=context.run.run_id, adapter_id="live-pumba", status="success")

    def abort(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(run_id=context.run.run_id, adapter_id="live-pumba", status="success")

    def rollback(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(run_id=context.run.run_id, adapter_id="live-pumba", status="success")

    def verify_recovery(self, context: ExecutionContext) -> RecoveryResult:
        return RecoveryResult(variant=RecoveryResultVariant.CONFIRMED_SUCCESS, run_id=context.run.run_id)

    def cleanup(self, context: ExecutionContext) -> ExecutionResult:
        return ExecutionResult(run_id=context.run.run_id, adapter_id="live-pumba", status="success")

    def build_declarative_manifests(self, spec) -> dict:
        return {}


def test_live_execution_prohibited_in_phase_3c(sample_app, cpu_stress_spec):
    assert LIVE_EXECUTION_ENABLED is False

    scheduler = ExperimentScheduler()
    grant = ApprovalGrant(experiment_id=cpu_stress_spec.experiment_id, approver="alice-sre")
    live_adapter = LiveCapableAdapter()

    # Scheduler guardrail rejects before execution
    report = scheduler.run_experiment(
        spec=cpu_stress_spec,
        app=sample_app,
        adapter=live_adapter,
        approval_grant=grant,
    )
    assert report.verdict == "rejected"
    assert any("strictly disabled" in err for err in report.errors)


# -----------------------------------------------------------------------------
# 15. Audit Completeness Tests
# -----------------------------------------------------------------------------

def test_audit_trail_captures_all_lifecycle_transitions(sample_app, cpu_stress_spec):
    scheduler = ExperimentScheduler()
    grant = ApprovalGrant(experiment_id=cpu_stress_spec.experiment_id, approver="alice-sre")
    mock_adapter = MockFaultAdapter()

    report = scheduler.run_experiment(
        spec=cpu_stress_spec,
        app=sample_app,
        adapter=mock_adapter,
        approval_grant=grant,
    )

    event_types = [ev["event_type"] for ev in report.audit_events]
    assert "preflight_started" in event_types
    assert "approval_granted" in event_types
    assert "authorization_completed" in event_types
    assert "setup_completed" in event_types
    assert "fault_injected" in event_types
    assert "observation_started" in event_types
    assert "rollback_completed" in event_types
    assert "recovery_verified" in event_types


# -----------------------------------------------------------------------------
# 16. Batch Scheduling Tests
# -----------------------------------------------------------------------------

def test_batch_scheduling_with_stop_on_failure(sample_app, cpu_stress_spec):
    scheduler = ExperimentScheduler()
    grant = ApprovalGrant(experiment_id=cpu_stress_spec.experiment_id, approver="alice-sre")

    # Spec 1: valid
    spec1 = cpu_stress_spec

    # Spec 2: invalid environment (triggers rejection)
    spec2 = cpu_stress_spec.model_copy(deep=True)
    spec2.experiment_id = "exp-batch-02"
    spec2.safety.environment_required = "production"

    # Spec 3: valid, but should be skipped due to stop_on_failure=True
    spec3 = cpu_stress_spec.model_copy(deep=True)
    spec3.experiment_id = "exp-batch-03"

    reports = scheduler.schedule_batch(
        experiments=[spec1, spec2, spec3],
        app=sample_app,
        adapter=MockFaultAdapter(),
        approval_grant=grant,
        stop_on_failure=True,
    )

    assert len(reports) == 2
    assert reports[0].verdict == "passed"
    assert reports[1].verdict == "rejected"
