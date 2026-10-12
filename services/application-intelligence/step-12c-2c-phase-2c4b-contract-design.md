# CHAOS-INTEL — PHASE 2C.4B.4
## RECOVERY AND OUTBOX CONTRACT HARDENING (DESIGN)

### 1. Durable Execution Intent Prerequisite
To prove whether an adapter invocation could have begun, the system utilizes a durable execution-intent marker. This marker is a strict prerequisite: **every adapter invocation path must require a successfully committed execution-intent marker** (e.g., transition from `AUTHORIZED` to `RUNNING`) before any remote call occurs.

**Enforcement & Testing**:
- *Enforcement*: The orchestrator architecture enforces this invariant by structurally isolating the transaction boundary from adapter invocation. The orchestrator must strictly evaluate the return of the `fenced_transaction` commit containing the intent marker. If the commit raises any exception (or blocks indefinitely), the invocation branch is categorically unreachable.
- *Testing*: Unit tests must simulate transaction aborts, database disconnects, and `CommitUncertaintyError` during the intent-marker commit phase to explicitly assert that the external adapter mock is never invoked.

### 2. Original-Worker Safety & Fenced Recovery
Before a recovery worker releases an idempotency reservation, marks a request failed, or makes a key reusable, it must absolutely guarantee the original worker cannot subsequently invoke the adapter. Lease expiration alone is inherently insufficient because a zombied process may awaken holding stale state.

**Fenced Recovery Protocol**:
1. The recovery worker actively acquires the run's lease, generating a new `fencing_token`.
2. The recovery worker executes state inspection *strictly within the `fenced_transaction`*, utilizing a `SELECT ... FOR UPDATE` equivalent (or optimistic concurrency validation) to prevent stale reads.
3. If the run state is `NOT_INVOKED_PROVEN` (intent never committed), the new fencing token securely guarantees that if the zombied worker awakens, its attempt to commit the execution-intent marker will face immediate rejection (`LeaseOwnershipError`). Therefore, the original worker is mechanically blocked from reaching the adapter invocation phase, rendering it completely safe for the recovery worker to abort the run and durably resolve the original idempotency record.

### 3. Recovery Classification
- **`NOT_INVOKED_PROVEN`**
  - *Evidence Required*: The durably committed run state is strictly prior to the execution-intent marker (e.g., `CREATED`, `PREFLIGHT`, `AUTHORIZATION_PENDING`, `AUTHORIZED`). 
  - *Permitted Actions*: The recovery worker acquires the lease, durably aborts the run (`FAILED`), and permanently resolves the idempotency record with a failed result.
  - *Retry Semantics*: A duplicate request with this completed idempotency key must return the recorded failed result. To re-attempt the operation, the caller MUST issue a new request with a completely new idempotency key or invoke a separate authorized retry operation. The system will never silently reuse, recycle, or clear a completed key to allow replay.

- **`INVOCATION_POSSIBLE`**
  - *Evidence Required*: The execution-intent marker (e.g., `RUNNING`, `SETUP`, `ROLLBACK`) is durably committed, but no terminal outcome is recorded. The crash could have occurred before, during, or after the remote call.
  - *Permitted Actions*: Automatic replay is strictly prohibited. The recovery worker must acquire a new fencing token, transition the run to `RECOVERY_CHECK`, and attempt read-only remote reconciliation via the adapter.

- **`OUTCOME_CONFIRMED`**
  - *Evidence Required*: A terminal state (`COMPLETED`, `FAILED`, `ABORTED`, `ROLLBACK_FAILED`, `RECOVERY_FAILED`) is durably committed.
  - *Permitted Actions*: The operation is definitively resolved. Reconcile missing idempotency publication via the uncertain-publication recovery protocol.

- **`OUTCOME_UNKNOWN`**
  - *Evidence Required*: The system encountered a `CommitUncertaintyError`, or the adapter's read-only reconciliation attempt in `RECOVERY_CHECK` was unsupported or inconclusive.
  - *Permitted Actions*: Stop automated processing. Do not assume failure. Do not replay. Retain the unresolved state and flag the operation for audited operator resolution.

### 4. Uncertain-Publication Recovery Protocol & Idempotency Consistency
When recovering a terminal run (`OUTCOME_CONFIRMED`) where final database publication encountered a `CommitUncertaintyError` or process crash, the recovery process must:
1. Read the authoritative run and idempotency records within a fenced transaction.
2. Validate that the run identity and request fingerprint flawlessly match the payload originally recorded in the idempotency record.
3. If the idempotency publication is **already committed** (it possesses a valid `terminal_result`), the worker must strictly preserve it and halt.
4. If the idempotency publication is **demonstrably missing** (status is `in_progress`), but the terminal run is perfectly consistent with the fingerprint, the worker must explicitly publish the terminal result inside the fenced transaction.
5. If the commit outcome cannot be established (database unreachable) or the record consistency fails validation, the worker must **retain the unresolved state and stop**. It must never blindly publish a result for a mismatched fingerprint or an unknown outcome, and must never replay external operations.

### 5. Handling Commit Uncertainty
When the system encounters a `CommitUncertaintyError` (e.g., connection lost during commit phase), the recovery protocol enforces strict safety:
- The system **must not assume the commit failed** and **must not replay external operations**.
- If the database is unreachable, the system retains the unresolved state.
- If the database is reachable, the worker inspects the durably committed state under the fenced boundary. If the transaction succeeded, the state is terminal (handled via the Uncertain-Publication Recovery Protocol). If the transaction failed, the prior active state remains, and it is safely routed to the `INVOCATION_POSSIBLE` (reconciliation) flow.

### 6. Transactional Consistency & Outbox Semantics
- **Atomic Operations**: All elements of a domain mutation must be transactionally consistent under the active fencing token. The `ExperimentRunModel` state transition, `RunTransitionHistoryModel` appendage, `AuditEventModel`, `OutboxEventModel`, and `IdempotencyRecordModel` result publication must commit atomically.
- **Outbox Delivery**: The outbox guarantees at-least-once delivery. It distinguishes event deduplication (handled mechanically by consumers via `OutboxEventModel.id`) from deduplication of external side effects (handled upstream by the Idempotency Manager).

### 7. Idempotency Lifecycle for `outcome_unknown`
- **Key Retention & Reuse**: Keys flagged as `outcome_unknown` are retained indefinitely and cannot be reused. Duplicate incoming requests immediately receive the cached `outcome_unknown` payload. 
- **Audited Resolution**: Operator overrides must generate a mandatory `AuditEvent` explicitly documenting the reconciliation decision.

### 8. Acceptance Test Design
The implementation phase must validate the following design-level tests:
1. **Original-Worker Racing**: Simulate a delayed worker attempting to commit an execution intent after a recovery worker has already acquired the lease (expect rejection).
2. **Completed-Key Duplicate Requests**: Verify a duplicate request identical to a recovered `NOT_INVOKED_PROVEN` failed run immediately returns the recorded result.
3. **Explicit Retry Semantics**: Verify that attempting to modify or reuse a completed idempotency key fails; explicit retries definitively require a new key.
4. **Publication Already Committed**: Recovery worker inspects a terminal run with an existing idempotency result and preserves it without modification.
5. **Publication Demonstrably Missing**: Recovery worker validates fingerprint consistency on a terminal run with an `in_progress` idempotency record, successfully publishing the missing result in a fenced transaction.
6. **Inconsistent Records**: Simulate an idempotency fingerprint mismatch on a terminal run during recovery; expect the system to halt and flag for operator resolution.
7. **Uncertain Publication Commits**: Simulate a dropped connection precisely during the idempotency publication commit. Ensure the worker successfully executes the uncertain-publication protocol securely.

### 9. Failure Matrix

| Crash Boundary | Durable State | Classification | Safe Recovery Action | Replay Prohibited? |
| :--- | :--- | :--- | :--- | :--- |
| **Before execution-intent commit** | `AUTHORIZED` (or earlier) | `NOT_INVOKED_PROVEN` | Acquire lease to fence out previous owner. Durably resolve original run and idempotency record as failed. Duplicate requests return the recorded result. A new attempt explicitly requires a new key or a separate authorized retry operation; never silently reuse a completed key. | No (new request with new key permitted) |
| **After intent commit, before adapter invocation** | `RUNNING` (or `SETUP`) | `INVOCATION_POSSIBLE` | Transition to `RECOVERY_CHECK`. Attempt read-only reconciliation. | **YES** |
| **During adapter invocation** | `RUNNING` (or `SETUP`) | `INVOCATION_POSSIBLE` | Transition to `RECOVERY_CHECK`. Attempt read-only reconciliation. | **YES** |
| **After external completion, before final DB publication** | `RUNNING` (or `SETUP`) | `INVOCATION_POSSIBLE` | Transition to `RECOVERY_CHECK`. Attempt read-only reconciliation. | **YES** |
| **During final database commit** | Varies (Terminal or `RUNNING`) | `OUTCOME_CONFIRMED` or `INVOCATION_POSSIBLE` | Execute uncertain-publication protocol: validate identity/fingerprint. If publication committed, preserve it. If demonstrably missing & consistent, publish in fenced transaction. If uncertain/inconsistent, retain unresolved state and stop. | **YES** |
