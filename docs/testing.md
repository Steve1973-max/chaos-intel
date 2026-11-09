# CHAOS-INTEL Testing & Verification Guide

## Test Suite Structure

The CHAOS-INTEL repository contains multiple test suites:

| Suite | Path | Test Count | Focus |
|---|---|:---:|---|
| **E2E & Integration** | `tests/` | 27 tests | Gateway, security, E2E 14-step workflow, orchestration, client proxies |
| **App Intelligence** | `services/application-intelligence/tests/` | 287 tests | Static discovery, AST parsing, risk engine, leases, idempotency |
| **Testing Agents** | `services/testing-agents/tests/` | 23 tests | Test case generation, prioritization, execution engine |
| **Chaos Engine** | `services/chaos-engine/tests/` | 23 tests | 12-fault catalog, blast radius, safety approval, dry-run adapter |
| **Failure Intelligence**| `services/failure-intelligence/tests/` | 22 tests | Anomaly detection, telemetry processing, root-cause correlation |
| **Frontend Unit** | `apps/web/src/__tests__/` | 7 tests | Safety invariants, API client storage, navigation routes |

---

## Running Test Suites

### 1. Platform Gateway & End-to-End Tests
```bash
# Set PYTHONPATH to root
export PYTHONPATH="."
pytest tests/ -v
```

### 2. Microservice Test Suites
```bash
# Application Intelligence
cd services/application-intelligence
PYTHONPATH="src:." pytest -m "not postgres"

# Testing Agents
cd services/testing-agents
PYTHONPATH="src:." pytest

# Chaos Engine
cd services/chaos-engine
PYTHONPATH="src:." pytest

# Failure Intelligence
cd services/failure-intelligence
PYTHONPATH="src:." pytest
```

### 3. Frontend Tests & Production Build
```bash
cd apps/web
npm test           # Runs Vitest unit test suite
npm run build      # Executes tsc typecheck and Vite bundle
```

### 4. PostgreSQL Real Persistence Gate
```bash
# Runs against real Docker PostgreSQL container with zero skips permitted
cd services/application-intelligence
python -m pytest tests/test_persistence_integration.py -v
```

