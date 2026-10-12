# CHAOS-INTEL — STEP 12C.2C PHASE 2B.1 Assessment
## Read-Only Durable Idempotency Integration

### 1. Executive Summary

This read-only assessment details the strategy for integrating durable idempotency into the existing `OrchestrationController`. The current system relies on an in-memory idempotency manager. By integrating the existing `SqlAlchemyIdempotencyRepository`, we will guarantee that duplicate requests are intercepted across process boundaries and restarts. We explicitly address how reservation expiry is handled safely, the strict ordering of commits to prevent duplicate execution, and the schema-validated recovery of completed responses.

### 2. Exact Files and Methods Inspected

- **`src/execution/orchestrator.py`**: Inspected `OrchestrationController.orchestrate()`, `_do_orchestrate()`, and `_fail_and_audit()`.
- **`src/execution/reliability/idempotency.py`**: Inspected `IdempotencyManager` and `compute_fingerprint()`.
- **`src/execution/persistence/interfaces.py`**: Inspected `IdempotencyRepository`, `IdempotencyConflictError`, and `CommitUncertaintyError`.
- **`src/execution/persistence/repositories.py`**: Inspected `SqlAlchemyIdempotencyRepository.reserve()`, `publish_result()`, and `get_result()`. Checked `SqlTransactionBoundary.transaction()`.
- **`src/execution/persistence/models.py`**: Inspected `IdempotencyRecordModel` (`application_id`, `operation_scope`, `idempotency_key_digest`, `fingerprint`, `owner_id`, `status`, `terminal_result`).
- **`src/execution/orchestration_models.py`**: Inspected `OrchestrationResponse`.
- **Tests**: `tests/test_commit_uncertainty.py`, `tests/test_orchestration.py`, `tests/test_persistence_integration.py`.

### 3. Current Idempotency Implementation and Gaps

**Current Implementation:**
- Uses an in-memory `IdempotencyManager` scoped to the process.
- `SqlAlchemyIdempotencyRepository` is fully modeled and uses PostgreSQL savepoints (`session.begin_nested()`) to handle concurrent `IntegrityError` safely, supporting `acquired`, `in_progress`, and completed outcomes.
- Request fingerprints use a deterministic SHA-256 hash.

**Gaps:**
- The orchestrator currently does not consume the durable repository.
- `CommitUncertaintyError` is not communicated back to the idempotency record.
- **Reservation Expiry:** The `IdempotencyRecordModel` supports `expires_at`, but an expired reservation must not blindly permit another worker to take over, as the original worker may have left behind an unknown commit outcome.

### 4. Request Lifecycle and Proposed Integration Point

**Integration Point & Explicit Ordering:**
1. **Idempotency Reserve:** At the start of `orchestrate()`, attempt to reserve the key.
2. **Lifecycle Transaction:** Inside `_do_orchestrate()`, the database transaction commits the lifecycle state, transitions, and audits.
3. **External Adapter Execution:** The dry-run executes (outside the transaction).
4. **Idempotency Publish:** The orchestrator serializes the final `OrchestrationResponse` and publishes it to the idempotency record.

This explicit ordering guarantees that the lifecycle state is always committed *before* the idempotency record is marked completed.

### 5. Proposed Reservation / Result-Publication Protocol

- **Reservation**: Attempt to acquire using `idempotency_repository.reserve()`.
- **Conflict**: If `reserve()` throws `IdempotencyConflictError`, return `409 Conflict`.
- **In-Progress**: If `reserve()` returns `status == "in_progress"`, return `429 Too Many Requests`.
- **Expired/Stale Reservation**: If the system sweeps an expired `in_progress` record, it must **not** delete it or blindly set it to `acquired`. Because the lifecycle transaction might have committed before the crash, the record must be marked `outcome_unknown` or require reconciliation by checking the authoritative run state in the `RunRepository`.
- **Cache Hit**: If `status == "completed"`, validate and return the stored `terminal_result`.
- **Publication**: Only the unique request `owner` (generated per orchestration attempt) can call `publish_result()`.

### 6. Transaction Boundaries and Crash-Recovery Matrix

We must rigorously respect the explicit ordering of commits.

| Scenario | Repository Outcome | Response | Execution Occurs | Duplicate Prevented By |
| :--- | :--- | :--- | :--- | :--- |
| **A. New key and fingerprint** | `acquired` -> `completed` | Original Response | Yes | N/A |
| **B. Same key while in-progress**| `in_progress` | `rejected` (concurrent) | No | Idempotency lock |
| **C. Same key, diff. fingerprint**| Raises `IdempotencyConflictError` | `rejected` (conflict) | No | Fingerprint check |
| **D. Response Cache Hit** | Returns `completed` | Cached Response | No | Cached state bypass |
| **E. Crash before LC Commit** | Record `in_progress` (stale) | N/A | No | Requires reconciliation to determine no LC commit occurred. |
| **F. Crash after LC Commit, before Publish** | Record `in_progress` (stale) | N/A | Adapter may run | **Lifecycle Guard**: Retry hits `Run already AUTHORIZED` check in `_do_orchestrate`. |
| **G. Unknown LC Commit Outcome** | Record transitions to `outcome_unknown` | `outcome_unknown` | No | Idempotency terminal state |

**Crucial Guarantee:** If the lifecycle commits successfully but the idempotency publish fails (Scenario F), the idempotency record remains `in_progress` (or eventually expires). When a client retries, even if the idempotency layer allows the retry to proceed past the lock (e.g., through a reconciliation mechanism or expiry), the **Lifecycle Database Guard** in `_do_orchestrate()` will fetch the authoritative DB state, observe it is already `AUTHORIZED` or `AUTHORIZATION_PENDING`, and immediately reject the request. This provides an impenetrable defense against duplicate execution.

### 7. Fingerprint and Stored-Response Contract

**Fingerprint:**
- Deterministic SHA-256 hash of `application_id`, `experiment_id`, `safety_decision_id`, and `mode`.
- This ensures request scope is tightly coupled to the application and authorization boundaries.

**Completed Responses Surviving Restarts:**
- A completed idempotency record stores the serialized `OrchestrationResponse` as JSON in `terminal_result`.
- Upon retrieval after a process restart, the system reconstructs the response using `OrchestrationResponse.model_validate(record.terminal_result)`.
- **Security & Disclosure:** The fingerprint enforces that a request only matches if the caller possesses the exact `safety_decision_id` and `application_id`. The response payload itself does not store raw secrets or execution credentials, aligning with the `OrchestrationResponse` schema contract.

### 8. Exact Files Expected to Change During Implementation

1. **`src/execution/orchestrator.py`**: Inject `IdempotencyRepository`. Implement the reserve/publish boundaries wrapping the execution flow.
2. **`src/execution/persistence/repositories.py`**: Update `SqlAlchemyIdempotencyRepository` to handle the `outcome_unknown` transition for failed commits or stale expirations.
3. **`tests/test_idempotency.py`** & **`tests/test_orchestration.py`**: Add tests and update mocks.

### 9. Test Plan and Measurable Acceptance Criteria

1. **Reservation Ownership:** First caller successfully reserves; concurrent caller gets `in_progress` rejection.
2. **Crash & Expiry Safety:** A mocked crash leaves a record `in_progress`. Advancing the clock triggers expiry. Retrying the request verifies the system safely reconciles or rejects, but *never* replays blindly.
3. **Commit Ordering & Publish Failure:** Mock the `publish_result()` to fail *after* lifecycle commit. Retrying the same request proves the lifecycle guard catches the duplicate and returns a safe rejection.
4. **Crash Recovery & Schema Validation:** Simulate a process restart by creating a new `OrchestrationController` instance. Assert that the cached response is correctly deserialized back into an `OrchestrationResponse` object.
5. **Fingerprint Conflict:** Assert modifications to `decision_id` with the same key produce `IdempotencyConflictError`.

### 10. Unresolved Decisions or Blockers

- **Reconciliation of Expired Records:** When an `in_progress` record expires, the system must definitively resolve whether the lifecycle transaction committed before deciding if a retry is safe. Currently, relying purely on the lifecycle guard in `_do_orchestrate` handles this flawlessly, but we must decide if the idempotency record itself should be automatically scrubbed/updated by a background worker to avoid cluttering the database. 
- **PostgreSQL Native Validation:** Because Docker is unavailable locally, PostgreSQL `IntegrityError` savepoint concurrency behavior will be validated using SQLite equivalents, deferring native PG concurrency testing to CI.
