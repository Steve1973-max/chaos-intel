# CHAOS-INTEL — PHASE 2C.4A
## RECOVERY AND OUTBOX — READ-ONLY DESIGN ASSESSMENT

### 1. Current State Findings & Artifacts
The durable orchestration and fencing implementation is complete and correctly isolates the dry-run execution path.
- **Orchestration**: `src/execution/orchestrator.py` currently handles `LeaseAcquisitionError` and `LeaseOwnershipError`, but leaves runs in intermediate states if the process dies abruptly.
- **States**: `src/execution/states.py` defines `RECOVERY_CHECK`, `ROLLBACK_FAILED`, `RECOVERY_FAILED`.
- **Outbox Model**: `OutboxEventModel` exists in `src/execution/persistence/models.py` with `delivery_status` and `retry_count`.
- **Idempotency**: `IdempotencyRecordModel` supports `in_progress` and `completed` states. A crash leaves the record indefinitely `in_progress`.

### 2. Crash-State Matrix
| Crash Timing | Run State | Idempotency Status | Recovery Action Needed |
| :--- | :--- | :--- | :--- |
| **Before DB commit (Preflight)** | `CREATED` | `in_progress` | Safe to automatically resume/retry. No external side effects occurred. |
| **During Adapter Execution** | `AUTHORIZED` (or `RUNNING` in live) | `in_progress` | **Uncertain**. For dry-run, safe to fail/resume. For live, the external system may be mutating. Must transition to `RECOVERY_CHECK`. |
| **After Adapter, Before Publication** | `AUTHORIZED` | `in_progress` | External side effect finished, but result lost. Must query adapter to reconcile actual outcome before advancing. |
| **During DB commit (Publication)** | `AUTHORIZED` | `in_progress` | `CommitUncertaintyError` yields `outcome_unknown`. Manual or external reconciliation required. |

### 3. Outbox Transaction and Delivery Semantics
- **Atomic Creation**: Outbox events (e.g., `RunStateChanged`, `ExecutionRequested`) **must** be appended inside the exact same `fenced_transaction` that modifies the `ExperimentRunModel`. 
- **Delivery Guarantees**: The outbox worker polls for `delivery_status = 'pending'`. It guarantees **at-least-once** delivery. 
- **Deduplication**: Because the outbox worker might retry, downstream consumers must be fully idempotent, natively deduping via the `OutboxEventModel.id`.
- **Dead-Letter Handling**: If delivery fails repeatedly, `retry_count` is incremented. Above a threshold (e.g., 5), `delivery_status` shifts to `'failed'`, generating an `AuditEvent` to alert operators.

### 4. Recovery Eligibility & Uncertainty Rules
A recovery worker scanning for abandoned runs (e.g., lease expired but idempotency still `in_progress`) must distinguish between safe restarts and uncertain operations:
- **Safe to Resume**: Operations abandoned in purely internal states (`CREATED`, `PREFLIGHT`, `AUTHORIZATION_PENDING`) where no adapter invocation could have logically occurred.
- **Uncertain (Do Not Replay)**: Operations abandoned in `SETUP`, `RUNNING`, `OBSERVING`, `ROLLBACK`, or `ABORT_REQUESTED`. The recovery worker **must never** automatically replay these. Instead, it must acquire the lease and transition the run to `RECOVERY_CHECK`.
- **Reconciliation**: From `RECOVERY_CHECK`, the orchestrator must invoke read-only adapter queries (e.g., `adapter.verify_state()`) to deterministically confirm the external side effect's outcome before determining the true terminal state (`FAILED`, `COMPLETED`, or `ROLLBACK`).

### 5. Enforcing Fencing in Recovery
Recovery workers must play by the exact same rules as the primary orchestrator:
1. Target an abandoned run.
2. Call `LeaseRepository.acquire(resource_id=f"run:{run_id}", owner_id=worker_id)`.
3. Receive a new `fencing_token`, which forcibly invalidates the crashed/zombied orchestrator's token.
4. Execute all state transitions (e.g., moving to `RECOVERY_CHECK`) and outbox event publishing strictly within the `FencedTransactionBoundary`.

### 6. PostgreSQL Testing Requirements
While SQLite validates the logical Python exception trees and transactional scopes, genuine PostgreSQL integration tests are strictly required for:
1. **`SELECT ... FOR UPDATE` Blocking**: Confirming that a stalled worker correctly blocks a recovery worker's `acquire()` until the TCP connection drops or the transaction completes.
2. **`SAVEPOINT` / Nested Transactions**: Confirming concurrent idempotency reservations (`IntegrityError` collisions) correctly rollback to the savepoint without poisoning the outer transaction in Postgres.

### 7. Phased Implementation Plan
- **Phase 2C.4B**: Outbox Publisher Integration. 
  - *Acceptance*: State transitions automatically write outbox events within the `fenced_transaction`. No outbox consumers exist yet.
- **Phase 2C.4C**: Outbox Consumer Worker. 
  - *Acceptance*: A background poller successfully delivers pending events idempotently, handles retries, and transitions events to `'failed'` (dead-letter).
- **Phase 2C.4D**: Recovery Worker & Reconciliation.
  - *Acceptance*: A worker identifies expired leases with `in_progress` idempotency, acquires the fencing token, and safely transitions active live runs to `RECOVERY_CHECK` without triggering replays.
