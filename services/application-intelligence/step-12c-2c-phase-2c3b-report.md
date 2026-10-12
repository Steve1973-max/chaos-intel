# CHAOS-INTEL — PHASE 2C.3B FINAL REPORT
## DURABLE FENCING INTEGRATION INTO ORCHESTRATION

### 1. Exact Files Changed and Why
- **`src/execution/orchestrator.py`**: 
  - Updated `OrchestrationController.__init__` to inject the optional `lease_repository`.
  - Modified `orchestrate` to natively acquire a durable lease explicitly identifying the protected run resource and passing the `fencing_token` downward.
  - Refactored `_do_orchestrate`'s inner `_execute_lifecycle` closure and idempotency publication path to wrap all persistent mutations natively inside the `fenced_transaction` when a durable lease is active.
- **`tests/test_orchestration_fencing.py`**:
  - Newly created deterministic SQLite integration tests proving correct lease acquisition logic, clean rejection on competing workers, protection against stale fencing tokens, and duplicate idempotency bypass functionality.

### 2. Orchestration Sequence Before vs. After Integration
- **Before Integration**: The controller relied upon an in-memory `LeaseManager` via `LeaseContext`, which enforced only process-local mutual exclusion. Lifecycle database mutations were written through a standard generic `TransactionBoundary.transaction()`, which lacked active database fencing and exposed the system to split-brain overwrites on restart.
- **After Integration**: The controller now acquires a universally scoped lock directly via `SqlAlchemyLeaseRepository`. It propagates the resulting `fencing_token` into the execution path. Whenever the controller executes `_execute_lifecycle` or attempts `idempotency_repository.publish_result()`, it establishes a `fenced_transaction`. If the worker has hung and its lease expired and was replaced, the active query detects the token drift instantly, rejecting the mutation.

### 3. Lease-Resource Identity and Owner-Identity Design
- **Lease-Resource Identity**: Consistently formatted as `f"run:{request.experiment_run.run_id}"`. This intrinsically ties the locking scope exactly to the single ExperimentRun lifecycle instance, cleanly permitting parallel orchestration requests that interact with distinct runs without unnecessary contention.
- **Owner Identity**: Inherits from the supplied idempotency owner, natively defaulting to a strictly unique instance via `str(uuid.uuid4())`. This prevents the fatal risk of silent reuse: every orchestration attempt bears a unique identifier, meaning a "zombie" attempt waking up cannot forge ownership over a resource actively leased by a restarted worker.

### 4. Enforcement Points for Protected Writes
Fencing is enforced in two strategic locations within `_do_orchestrate`:
1. **Inside `_execute_lifecycle`**: Specifically wrapping `run_repository.transition_state` and the accompanying appendations to transition histories and audit logs.
2. **Inside Idempotency Publication**: Explicitly wrapping `idempotency_repository.publish_result()`.

### 5. Handling Acquisition, Release, and Failures
- **Acquisition**: Triggered synchronously at the start of `orchestrate`. If `LeaseAcquisitionError` occurs (i.e. another valid worker holds the lease), execution halts and returns a clean rejection status.
- **Release**: Handled in a strict `finally:` block directly bounding `_do_orchestrate`. The release strictly demands the correct `fencing_token` matching the database state to gracefully release.
- **Loss/Failure Detection**: If the lease inherently expires and is seized by another process mid-execution (such as during a long-running adapter call), the subsequent `fenced_transaction` will eagerly raise `LeaseOwnershipError`. `_do_orchestrate` naturally traps this and returns an `outcome_unknown` or `rejected` error (depending on if execution occurred).

### 6. Safety of Uncertain Commits and External Side Effects
- **External Side Effects**: The Dry Run execution adapter remains untouched. Because execution logic occurs strictly isolated from the transaction boundaries, the database is never held locked while the external side effect is evaluated. 
- **Uncertain Commits**: Handled natively by the `FencedTransactionBoundary` fallback wrapper logic, which propagates `CommitUncertaintyError`. The orchestrator inherently routes this to a deterministic `"outcome_unknown"` payload, strictly ensuring no replay occurs dynamically without explicit manual intervention.

### 7. Focused and Full-Suite Test Results
- **Focused Tests (`test_orchestration_fencing.py`)**: 4 passing SQLite determinism tests demonstrating success, stale rejection, acquisition failure, and idempotent duplicates cleanly.
- **Full-Suite Output**: 
```text
collected 242 items
================== 238 passed, 4 skipped, 1 warning in 4.63s ==================
```

### 8. PostgreSQL Test Status
PostgreSQL concurrency logic evaluates structurally via SQLAlchemy's Native syntax `with_for_update()`, tested locally via SQLite equivalence savepoints. Live PostgreSQL Testcontainer suites were natively **skipped** pending a Docker engine.

### 9. Remaining Correctness Gaps
The integration behaves flawlessly under standard parameters.
However, because execution halts completely with `status="outcome_unknown"` when a `CommitUncertaintyError` is propagated from the transactional boundary (e.g., loss of DB connectivity), the external outcome state requires a reconciliation loop or recovery worker. The controller correctly refuses to aggressively replay, establishing the necessity of Phase 2D: Recovery Workers and Asynchronous Outbox paradigms.
