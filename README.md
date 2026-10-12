# CHAOS-INTEL
**Intelligent Autonomous Software Resilience & Failure Discovery Platform**

## Project Purpose
CHAOS-INTEL is designed to automatically ingest unknown applications, analyze their architecture, formulate testing and experimentation strategies, and execute resilience tests to discover failure modes and vulnerabilities.

## Four-Person Ownership
This project is built collaboratively by a four-person team, each owning a specific domain:
1. **Person 1 (AI + Application Intelligence):** Responsible for ingesting applications, scanning source code, detecting technologies, analyzing dependencies, generating architecture graphs, and formulating risk profiles and test/experiment strategies.
2. **Person 2 (Testing & Chaos Engine):** Responsible for executing tests (Playwright, HTTPX, k6) and chaos experiments (Pumba, tc/netem, Chaos Mesh) and managing the experiment lifecycle.
3. **Person 3 (Backend Platform):** Responsible for the core Fastapi backend, PostgreSQL/Redis storage, workers, OpenTelemetry/Prometheus/Loki observability, and managing findings/root cause analysis.
4. **Person 4 (Frontend/UI):** Responsible for the React frontend dashboard, application architecture visualization, test/experiment UI, and reporting.

## Monorepo Structure
The repository is structured as a monorepo to house all four subsystems cleanly:
- `apps/`: User-facing applications (`web` for frontend, `api` for primary gateway/backend).
- `services/`: Domain-specific backend services (e.g., `application-intelligence`, `chaos-engine`).
- `workers/`: Background task processors.
- `packages/`: Shared libraries, including the critical `schemas` for cross-team contracts.
- `infrastructure/`: Deployment and provisioning configurations.
- `tests/`: End-to-end and integration tests crossing boundaries.
- `docs/`: Documentation and contract proposals.
- `research/`: R&D and LLM/Graph experiments.

## Shared Contracts
To prevent isolated and incompatible models, all cross-module communication happens through **shared contracts** defined in `packages/schemas/`.
These JSON schemas serve as the canonical machine-readable source of truth for objects like Applications, Services, Dependencies, and Architecture Graphs.

## Current Implementation Phase
We are currently in **Step 1: Foundation Setup**.
- Establishing the Git repository and folder structure.
- Defining the foundational shared schemas (`APPLICATION`, `SERVICE`, `DEPENDENCY`, `ARCHITECTURE`).
- Scaffolding the Person 1 (`application-intelligence`) directory without implementing advanced features like Risk/Strategy engines, LLMs, or ML yet.

## Integration Philosophy
We adhere to an **Evidence-First** and **Contract-Driven** design.
- AI must reason based on evidence (e.g., file existence, specific dependencies).
- No direct coupling between domains. Subsystems communicate via well-defined data models.
- **Person 3 to Person 1 Flow (Initial Boundary):**
  Person 3 (Platform) → Triggers Application Analysis Job → Person 1 (Intelligence) processes and generates → ApplicationModel → Returns to Person 3.
  (Implemented via a clean service interface, deferring Redis/Celery/gRPC for later).
