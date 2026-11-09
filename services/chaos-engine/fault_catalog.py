"""Declarative Fault Catalog for CHAOS-INTEL Phase 3C.

Defines the 12 core infrastructure and service fault specifications (plus aliases
for full compatibility with Phase 2 Application Intelligence `PolicyConstants.SUPPORTED_FAULTS`).

Every fault specification defines:
- Fault type and typed parameter specifications (with min/max/enum bounds)
- Target scope (`allowed_target_types`, `allowed_blast_scopes`, `max_affected_components`)
- Duration (`default_duration_seconds`, `max_duration_seconds`)
- Expected impact
- Recovery strategy (`strategy`, `automatic`, `verification_required`, `verification_checks`)
- Required permissions
- Risk classification (`low`, `medium`, `high`, `critical`)
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, Field

_APP_INTEL_ROOT = Path(__file__).resolve().parents[1] / "application-intelligence"
if str(_APP_INTEL_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_INTEL_ROOT))

from src.models.experiment import (
    AbortCondition,
    BlastRadius,
    ExperimentSpecification,
    Fault,
    Rollback,
    Safety,
    SteadyState,
    Target,
)
from src.models.technology import Evidence

FaultCategory = Literal["infrastructure", "service"]
RiskClassification = Literal["low", "medium", "high", "critical"]


class FaultCatalogError(ValueError):
    """Raised when a fault specification violates catalog constraints."""


class FaultParameterSpec(BaseModel):
    """Typed parameter definition for a declarative fault."""

    name: str = Field(min_length=1)
    param_type: Literal["int", "float", "str", "bool"]
    required: bool = True
    default: Optional[Any] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    allowed_values: Optional[List[Any]] = None
    description: str = Field(min_length=1)


class FaultTargetScope(BaseModel):
    """Permitted target types and blast-radius scopes for a fault."""

    allowed_target_types: List[str] = Field(min_length=1)
    allowed_blast_scopes: List[str] = Field(min_length=1)
    max_affected_components: int = Field(ge=1, le=2)


class FaultRecoveryStrategy(BaseModel):
    """Declarative recovery and rollback strategy for a fault."""

    strategy: str = Field(min_length=1)
    automatic: bool = True
    verification_required: bool = True
    verification_checks: List[str] = Field(min_length=1)


class FaultDefinition(BaseModel):
    """Complete declarative definition of an infrastructure or service fault."""

    fault_type: str = Field(min_length=1)
    aliases: List[str] = Field(default_factory=list)
    policy_fault_type: str = Field(min_length=1)
    category: FaultCategory
    title: str = Field(min_length=1)
    default_method: str = Field(min_length=1)
    supported_methods: List[str] = Field(min_length=1)
    parameters: List[FaultParameterSpec] = Field(default_factory=list)
    target_scope: FaultTargetScope
    default_duration_seconds: int = Field(ge=1, le=300)
    max_duration_seconds: int = Field(ge=1, le=300)
    expected_impact: str = Field(min_length=1)
    recovery_strategy: FaultRecoveryStrategy
    required_permissions: List[str] = Field(min_length=1)
    risk_classification: RiskClassification


def _build_default_definitions() -> List[FaultDefinition]:
    return [
        # =====================================================================
        # INFRASTRUCTURE FAULTS (6)
        # =====================================================================
        FaultDefinition(
            fault_type="cpu_stress",
            aliases=["resource_cpu"],
            policy_fault_type="resource_cpu",
            category="infrastructure",
            title="CPU Stress",
            default_method="cpu_burn_workers",
            supported_methods=["cpu_burn_workers", "cgroup_cpu_quota_throttle", "stress_ng_cpu_simulation"],
            parameters=[
                FaultParameterSpec(
                    name="cpu_percent",
                    param_type="int",
                    required=True,
                    default=80,
                    min_value=10,
                    max_value=100,
                    description="Target CPU utilization percentage during fault window.",
                ),
                FaultParameterSpec(
                    name="cores",
                    param_type="int",
                    required=False,
                    default=1,
                    min_value=1,
                    max_value=64,
                    description="Number of vCPU cores targeted.",
                ),
            ],
            target_scope=FaultTargetScope(
                allowed_target_types=["service", "infrastructure"],
                allowed_blast_scopes=["single_service"],
                max_affected_components=1,
            ),
            default_duration_seconds=60,
            max_duration_seconds=180,
            expected_impact="Elevated CPU utilization and compute queue saturation; request latency may increase while service remains reachable.",
            recovery_strategy=FaultRecoveryStrategy(
                strategy="terminate_cpu_stress_workers_and_restore_cgroup_quota",
                automatic=True,
                verification_required=True,
                verification_checks=["cpu_utilization_below_threshold", "service_health_endpoint_ok"],
            ),
            required_permissions=["infrastructure:cpu_stress", "container:resource_control"],
            risk_classification="medium",
        ),
        FaultDefinition(
            fault_type="memory_pressure",
            aliases=["resource_memory"],
            policy_fault_type="resource_memory",
            category="infrastructure",
            title="Memory Pressure",
            default_method="memory_balloon_allocation",
            supported_methods=["memory_balloon_allocation", "cgroup_memory_limit_pressure"],
            parameters=[
                FaultParameterSpec(
                    name="memory_percent",
                    param_type="int",
                    required=True,
                    default=75,
                    min_value=10,
                    max_value=95,
                    description="Target working-set memory pressure percentage (capped at 95% to prevent host OOM).",
                ),
                FaultParameterSpec(
                    name="megabytes",
                    param_type="int",
                    required=False,
                    default=256,
                    min_value=16,
                    max_value=8192,
                    description="Allocated memory buffer size in MiB.",
                ),
            ],
            target_scope=FaultTargetScope(
                allowed_target_types=["service", "infrastructure"],
                allowed_blast_scopes=["single_service"],
                max_affected_components=1,
            ),
            default_duration_seconds=60,
            max_duration_seconds=180,
            expected_impact="Increased GC/page reclamation activity and potential memory allocation backpressure without host kernel panic.",
            recovery_strategy=FaultRecoveryStrategy(
                strategy="release_allocated_memory_pages_and_verify_rss",
                automatic=True,
                verification_required=True,
                verification_checks=["memory_utilization_restored", "no_oom_restarts", "service_health_endpoint_ok"],
            ),
            required_permissions=["infrastructure:memory_pressure", "container:resource_control"],
            risk_classification="high",
        ),
        FaultDefinition(
            fault_type="disk_io_pressure",
            aliases=["io_pressure"],
            policy_fault_type="resource_memory",
            category="infrastructure",
            title="Disk I/O Pressure",
            default_method="blkio_throttle_and_sync_writes",
            supported_methods=["blkio_throttle_and_sync_writes", "io_latency_injection"],
            parameters=[
                FaultParameterSpec(
                    name="io_wait_ms",
                    param_type="int",
                    required=True,
                    default=50,
                    min_value=5,
                    max_value=2000,
                    description="Injected disk read/write latency in milliseconds.",
                ),
                FaultParameterSpec(
                    name="bandwidth_limit_mbps",
                    param_type="int",
                    required=False,
                    default=10,
                    min_value=1,
                    max_value=1000,
                    description="Throttled block I/O throughput in MB/s.",
                ),
            ],
            target_scope=FaultTargetScope(
                allowed_target_types=["service", "infrastructure", "database", "dependency"],
                allowed_blast_scopes=["single_service", "single_dependency"],
                max_affected_components=1,
            ),
            default_duration_seconds=45,
            max_duration_seconds=150,
            expected_impact="Increased disk read/write latency and fsync queuing; persistence operations slow down.",
            recovery_strategy=FaultRecoveryStrategy(
                strategy="remove_blkio_throttle_and_cleanup_temp_io_buffers",
                automatic=True,
                verification_required=True,
                verification_checks=["disk_io_latency_normal", "service_health_endpoint_ok"],
            ),
            required_permissions=["infrastructure:disk_io_control", "container:blkio_control"],
            risk_classification="medium",
        ),
        FaultDefinition(
            fault_type="network_latency",
            aliases=["latency"],
            policy_fault_type="latency",
            category="infrastructure",
            title="Network Latency",
            default_method="tc_netem_delay",
            supported_methods=["tc_netem_delay", "network_delay", "proxy_delay_injection"],
            parameters=[
                FaultParameterSpec(
                    name="latency_ms",
                    param_type="int",
                    required=True,
                    default=200,
                    min_value=1,
                    max_value=10000,
                    description="Added network round-trip delay in milliseconds.",
                ),
                FaultParameterSpec(
                    name="jitter_ms",
                    param_type="int",
                    required=False,
                    default=20,
                    min_value=0,
                    max_value=2000,
                    description="Latency jitter variance in milliseconds.",
                ),
            ],
            target_scope=FaultTargetScope(
                allowed_target_types=["service", "dependency", "external_dependency", "api", "infrastructure"],
                allowed_blast_scopes=["single_service", "single_dependency", "single_api", "single_external_dependency"],
                max_affected_components=1,
            ),
            default_duration_seconds=60,
            max_duration_seconds=300,
            expected_impact="Elevated network RTT across target interface; upstream callers experience slower responses and test timeout configurations.",
            recovery_strategy=FaultRecoveryStrategy(
                strategy="delete_tc_netem_qdisc_rule",
                automatic=True,
                verification_required=True,
                verification_checks=["network_rtt_restored", "error_rate_within_baseline"],
            ),
            required_permissions=["network:netem_delay", "CAP_NET_ADMIN"],
            risk_classification="low",
        ),
        FaultDefinition(
            fault_type="packet_loss",
            aliases=[],
            policy_fault_type="packet_loss",
            category="infrastructure",
            title="Packet Loss",
            default_method="tc_netem_loss",
            supported_methods=["tc_netem_loss", "iptables_statistic_drop"],
            parameters=[
                FaultParameterSpec(
                    name="loss_percent",
                    param_type="float",
                    required=True,
                    default=10.0,
                    min_value=0.1,
                    max_value=100.0,
                    description="Percentage of packets dropped on target network interface.",
                ),
                FaultParameterSpec(
                    name="correlation_percent",
                    param_type="float",
                    required=False,
                    default=0.0,
                    min_value=0.0,
                    max_value=100.0,
                    description="Packet loss correlation percentage.",
                ),
            ],
            target_scope=FaultTargetScope(
                allowed_target_types=["service", "dependency", "external_dependency", "infrastructure"],
                allowed_blast_scopes=["single_service", "single_dependency", "single_external_dependency"],
                max_affected_components=1,
            ),
            default_duration_seconds=45,
            max_duration_seconds=180,
            expected_impact="TCP retransmissions, degraded throughput, and intermittent request timeouts on the affected link.",
            recovery_strategy=FaultRecoveryStrategy(
                strategy="remove_tc_netem_packet_loss_rule",
                automatic=True,
                verification_required=True,
                verification_checks=["packet_loss_zero", "service_latency_restored"],
            ),
            required_permissions=["network:netem_loss", "CAP_NET_ADMIN"],
            risk_classification="medium",
        ),
        FaultDefinition(
            fault_type="network_disconnection",
            aliases=["network_partition"],
            policy_fault_type="network_partition",
            category="infrastructure",
            title="Network Disconnection",
            default_method="iptables_partition_drop",
            supported_methods=["iptables_partition_drop", "network_isolation", "cni_link_disconnect"],
            parameters=[
                FaultParameterSpec(
                    name="direction",
                    param_type="str",
                    required=False,
                    default="both",
                    allowed_values=["ingress", "egress", "both"],
                    description="Traffic direction blocked during disconnection.",
                ),
                FaultParameterSpec(
                    name="peer_id",
                    param_type="str",
                    required=False,
                    default="all",
                    description="Specific peer service/dependency ID to isolate from, or 'all'.",
                ),
            ],
            target_scope=FaultTargetScope(
                allowed_target_types=["service", "dependency", "external_dependency", "infrastructure"],
                allowed_blast_scopes=["single_service", "single_dependency", "single_external_dependency", "multiple_services"],
                max_affected_components=2,
            ),
            default_duration_seconds=30,
            max_duration_seconds=120,
            expected_impact="Complete network partition along targeted link; circuit breakers and fallback paths must activate.",
            recovery_strategy=FaultRecoveryStrategy(
                strategy="flush_isolation_rules_and_restore_network_link",
                automatic=True,
                verification_required=True,
                verification_checks=["network_connectivity_restored", "circuit_breaker_closed", "steady_state_restored"],
            ),
            required_permissions=["network:isolation", "CAP_NET_ADMIN"],
            risk_classification="critical",
        ),
        # =====================================================================
        # SERVICE FAULTS (6)
        # =====================================================================
        FaultDefinition(
            fault_type="service_unavailability",
            aliases=["availability"],
            policy_fault_type="availability",
            category="service",
            title="Service Unavailability",
            default_method="readiness_probe_fail",
            supported_methods=["readiness_probe_fail", "service_stop", "replica_scale_down_simulation"],
            parameters=[
                FaultParameterSpec(
                    name="unavailable_percent",
                    param_type="int",
                    required=False,
                    default=100,
                    min_value=10,
                    max_value=100,
                    description="Percentage of service instances made unavailable.",
                ),
            ],
            target_scope=FaultTargetScope(
                allowed_target_types=["service"],
                allowed_blast_scopes=["single_service", "multiple_services"],
                max_affected_components=2,
            ),
            default_duration_seconds=30,
            max_duration_seconds=120,
            expected_impact="Target service stops accepting traffic; load balancer failover or graceful degradation is exercised.",
            recovery_strategy=FaultRecoveryStrategy(
                strategy="restart_service_and_verify_readiness",
                automatic=True,
                verification_required=True,
                verification_checks=["service_replicas_ready", "health_check_200_ok", "error_rate_within_baseline"],
            ),
            required_permissions=["service:lifecycle_control"],
            risk_classification="critical",
        ),
        FaultDefinition(
            fault_type="process_termination_simulation",
            aliases=["process_kill_simulation"],
            policy_fault_type="availability",
            category="service",
            title="Process Termination Simulation",
            default_method="simulated_sigterm",
            supported_methods=["simulated_sigterm", "simulated_sigkill_restart"],
            parameters=[
                FaultParameterSpec(
                    name="signal",
                    param_type="str",
                    required=True,
                    default="SIGTERM",
                    allowed_values=["SIGTERM", "SIGINT", "SIGKILL"],
                    description="Process termination signal to simulate.",
                ),
                FaultParameterSpec(
                    name="grace_period_seconds",
                    param_type="int",
                    required=False,
                    default=10,
                    min_value=0,
                    max_value=60,
                    description="Graceful drain window before termination.",
                ),
            ],
            target_scope=FaultTargetScope(
                allowed_target_types=["service"],
                allowed_blast_scopes=["single_service"],
                max_affected_components=1,
            ),
            default_duration_seconds=30,
            max_duration_seconds=90,
            expected_impact="Simulates sudden worker/container process termination to verify supervisor restart and in-flight request draining.",
            recovery_strategy=FaultRecoveryStrategy(
                strategy="verify_supervisor_process_restart_and_readiness",
                automatic=True,
                verification_required=True,
                verification_checks=["process_running", "service_health_endpoint_ok"],
            ),
            required_permissions=["service:process_signal_simulation"],
            risk_classification="high",
        ),
        FaultDefinition(
            fault_type="dependency_unavailability",
            aliases=["dependency_unavailable"],
            policy_fault_type="dependency_unavailable",
            category="service",
            title="Dependency Unavailability",
            default_method="blackhole_dependency_endpoint",
            supported_methods=["blackhole_dependency_endpoint", "dependency_reject_connections"],
            parameters=[
                FaultParameterSpec(
                    name="dependency_id",
                    param_type="str",
                    required=False,
                    default="target_dependency",
                    description="Identifier of the downstream dependency to make unavailable.",
                ),
                FaultParameterSpec(
                    name="failure_mode",
                    param_type="str",
                    required=False,
                    default="connection_refused",
                    allowed_values=["connection_refused", "blackhole_timeout", "dns_nxdomain"],
                    description="How the unavailable dependency fails requests.",
                ),
            ],
            target_scope=FaultTargetScope(
                allowed_target_types=["dependency", "external_dependency", "database", "queue", "service"],
                allowed_blast_scopes=["single_dependency", "single_external_dependency", "single_service"],
                max_affected_components=1,
            ),
            default_duration_seconds=45,
            max_duration_seconds=180,
            expected_impact="Downstream dependency becomes unreachable; upstream services must trip circuit breakers or serve cached/fallback data.",
            recovery_strategy=FaultRecoveryStrategy(
                strategy="restore_dependency_routing_and_reset_circuit_breakers",
                automatic=True,
                verification_required=True,
                verification_checks=["dependency_reachable", "upstream_error_rate_recovered"],
            ),
            required_permissions=["dependency:routing_control"],
            risk_classification="high",
        ),
        FaultDefinition(
            fault_type="api_latency",
            aliases=["dependency_slow"],
            policy_fault_type="dependency_slow",
            category="service",
            title="API Latency Injection",
            default_method="http_middleware_delay",
            supported_methods=["http_middleware_delay", "gateway_route_delay"],
            parameters=[
                FaultParameterSpec(
                    name="delay_ms",
                    param_type="int",
                    required=True,
                    default=500,
                    min_value=10,
                    max_value=30000,
                    description="Injected HTTP/API handler latency in milliseconds.",
                ),
                FaultParameterSpec(
                    name="affected_percentage",
                    param_type="int",
                    required=False,
                    default=100,
                    min_value=1,
                    max_value=100,
                    description="Percentage of matching API requests delayed.",
                ),
            ],
            target_scope=FaultTargetScope(
                allowed_target_types=["api", "service", "dependency", "external_dependency"],
                allowed_blast_scopes=["single_api", "single_service", "single_dependency", "single_external_dependency"],
                max_affected_components=1,
            ),
            default_duration_seconds=60,
            max_duration_seconds=240,
            expected_impact="Targeted API route exhibits high response latency; client timeouts and bulkheads are tested.",
            recovery_strategy=FaultRecoveryStrategy(
                strategy="remove_api_latency_interceptor",
                automatic=True,
                verification_required=True,
                verification_checks=["api_p95_latency_within_sla"],
            ),
            required_permissions=["api:fault_injection_filter"],
            risk_classification="low",
        ),
        FaultDefinition(
            fault_type="http_error_injection",
            aliases=["http_abort_injection"],
            policy_fault_type="availability",
            category="service",
            title="HTTP Error Injection",
            default_method="http_status_override",
            supported_methods=["http_status_override", "gateway_fault_response"],
            parameters=[
                FaultParameterSpec(
                    name="status_code",
                    param_type="int",
                    required=True,
                    default=503,
                    min_value=400,
                    max_value=599,
                    description="HTTP 4xx/5xx error status code to inject.",
                ),
                FaultParameterSpec(
                    name="error_rate_percent",
                    param_type="float",
                    required=False,
                    default=50.0,
                    min_value=1.0,
                    max_value=100.0,
                    description="Percentage of requests returning the injected HTTP status code.",
                ),
            ],
            target_scope=FaultTargetScope(
                allowed_target_types=["api", "service", "external_dependency"],
                allowed_blast_scopes=["single_api", "single_service", "single_external_dependency"],
                max_affected_components=1,
            ),
            default_duration_seconds=45,
            max_duration_seconds=180,
            expected_impact="Targeted HTTP endpoints return controlled 4xx/5xx responses; retry backoff and error handling are verified.",
            recovery_strategy=FaultRecoveryStrategy(
                strategy="disable_http_error_injection_filter",
                automatic=True,
                verification_required=True,
                verification_checks=["http_2xx_rate_restored", "error_rate_below_threshold"],
            ),
            required_permissions=["api:fault_injection_filter"],
            risk_classification="medium",
        ),
        FaultDefinition(
            fault_type="connection_failures",
            aliases=["connection_exhaustion", "queue_backlog"],
            policy_fault_type="connection_exhaustion",
            category="service",
            title="Connection Failures & Pool Exhaustion",
            default_method="tcp_reset_and_pool_saturation",
            supported_methods=["tcp_reset_and_pool_saturation", "connection_refused_injection", "message_consumption_delay"],
            parameters=[
                FaultParameterSpec(
                    name="failure_rate_percent",
                    param_type="float",
                    required=True,
                    default=100.0,
                    min_value=1.0,
                    max_value=100.0,
                    description="Percentage of new outbound/inbound connections that fail.",
                ),
                FaultParameterSpec(
                    name="max_concurrent_connections",
                    param_type="int",
                    required=False,
                    default=0,
                    min_value=0,
                    max_value=10000,
                    description="Capped connection pool ceiling during fault.",
                ),
            ],
            target_scope=FaultTargetScope(
                allowed_target_types=["dependency", "service", "database", "queue", "external_dependency"],
                allowed_blast_scopes=["single_dependency", "single_service", "single_external_dependency"],
                max_affected_components=1,
            ),
            default_duration_seconds=45,
            max_duration_seconds=180,
            expected_impact="New TCP/pool connections fail with RST/timeout; connection pool recovery and reconnection logic are tested.",
            recovery_strategy=FaultRecoveryStrategy(
                strategy="restore_connection_pool_limits_and_clear_rst_rules",
                automatic=True,
                verification_required=True,
                verification_checks=["connection_pool_healthy", "zero_connection_errors"],
            ),
            required_permissions=["network:connection_control", "service:pool_control"],
            risk_classification="high",
        ),
    ]


class FaultCatalog:
    """Registry and validator for declarative infrastructure and service faults."""

    def __init__(self) -> None:
        self._definitions: Dict[str, FaultDefinition] = {}
        self._alias_map: Dict[str, str] = {}
        for defn in _build_default_definitions():
            self.register(defn)

    def register(self, definition: FaultDefinition) -> None:
        self._definitions[definition.fault_type] = definition
        self._alias_map[definition.fault_type] = definition.fault_type
        for alias in definition.aliases:
            self._alias_map[alias] = definition.fault_type

    def resolve(self, fault_type: str) -> FaultDefinition:
        if not fault_type or not isinstance(fault_type, str):
            raise FaultCatalogError("Fault type must be a non-empty string.")
        canonical = self._alias_map.get(fault_type.strip().lower())
        if not canonical or canonical not in self._definitions:
            raise FaultCatalogError(f"Unsupported fault type '{fault_type}'.")
        return self._definitions[canonical]

    def list_definitions(self, category: Optional[FaultCategory] = None) -> List[FaultDefinition]:
        defs = [self._definitions[k] for k in sorted(self._definitions.keys())]
        if category is not None:
            defs = [d for d in defs if d.category == category]
        return defs

    def validate_parameters(
        self, fault_type: str, parameters: Optional[Dict[str, Any]]
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Validate and populate default fault parameters against the catalog definition."""
        defn = self.resolve(fault_type)
        params = dict(parameters or {})
        errors: List[str] = []
        normalized: Dict[str, Any] = dict(params)

        for p_spec in defn.parameters:
            val = normalized.get(p_spec.name)
            if val is None:
                if p_spec.default is not None:
                    val = p_spec.default
                    normalized[p_spec.name] = val
                elif p_spec.required:
                    errors.append(f"Missing required parameter '{p_spec.name}' for fault '{defn.fault_type}'.")
                    continue
                else:
                    continue

            # Type validation
            if p_spec.param_type == "int":
                if isinstance(val, bool) or not isinstance(val, int):
                    errors.append(f"Parameter '{p_spec.name}' must be an integer, got {type(val).__name__}.")
                    continue
            elif p_spec.param_type == "float":
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    errors.append(f"Parameter '{p_spec.name}' must be a number, got {type(val).__name__}.")
                    continue
                val = float(val)
                normalized[p_spec.name] = val
            elif p_spec.param_type == "str":
                if not isinstance(val, str) or not val.strip():
                    errors.append(f"Parameter '{p_spec.name}' must be a non-empty string.")
                    continue
            elif p_spec.param_type == "bool":
                if not isinstance(val, bool):
                    errors.append(f"Parameter '{p_spec.name}' must be a boolean.")
                    continue

            # Range validation
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                if p_spec.min_value is not None and val < p_spec.min_value:
                    errors.append(
                        f"Parameter '{p_spec.name}' value {val} is below minimum {p_spec.min_value}."
                    )
                if p_spec.max_value is not None and val > p_spec.max_value:
                    errors.append(
                        f"Parameter '{p_spec.name}' value {val} exceeds maximum {p_spec.max_value}."
                    )

            # Allowed values validation
            if p_spec.allowed_values is not None and val not in p_spec.allowed_values:
                errors.append(
                    f"Parameter '{p_spec.name}' value {val!r} is not in allowed values {p_spec.allowed_values}."
                )

        return normalized, errors

    def create_experiment_specification(
        self,
        *,
        application_id: str,
        target: Target,
        fault_type: str,
        parameters: Optional[Dict[str, Any]] = None,
        duration_seconds: Optional[int] = None,
        environment: str = "staging",
        blast_scope: Optional[str] = None,
        max_affected_components: int = 1,
        candidate_ids: Optional[List[str]] = None,
        experiment_id: Optional[str] = None,
        name: Optional[str] = None,
        hypothesis: Optional[str] = None,
        requires_approval: bool = True,
    ) -> ExperimentSpecification:
        """Build a declarative `ExperimentSpecification` enriched with catalog metadata."""
        defn = self.resolve(fault_type)
        normalized_params, param_errors = self.validate_parameters(fault_type, parameters)
        if param_errors:
            raise FaultCatalogError("; ".join(param_errors))

        dur = int(duration_seconds if duration_seconds is not None else defn.default_duration_seconds)
        scope = blast_scope or defn.target_scope.allowed_blast_scopes[0]

        if not experiment_id:
            digest = hashlib.sha256(
                f"{application_id}:{target.id}:{defn.fault_type}:{dur}".encode("utf-8")
            ).hexdigest()[:10]
            experiment_id = f"exp-{digest}"

        return ExperimentSpecification(
            experiment_id=experiment_id,
            application_id=application_id,
            candidate_ids=candidate_ids or [f"cand-{target.id}"],
            name=name or f"{defn.title} on {target.name}",
            hypothesis=hypothesis
            or f"Injecting {defn.fault_type} on {target.name} ({target.id}) for {dur}s maintains steady state and recovers cleanly.",
            status="draft",
            target=target,
            fault=Fault(
                type=defn.fault_type,
                method=defn.default_method,
                parameters=normalized_params,
                purpose=defn.expected_impact,
            ),
            duration_seconds=dur,
            blast_radius=BlastRadius(
                scope=scope,
                max_affected_components=max_affected_components,
            ),
            steady_state=SteadyState(
                required=True,
                checks=list(defn.recovery_strategy.verification_checks),
            ),
            observations=[
                "cpu_percent",
                "memory_percent",
                "latency_p95_ms",
                "error_rate",
                "availability_ratio",
            ],
            abort_conditions=[
                AbortCondition(
                    metric="error_rate",
                    operator=">",
                    threshold=0.25,
                    action="abort",
                    requires_configuration=False,
                ),
                AbortCondition(
                    metric="availability_ratio",
                    operator="<",
                    threshold=0.80,
                    action="abort",
                    requires_configuration=False,
                ),
            ],
            rollback=Rollback(
                strategy=defn.recovery_strategy.strategy,
                automatic=defn.recovery_strategy.automatic,
                verification_required=defn.recovery_strategy.verification_required,
            ),
            prerequisites=["Target environment is non-production", "Steady-state baseline is healthy"],
            safety=Safety(
                requires_approval=requires_approval,
                environment_required=environment,
                reversible=True,
                rollback_required=True,
                production_allowed=False,
            ),
            confidence=0.85,
            evidence=[
                Evidence(
                    source="fault_catalog",
                    type=defn.category,
                    detail=f"Declarative fault specification '{defn.fault_type}' (risk={defn.risk_classification})",
                )
            ],
            metadata={
                "fault_category": defn.category,
                "canonical_fault_type": defn.fault_type,
                "policy_fault_type": defn.policy_fault_type,
                "expected_impact": defn.expected_impact,
                "required_permissions": list(defn.required_permissions),
                "risk_classification": defn.risk_classification,
                "max_duration_seconds": defn.max_duration_seconds,
            },
        )


DEFAULT_FAULT_CATALOG: FaultCatalog = FaultCatalog()


