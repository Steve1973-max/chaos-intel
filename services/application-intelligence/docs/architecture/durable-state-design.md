# CHAOS-INTEL: Durable State and Distributed Coordination Design

## 1. Architecture Decision & Rationale

CHAOS-INTEL currently relies on process-local, in-memory state mapping `ExperimentRun` lifecycles, orchestration leases, idempotency tokens, and audit events. A transition to distributed coordination is necessary to support horizontally scaled workers and durable crash recovery.

### Technology Comparison

1. **PostgreSQL Only (Recommended)**
   - **Mechanism:** Leverages ACID transactions, row-level locking (e.g., `SELECT ... FOR UPDATE SKIP LOCKED`), and conditional updates (Compare-and-Swap).
   - **Pros:** Unified system of record; no extra deployment dependencies; strict serializability for state transitions; natively supports transactional outboxes.
   - **Cons:** Polling overhead for lease acquisition; requires explicit fencing tokens.

2. **PostgreSQL + Redis**
   - **Mechanism:** PostgreSQL for state, Redis for distributed locking (Redlock) and pub/sub.
   - **Pros:** Lower latency for lock acquisition; TTL-based lock expiry is native.
   - **Cons:** Introduces split-brain risks between lock state and DB state (requires fencing anyway); operational complexity of managing a Redis cluster; Redlock is notoriously unsafe against timing anomalies and GC pauses.

3. **PostgreSQL + Temporal (Workflow Engine)**
   - **Mechanism:** Temporal manages orchestrations as stateful workflows.
   - **Pros:** Built-in timers, retries, and idempotency.
   - **Cons:** Massive operational burden; paradigm shift requiring complete rewrite of `LifecycleController` and `Orchestrator`; excessive for current maturity.

### Conclusion
**We recommend PostgreSQL Only.** A relational database with transactional isolation and row-level locks natively provides the consistency required for safety-critical coordination without the overhead of external infrastructure. Fencing tokens (optimistic concurrency control via versioning) are sufficient to prevent stale worker commits.

---

## 2. Component Contracts

### A. Durable Run Repository
- **Create Run:** Inserts an initial `ExperimentRun` in `CREATED` state.
- **Read Run:** Fetches current state.
- **Atomic Transition:** Requires conditional updates. E.g., `UPDATE run SET state = 'AUTHORIZED', version = version + 1 WHERE id = X AND version = Y`. This prevents stale updates.
- **State Transition History:** Commits to a sibling `run_transitions` table within the same transaction.
- **Illegal Transitions:** The database layer enforces state constraints (e.g., via check constraints or strict repository gating) mirroring the existing `assert_valid_transition` logic.

### B. Distributed Leases
- **Identity & Scope:** A lease targets a specific `run_id`.
- **Owner Semantics:** Acquired by a worker UUID.
- **Fencing Tokens & Resource Protection:** On acquisition, a monotonically increasing `fencing_token` (or `version`) is generated. 
  - *Database Protection:* All subsequent DB writes for this run *must* include this token. Conditional updates (e.g., `WHERE version = X`) ensure that a stale worker cannot overwrite database state.
  - *External-Resource Protection:* A database fencing token alone **does not** magically make external side effects safe. If a worker pauses, its lease expires, and a new worker takes over, the paused worker might still wake up and send a stale network command to a Kubernetes API or external system. The destination system itself must enforce fencing (e.g., via `resourceVersion` in Kubernetes) or an equivalent ownership mechanism. If the destination cannot natively support fencing, any uncertain external operation explicitly requires reconciliation or manual intervention. We do not claim a DB token perfectly fences external side-effects.
- **Expiry:** Heartbeating updates an `expires_at` timestamp.
- **Stale Workers:** If a worker pauses (e.g., GC pause) and its lease expires, another worker acquires the lease, incrementing the `fencing_token`. When the paused worker wakes and attempts to commit, its database writes are rejected due to a stale token. However, as noted above, if it attempts to execute a live command *after* waking but *before* checking the DB, external side-effects could theoretically execute.
- **Unavailability:** If the database drops, the worker safely halts, as it cannot commit state or renew its lease.

### C. Durable Idempotency
- **Key Scope:** Unique constraint on `(application_id, experiment_id, idempotency_key)`.
- **Fingerprint:** Canonical SHA-256 hash of semantic request body (excluding secrets).
- **Atomic Reservation Protocol:** `ON CONFLICT DO NOTHING` is utilized as the primitive, but it operates within a distinct transaction boundary:
  1. **Reservation Transaction:** A worker attempts to `INSERT` the idempotency record. If successful, it becomes the reservation owner and proceeds. If the row already exists (`ON CONFLICT`), the worker does not acquire the reservation. It observes the existing record; if the status is `in_progress`, it immediately returns a typed `in_progress` response to the caller without waiting or executing. Only the reservation owner is authorized to proceed with orchestration.
  2. **Execution Phase:** Orchestration and (if applicable) external side-effects occur. This phase happens entirely *outside* of the idempotency database transaction. A database transaction cannot make an unrelated external side-effect atomic.
  3. **Result Publication Transaction:** Upon completion, the reservation owner updates the idempotency record with the final `ExecutionResult` and marks it `completed`.
- **Behavior:** Concurrent duplicates receive an `in_progress` response. Different fingerprints yield `IdempotencyConflictError`.
- **Completion:** Updates the record with the final `ExecutionResult`.
- **Expiry:** Records expire based on a defined retention policy (e.g., 30 days) to prevent infinite unbounded growth.

### D. Recovery and Reconciliation
- **Outcome Unknown:** Interrupted orchestration defaults to `outcome_unknown` upon recovery parsing.
- **Rule:** The system *never* automatically replays an uncertain real-world side effect. 
- **Reconciliation:** Requires independent evidence gathering (e.g., polling external adapters for execution state) or manual operator intervention.

### E. OUTCOME_CONFIRMED Classification Semantics (Phase 2C.5B)

> **Current behavior — dry-run boundary only.** The constraints below apply while the system operates exclusively in dry-run mode. They must not be interpreted as sufficient for real-adapter execution.

#### What OUTCOME_CONFIRMED currently means

`RecoveryClassifier.classify()` returns `OUTCOME_CONFIRMED` when the authoritative run record (read from the durable database) shows that `run.state` is one of the five terminal states: `COMPLETED`, `FAILED`, `ABORTED`, `ROLLBACK_FAILED`, or `RECOVERY_FAILED`.

This classification uses the run state as read from the DB and reported through `has_authoritative_state=True`. If `has_authoritative_state` is `False` or the run record is `None`, the classifier returns `OUTCOME_UNKNOWN` regardless of any cached state — it never claims confirmation from unavailable evidence.

#### What OUTCOME_CONFIRMED currently does NOT mean

`OUTCOME_CONFIRMED` does **not** independently verify that:

- An idempotency record exists for the run.
- The idempotency record's `status` is `completed`.
- The idempotency `terminal_result` is non-null and consistent with the terminal run state.
- The idempotency record was written by the same operation that produced the terminal run state.
- The request fingerprint on the idempotency record matches the originating request.

A run can reach a terminal state while its idempotency record remains `in_progress` or is absent entirely (for example, if the idempotency publication step failed after the run transitioned to terminal). The classifier will still return `OUTCOME_CONFIRMED` in that situation without flagging the inconsistency.

#### Why this is currently safe

This limitation is contained by two hard constraints that remain in force:

1. **Dry-run-only boundary.** Live mode is rejected by `OrchestrationController.orchestrate()` before any lifecycle or adapter work begins. The `DryRunAdapter` makes no real external mutations, so no actual side-effect confirmation is needed.
2. **Classifier is read-only.** `RecoveryClassifier.classify()` performs no adapter invocations, no lease acquisition, no state mutations, and no idempotency record writes. A false `OUTCOME_CONFIRMED` for a dry-run run has no operational consequence.

#### Required future behavior before real adapters are enabled

Before any live execution adapter is introduced, the outcome-confirmation logic must be strengthened. The following requirements apply:

1. **Cross-record corroboration is mandatory.** `OUTCOME_CONFIRMED` must require both a terminal run state *and* a consistent, completed idempotency record for the same run and request fingerprint. A terminal run state alone is not sufficient evidence of a consistent outcome.
2. **Missing idempotency record is not confirmable.** If the run is terminal but no idempotency record exists, the classifier must not return `OUTCOME_CONFIRMED`. The appropriate classification is `OUTCOME_UNKNOWN` or a new `OUTCOME_INCONSISTENT` variant, pending a design decision.
3. **Mismatched or in-progress idempotency is not confirmable.** If the idempotency record belongs to a different run, has a non-matching fingerprint, or is still `in_progress`, the classifier must return `OUTCOME_UNKNOWN`. It must not silently treat an inconsistent record as confirmation.
4. **Contradictory records must not be resolved automatically.** If the run state and idempotency result disagree about the outcome (e.g., run is `COMPLETED` but the stored result indicates failure), the system must flag the inconsistency for manual operator review rather than picking a winner.
5. **Uncertain commits remain unresolved.** A `CommitUncertaintyError` during any phase of outcome establishment must preserve the `outcome_unknown` status until authoritative evidence resolves it. The `CommitUncertaintyError` must never be silently converted into confirmation.

#### Design decision log

| Phase | Decision |
|-------|----------|
| 2C.5B | `OUTCOME_CONFIRMED` = terminal run state from authoritative DB only. Idempotency corroboration not required. Acceptable because the system is dry-run only. |
| Pre-live-adapter | Extend `RecoveryClassifier` to accept and require an idempotency record corroboration parameter. Introduce tests for all inconsistency scenarios (missing, mismatched, contradictory). |

### F. Audit Trail
- **Identity & Ordering:** Immutable append-only log mapped to `event_id` and `timestamp`.
- **Atomicity:** `AuditEvent` rows are committed in the exact same database transaction as the `ExperimentRun` transition.
- **Redaction:** Secrets are proactively redacted in the application layer before reaching the DB payload.
- **Tamper-Resistance:** Cannot guarantee true cryptographic tamper-proof properties without external WORM storage or blockchain anchoring, but restricts DELETE/UPDATE privileges at the IAM level.

### G. Approval and Safety Invariants
- **Immutable Decisions:** `SafetyDecision` rows are strictly append-only.
- **Approval Constraints:** Mutating run metadata does not constitute approval. `requires_configuration` decisions demand an entirely new run/decision tree.
- **Revalidation:** Target or environment shifts invalidate existing approvals natively by forcing a fingerprint/ID mismatch against the `SafetyDecision`.

---

## 3. Migration Phases

1. **Phase 1: Interface Abstraction (Current/Next)**
   - Extract `LeaseManager`, `IdempotencyManager`, and `AuditLogger` into Python `Protocol` or Abstract Base Classes.
   - Maintain current in-memory implementations for local dev/testing.
2. **Phase 2: PostgreSQL Implementation**
   - Implement `PostgresLeaseManager` etc., using SQLAlchemy/asyncpg.
   - Introduce database migration scripts (Alembic).
3. **Phase 3: Rollout and Feature Flagging**
   - Inject the Postgres managers via feature flags.
   - Monitor for transaction lock contention.
   - *Note: Switching dynamically back to in-memory fallback during an outage is prohibited, as it breaks mutual exclusion guarantees for distributed workers.*
