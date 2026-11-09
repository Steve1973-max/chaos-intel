# CHAOS-INTEL API Documentation

Base Prefix: `/api/v1`

## Authentication & RBAC
All protected routes require an authentication key supplied via the `X-API-Key` header or `Authorization: Bearer <key>`.

| Role | Hierarchy Level | Capabilities | Default Test Key |
|---|:---:|---|---|
| **Admin** | 3 | Full access, chaos approval, pipeline cancellation | `admin-key-supersecret` |
| **Operator** | 2 | Application registration, test execution, chaos scheduling | `operator-key-secret` |
| **Viewer** | 1 | Read-only inspection of graphs, risks, reports, metrics | `viewer-key-public` |

---

## Endpoint Catalog

### 1. System Health
- `GET /api/v1/health`: Overall platform status and version info.
- `GET /api/v1/health/services`: Detailed health status of all 4 microservices + background queue.

### 2. Application Intelligence
- `POST /api/v1/applications/register`: Register directory codebase path (`role >= operator`).
- `POST /api/v1/applications/upload`: Upload and safely stage application archive (`.zip`, `.tar.gz`) (`role >= operator`).
- `POST /api/v1/applications/{id}/analyze`: Enqueue background static AST discovery (`role >= operator`).
- `GET /api/v1/applications/{id}`: Application summary and detected technologies (`role >= viewer`).
- `GET /api/v1/applications/{id}/architecture`: Visual dependency graph nodes and edges (`role >= viewer`).
- `GET /api/v1/applications/{id}/risks`: Static risk assessment findings and composite score (`role >= viewer`).
- `GET /api/v1/applications`: Paginated list of registered applications (`role >= viewer`).

### 3. Testing Agents
- `POST /api/v1/testing/plans/generate`: Synthesize test plan based on architecture topology (`role >= operator`).
- `GET /api/v1/testing/plans/{id}`: Retrieve test plan and candidate cases (`role >= viewer`).
- `POST /api/v1/testing/executions`: Enqueue test plan execution against target application (`role >= operator`).
- `GET /api/v1/testing/executions/{id}`: Detailed step-level trace results (`role >= viewer`).
- `GET /api/v1/testing/executions`: Paginated list of test executions (`role >= viewer`).

### 4. Controlled Chaos Engine (Dry-Run Mode)
- `POST /api/v1/chaos/experiments`: Create and validate declarative 12-fault experiment specification (`role >= operator`).
- `POST /api/v1/chaos/experiments/{id}/approve`: Record explicit human safety approval grant (`role == admin`).
- `POST /api/v1/chaos/executions`: Initiate controlled dry-run experiment run (`role >= operator`, requires `dry_run: true`).
- `GET /api/v1/chaos/executions/{id}`: Retrieve dry-run verification report and event timeline (`role >= viewer`).
- `GET /api/v1/chaos/experiments`: Paginated list of experiment specifications (`role >= viewer`).

### 5. Telemetry & Failure Intelligence
- `POST /api/v1/telemetry/ingest`: Ingest metrics, structured logs, and distributed trace spans (`role >= operator`).
- `POST /api/v1/intelligence/analyze`: Run multi-signal anomaly correlation and root-cause ranking (`role >= operator`).
- `GET /api/v1/intelligence/reports/{id}`: Retrieve failure intelligence analysis report (`role >= viewer`).
- `GET /api/v1/intelligence/recommendations`: Filterable list of prioritized remediation actions (`role >= viewer`).

### 6. Distributed Orchestration
- `POST /api/v1/orchestration/pipeline`: Trigger full 10-step distributed resilience audit (`role >= operator`, supports `idempotency_key`).
- `GET /api/v1/orchestration/pipeline/{id}`: Retrieve pipeline execution timeline and artifacts (`role >= viewer`).
- `POST /api/v1/orchestration/pipeline/{id}/cancel`: Request graceful pipeline cancellation (`role >= operator`).
- `GET /api/v1/orchestration/jobs`: Paginated list of background jobs (`role >= viewer`).

