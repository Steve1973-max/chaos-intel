# CHAOS-INTEL — Phase 3C: Controlled Chaos Experiment Engine

A modular chaos engineering engine that designs, validates, schedules, and executes controlled fault-injection experiments against explicitly authorized target environments.

## Core Capabilities

1. **Declarative Fault Catalog (`fault_catalog.py`)**
   - 12 supported fault types:
     - 6 Infrastructure: `cpu_stress`, `memory_pressure`, `disk_io_pressure`, `network_latency`, `packet_loss`, `network_disconnection`
     - 6 Service: `service_unavailability`, `process_termination_simulation`, `dependency_unavailability`, `api_latency`, `http_error_injection`, `connection_failures`
   - Typed parameter ranges, target scope constraints, recovery strategies, and default rollback plans.

2. **Topological Blast-Radius Analysis (`blast_radius.py`)**
   - Direct target scope validation.
   - Reverse call-graph propagation from the architecture graph.
   - Single-Point-of-Failure (SPOF) risk correlation.
   - Policy constant threshold enforcement (`PolicyConstants.BLAST_RADIUS_LIMITS`).

3. **Steady-State Evaluation (`steady_state.py`)**
   - Baseline and continuous telemetry probes (`cpu_percent`, `memory_percent`, `latency_p95_ms`, `error_rate`, `availability_ratio`).
   - Abort condition evaluation (`>`, `>=`, `<`, `<=`, `==`, `!=`).

4. **Experiment Specification Validation (`experiment_validator.py`)**
   - Parameter range and target validation.
   - Prevention of production target execution.
   - Integration with Application Intelligence Safety & Policy Engine (`evaluate_experiment_safety`).
   - Shared JSON schema validation (`experiment.schema.json`, `safety-decision.schema.json`).

5. **Durable Lifecycle Integration (`experiment_scheduler.py`, `fault_injector.py`, `rollback_manager.py`)**
   - Reuses existing `LifecycleController` state machine as the single source of truth.
   - All 14 experiment lifecycle steps orchestrated.
   - Hard invariant: `LIVE_EXECUTION_ENABLED = False` (live fault execution is strictly disabled).
   - Zero automatic replay of uncertain external operations.
   - Inconclusive recovery is treated as unresolved, never successful.
   - Independent post-recovery steady-state telemetry gating.

6. **Observability & Evidence (`experiment_observer.py`)**
   - OpenTelemetry-compatible metrics and spans.
   - Structured `EvidenceRef` attachment.
   - Full audit event logging with `AuditLogger`.

