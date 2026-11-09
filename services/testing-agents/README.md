# CHAOS-INTEL — Testing Agents Service (`services/testing-agents`)

Intelligent testing and automated test execution subsystem (Phases 3A & 3B) that consumes `ApplicationModel` outputs from `services/application-intelligence/`, generates structured, explainable, evidence-backed `TestPlan`s, and executes explicitly approved functional, API, UI, and workflow tests in isolated sandboxes.

## Phase 3A — Intelligent Testing Agent Foundation
- `agent_registry.py`: `AgentRegistry` and model-agnostic `IntelligenceProvider` protocol (`DeterministicBaselineProvider`).
- `test_planner.py`: `TestPlanner` coordinating candidate resolution, test case generation, prioritization, coverage analysis, and JSON Schema validation (synchronous and asynchronous entrypoints).
- `test_case_generator.py`: `TestCaseGenerator` converting `TestCandidate`s and provider suggestions into structured, deduplicated `TestCase`s.
- `test_prioritizer.py`: `TestPrioritizer` computing explainable `PriorityBreakdown`s from risk score, severity, dependency criticality, and confidence.
- `coverage_analyzer.py`: `CoverageAnalyzer` identifying covered and uncovered services, dependencies, APIs, and multi-hop workflows.
- `evidence_collector.py`: `EvidenceCollector` enforcing source evidence traceability and deterministic deduplication.

## Phase 3B — Automated Test Execution Engine
- `execution/engine.py`: `TestExecutionEngine` executing approved `TestPlan`s and `TestCase`s with bounded concurrency (`asyncio.Semaphore`), configurable timeouts, cooperative cancellation, LIFO cleanup guarantees, and zero automatic replay of uncertain external operations.
- `execution/execution_registry.py`: `ExecutionAdapterRegistry` managing execution adapters and enforcing `supports_live_chaos=False`.
- `execution/execution_context.py`: `IsolatedExecutionContext` and `CancellationToken` providing per-test variable isolation, structured redacted logs, evidence tracking, and fault-isolated LIFO cleanup callbacks.
- `execution/result_collector.py`: `ResultCollector`, `TestExecutionResult`, `StepExecutionResult`, and `PlanExecutionReport` normalizing results, redacting secrets, and validating against `test-run.schema.json`.
- `execution/sandbox.py`: `TargetSandbox`, `SandboxPolicy`, `ExecutionApproval`, and `SecretRedactor` enforcing explicit plan authorization, URL host/scheme allowlists, localhost/private network blocking, cloud metadata endpoint blocking, and destructive action blocking.
- `adapters/`:
  - `base.py`: `BaseTestExecutionAdapter`, `AdapterMetadata`, `AdapterExecutionOutput`, and `UncertainOperationError`.
  - `api_adapter.py`: `ApiTestAdapter` for HTTP methods, status codes, headers/auth (Bearer, ApiKey, Basic), timeouts, latency measurement, and Draft-07 JSON Schema validation.
  - `ui_adapter.py`: `UiTestAdapter` and `SimulatedPlaywrightPage` (`BrowserPageSession`) for page navigation, element visibility/interaction, console error and network failure telemetry, and failure screenshot capture.
  - `workflow_adapter.py`: `WorkflowTestAdapter` for multi-step user journeys, preconditions/postconditions, step-level results, and failure localization.
- `schemas/`: Canonical Draft-07 JSON schemas (`test-case.schema.json`, `coverage-report.schema.json`, `test-plan.schema.json`, `test-run.schema.json`) and `SchemaValidator`.
