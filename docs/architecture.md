# CHAOS-INTEL Architecture Documentation

## Platform Overview
CHAOS-INTEL is an autonomous software resilience and failure intelligence platform that combines:
1. **Application Intelligence (`services/application-intelligence/`)**: AST-driven static analysis, technology fingerprinting, service/API discovery, dependency graph building, risk assessment scoring, and experiment candidate formulation.
2. **Testing Agents (`services/testing-agents/`)**: Autonomous test planners, test case generators, test prioritizers, coverage analyzers, and multi-protocol execution engines (REST API, Playwright browser UI, and multi-step workflows).
3. **Controlled Chaos Engine (`services/chaos-engine/`)**: Declarative 12-fault catalog (CPU stress, memory pressure, disk I/O, network latency, packet loss, network partition, service outage, process termination, dependency outage, API latency, HTTP error injection, connection pool exhaustion), blast-radius calculation, steady-state baseline evaluation, and human safety approval boundaries. **Live chaos execution remains strictly disabled (dry-run only).**
4. **Failure Intelligence (`services/failure-intelligence/`)**: Telemetry ingestion buffers, metric normalization, log parsing, distributed trace span processing, multi-signal anomaly correlation, and ranked root-cause hypotheses strictly enforcing `is_causation_proven = false`.
5. **Distributed Platform & API Gateway (`apps/api/`, `workers/`)**: FastAPI versioned gateway (`/api/v1/`), correlation ID propagation, RBAC role enforcement, async job queue (InMemory and Redis), and distributed orchestrator executing 10-step resilience workflows.
6. **Enterprise Web Dashboard (`apps/web/`)**: React 18, TypeScript, Vite, Tailwind CSS dark theme with 11 operational sections, interactive SVG architecture visualizer, time-series charts, and report exports.

## Core Data Flow Architecture

```
User / Web Dashboard (apps/web)
       │ (REST /api/v1 + RBAC X-API-Key)
       ▼
API Gateway (apps/api)
       │
       ├──► Asynchronous Job Queue (workers/queue.py)
       │        ▼
       │    Background Worker (workers/worker.py)
       │        ▼
       │    Distributed Orchestrator (workers/orchestrator.py)
       │        │
       │        ├─► Step 1-2: Application Intelligence (AST parsing, topology)
       │        ├─► Step 3-4: Testing Agents (Plan & approved test runs)
       │        ├─► Step 5-7: Chaos Engine (Safety check, dry-run simulation)
       │        ├─► Step 8-9: Failure Intelligence (Telemetry & hypothesis ranking)
       │        └─► Step 10: Unified Audit Report Synthesis
       │
       └──► Direct Synchronous Queries (Health, Topology, Telemetry, Reports)
```

## Reliability & State Persistence Invariants
- **No Transaction Overhang**: Database transactions are never held open across external agent calls or async network operations.
- **Idempotency Reservations**: Duplicate requests with identical idempotency keys return existing terminal results without re-execution.
- **Fenced Leases**: Authoritative lease acquisition with monotonically incrementing fencing tokens prevents stale execution owners from committing mutations.
- **Commit Uncertainty**: Operations with indeterminate outcomes are never automatically replayed and are routed to dead-letter queues.
- **Causation Guardrail**: Inferred root causes are strictly marked `is_causation_proven: false` and presented as ranked hypotheses.

