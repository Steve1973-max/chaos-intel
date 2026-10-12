# CHAOS-INTEL — STEP 12C.2C PHASE 2C.1
## READ-ONLY ARCHITECTURE & DEPENDENCY ASSESSMENT

### 1. Executive Assessment
The persistence and orchestration implementations effectively utilize the SQLAlchemy baseline for durable state, history, and optimistic concurrency. Idempotency is durably protecting the orchestration loop from unsafe concurrent executions and replays. However, the `LeaseRepository` is entirely unwired (orchestrator still relies on the in-memory `LeaseManager`), and the outbox pattern is merely a database schema without repository or dispatch logic. Crucially, the system correctly favors safety (failing closed on stalled idempotency keys) because it currently lacks a mechanism to prove whether a crashed worker initiated an external side effect.

### 2. Actual Implementation Inventory
- **LeaseRecordModel & SqlAlchemyLeaseRepository:**
  - *Location:* `src/execution/persistence/models.py`, `src/execution/persistence/repositories.py`.
  - *Status:* Implemented and migrated. Uses `with_for_update()` for atomic acquisition and `fencing_token` for validation.
  - *Wiring:* **Unwired**. `OrchestrationController` (`src/execution/orchestrator.py`) still defaults to the in-memory `LeaseManager`.
- **IdempotencyRecordModel & SqlAlchemyIdempotencyRepository:**
  - *Location:* `models.py`, `repositories.py`.
  - *Status:* Implemented and fully wired in `OrchestrationController`.
- **ExperimentRunModel, RunRepositories, History, Optimistic Concurrency:**
  - *Location:* `models.py`, `repositories.py`.
  - *Status:* Implemented. `transition_state` enforces optimistic concurrency via version checks.
- **AuditEventModel & Repository:**
  - *Location:* `models.py`, `repositories.py`.
  - *Status:* Implemented and wired into the orchestration transaction boundary.
- **OutboxEventModel:**
  - *Location:* `models.py`.
  - *Status:* Model exists (`transactional_outbox`). **Unwired/Incomplete**. No repository interface, implementation, or dispatch logic exists.
- **TransactionBoundary & CommitUncertaintyError:**
  - *Location:* `repositories.py`, `interfaces.py`.
  - *Status:* Implemented. Handled safely in the orchestrator.
- **OrchestrationController & LifecycleController:**
  - *Location:* `src/execution/orchestrator.py`, `src/execution/lifecycle.py`.
  - *Status:* Wired. Lifecycle is computed purely in memory; Orchestrator manages the durable commits.
- **Alembic Migrations:**
  - *Location:* `alembic/versions/cd4d74de49fe_baseline_migration.py`.
  - *Status:* Contains schemas for all models including `leases` and `transactional_outbox`.

### 3. Durable Lease Integration Findings
1. **Acquisition/Renewal:** Acquired atomically via `SELECT ... FOR UPDATE`. Renewals validate the `owner_id` and `fencing_token`.
2. **Atomicity:** Yes, row-level locks and `IntegrityError` handling via savepoints provide atomic acquisition.
3. **Fencing Tokens:** `fencing_token` increments on each acquisition. It protects the lease itself but is **not** currently passed into the `RunRepository` to fence database writes. Optimistic concurrency (version) is the only write fence for runs.
4. **Interaction with Idempotency:** Leases protect the orchestration worker's active processing slot. Idempotency reservations protect the request payload globally.
5. **Vulnerability:** If a lease expires while the original worker is executing a long adapter call, a new worker could acquire the lease. The original worker's database writes might be rejected by optimistic concurrency, but its external side effects cannot be recalled. A database fencing token does not protect external systems.

### 4. Crash-Point and Recovery Matrix

| Crash Point | Visible Durable State | Safe to Auto-Retry? | Evidence/Reconciliation Needed |
| :--- | :--- | :--- | :--- |
| **Before Reservation** | Nothing. | **Yes.** | None. Idempotency will reserve cleanly. |
| **After Reservation, Before LC Commit** | Idempotency `in_progress`. | **No.** | We cannot prove the LC commit didn't secretly succeed (uncertain commit). Must check Run state. |
| **During LC Commit (Uncertain)** | Idempotency `in_progress`. Run state unknown. | **No.** | Compare expected Run state version vs DB version. |
| **After LC Commit, Before Adapter** | Idempotency `in_progress`. Run = `AUTHORIZED`. | **No.** | Cannot prove adapter wasn't invoked. Requires adapter-specific query to external system. |
| **During Adapter Execution** | Idempotency `in_progress`. Run = `AUTHORIZED`. | **No.** | External side-effect outcome is unknown. |
| **After Adapter, Before Publish** | Idempotency `in_progress`. Run = `AUTHORIZED`. | **No.** | External side-effect completed. Replaying would duplicate it. |
| **Worker Restarts / Concurrent** | Lease `active` or `expired`. Idempotency `in_progress`. | **No.** | Worker might still be alive. Cannot trust lease expiration as proof of process death. |

*Contract Gap Identified:* The current architecture cannot distinguish between "crashed before adapter execution" and "crashed during adapter execution." Any stalled `in_progress` idempotency record past the `AUTHORIZED` state requires out-of-band external reconciliation before it can be retried.

### 5. Transactional Outbox Integration Design
- **Transaction Boundary:** State changes (e.g., `RunTransitionHistory`) and `OutboxEventModel` insertion MUST share the same `SqlTransactionBoundary`.
- **Claiming & Dispatch:** A background dispatcher will use PostgreSQL's `SELECT ... FOR UPDATE SKIP LOCKED` to claim pending events without blocking concurrent dispatchers.
- **Delivery Model:** **At-least-once**. The system guarantees the outbox event is dispatched, but crashes post-dispatch (before ack) will result in redelivery. Consumers MUST be idempotent using the outbox `id`.
- **Minimum Additions:** An `OutboxRepository` containing `append()`, `claim_batch()`, `acknowledge()`, and `mark_failed()` methods.

### 6. PostgreSQL Concurrency Requirements
SQLite file-level locking is insufficient to prove the following behaviors. The skipped `testcontainers.community.postgres` tests must eventually cover:
1. **Competing Lease Acquisition:** Proving multiple concurrent threads attempting to acquire the same `resource_id` safely resolve without deadlocks.
2. **Outbox Claim Contention:** Proving `SKIP LOCKED` functions correctly to allow multiple dispatch workers to pull disjoint batches of outbox events simultaneously.
3. **Concurrent Idempotency Reservation:** Validating nested savepoints (`begin_nested()`) behave correctly under Postgres isolation levels when handling duplicate fingerprints.

### 7. Proposed Implementation Sequence
**Substep 1: Durable Lease Wiring**
- *Scope:* Inject `SqlAlchemyLeaseRepository` into `OrchestrationController`. Wrap `_do_orchestrate` with durable lease acquisition.
- *Invariants:* External side-effects are not shielded by the lease.
- *Dependencies:* None. Can be verified via SQLite.

**Substep 2: Transactional Outbox Foundation**
- *Scope:* Implement `OutboxRepository` and wire it into `_execute_lifecycle` so state transitions automatically emit outbox events.
- *Invariants:* Strict atomic inclusion inside `TransactionBoundary`.
- *Dependencies:* None.

**Substep 3: Outbox Dispatch Worker**
- *Scope:* Implement the background worker claiming and publishing events.
- *Dependencies:* **Requires PostgreSQL** to verify `SKIP LOCKED` contention.

**Substep 4: Reconciliation Protocol**
- *Scope:* Implement an interface for adapters to query external systems (e.g., Kubernetes) to reconcile stalled `in_progress` runs.
- *Dependencies:* Outbox foundation and adapter read-APIs.

### 8. Risks and Unresolved Blockers
- **Fencing External Systems:** We cannot use DB leases to fence external API calls. Adapters must natively support idempotency keys when talking to external targets, or we must accept at-least-once delivery semantics for external side effects.
- **Unverified Concurrency:** Core mechanisms like `SKIP LOCKED` and `with_for_update()` remain technically unverified against the target engine (PostgreSQL).

*(No files were modified or executed destructively during this assessment).*
