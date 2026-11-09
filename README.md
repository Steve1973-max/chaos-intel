# CHAOS-INTEL
**Intelligent Autonomous Software Resilience & Failure Discovery Platform**

[![CI](https://github.com/example/chaos-intel/actions/workflows/ci.yml/badge.svg)](https://github.com/example/chaos-intel/actions/workflows/ci.yml)
[![PostgreSQL Gate](https://github.com/example/chaos-intel/actions/workflows/postgres-integration.yml/badge.svg)](https://github.com/example/chaos-intel/actions/workflows/postgres-integration.yml)
[![Platform Version](https://img.shields.io/badge/version-2.4.0-blue.svg)](https://github.com/example/chaos-intel)
[![License](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)

---

## 1. Project Purpose & Architecture

CHAOS-INTEL is an enterprise-grade autonomous software resilience platform. It automatically ingests application codebases, extracts their architectural topologies, synthesizes targeted test suites, conducts controlled dry-run chaos experiments, ingests multi-signal observability telemetry, and correlates failure modes to produce ranked root-cause hypotheses and actionable remediations.

### Core Subsystems:
1. **Application Intelligence (`services/application-intelligence/`)**: AST-driven code scanner, service & dependency detector, technology fingerprinting, acyclic architecture graph builder, and static vulnerability risk assessment.
2. **Testing Agents (`services/testing-agents/`)**: Autonomous test planner, prioritizer, and multi-protocol execution engine (REST API, Playwright UI, and multi-step workflows).
3. **Controlled Chaos Engine (`services/chaos-engine/`)**: 12-fault catalog across infrastructure and service failure modes, blast-radius preview, steady-state baselines, and safety approval boundaries. **Live chaos execution is hard-disabled (dry-run mode enforced).**
4. **Failure Intelligence (`services/failure-intelligence/`)**: Telemetry normalization, metric time-series correlation, structured log inspection, trace span waterfall explorer, and ranked root-cause hypotheses strictly enforcing `is_causation_proven = false`.
5. **API Gateway & Orchestration (`apps/api/`, `workers/`)**: FastAPI versioned gateway (`/api/v1/`), correlation ID propagation, RBAC role enforcement, rate limiting, and distributed 10-step orchestrator.
6. **Web Dashboard (`apps/web/`)**: React 18, TypeScript, Tailwind CSS enterprise dark SaaS interface with 11 operational sections, interactive SVG architecture visualizer, sparklines, and report exports.

---

## 2. Monorepo Organization

```
├── apps/
│   ├── api/                         # FastAPI Gateway (/api/v1/) with RBAC & middleware
│   └── web/                         # React 18 + Vite + Tailwind CSS dashboard
├── services/
│   ├── application-intelligence/    # Static analysis, AST, architecture graph, risk engine
│   ├── testing-agents/              # Autonomous test planners & execution sandbox
│   ├── chaos-engine/                # 12-fault chaos catalog, safety guards, dry-run adapter
│   └── failure-intelligence/        # Telemetry ingestion, anomaly correlation, hypotheses
├── workers/                         # Background worker, task registry, distributed orchestrator
├── packages/
│   ├── clients/                     # Typed service client wrappers with loader isolation
│   └── schemas/                     # Canonical cross-team JSON schemas & contracts
├── infrastructure/                  # Docker Compose, init scripts, and deployment configs
├── tests/                           # End-to-end integration tests & performance benchmarks
└── docs/                            # In-depth architectural & API specifications
```

---

## 3. End-to-End Workflow

1. **Register/Upload**: Ingest source repository or upload archive (`.zip`, `.tar.gz`) with ZipSlip safeguards.
2. **Static Discovery**: Extract microservice topology, API routes, and dependencies via AST analysis.
3. **Risk Profile**: Calculate composite risk score and identify architectural fragility.
4. **Autonomous Testing**: Generate risk-targeted test suites across API, UI, and workflows.
5. **Controlled Chaos**: Model controlled failure scenarios from the 12-fault catalog.
6. **Safety Boundary**: Enforce explicit human safety approval grant via Admin API key.
7. **Dry-Run Simulation**: Execute fault scenario in dry-run mode with live execution ban.
8. **Telemetry Ingestion**: Ingest metrics, structured logs, and distributed trace spans.
9. **Failure Correlation**: Correlate anomalies across signals to identify probable root causes.
10. **Unified Report**: Deliver an evidence-backed resilience evaluation with actionable remediation steps.

---

## 4. Quick Start & Local Setup

### Prerequisites
- Python 3.12+ (or 3.14)
- Node.js 20+ & npm 10+
- Docker & Docker Compose (optional)

### Running Backend API Gateway
```bash
# Install dependencies
pip install fastapi "uvicorn[standard]" pydantic starlette sqlalchemy redis psycopg[binary] httpx anyio pytest pytest-asyncio

# Launch API Gateway
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --reload
# API Gateway: http://127.0.0.1:8000
# OpenAPI Docs: http://127.0.0.1:8000/docs
```

### Running Frontend Dashboard
```bash
cd apps/web
npm install
npm run dev
# Dashboard available on http://localhost:3000
```

### Running Complete Docker Stack
```bash
cp .env.example .env
docker compose up -d --build
```

---

## 5. Verification & Testing

```bash
# Run all platform integration and E2E tests:
PYTHONPATH=. pytest tests/ -v

# Run performance benchmarks:
PYTHONPATH=. pytest tests/benchmarks/test_performance.py -s

# Run frontend test suite:
cd apps/web && npm test

# Run frontend production build:
cd apps/web && npm run build
```

---

## 6. Safety & Invariant Guarantees

- **Live Chaos Execution Disabled**: All chaos experiments run strictly in dry-run mode (`dry_run: true`).
- **Hypothesis Disclaimer**: Inferred root causes enforce `is_causation_proven: false` and are never presented as proven facts.
- **Idempotency & Replay Fencing**: Uncertain external side effects are never automatically replayed; authoritative state checks fence duplicate operations.
- **Transaction Boundaries**: Database transactions are never held open across external agent calls or worker steps.
