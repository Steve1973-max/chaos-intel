# CHAOS-INTEL: Durable State Acceptance Criteria

Before implementation can be considered complete and before any live infrastructure execution adapters are enabled, the distributed coordination layer must pass the following verifiable criteria.

## 1. Safety Invariants

- **Transactional Atomicity:** `ExperimentRun` state transitions and their corresponding `AuditEvent` records must be committed in a single database transaction.
- **Fencing Protection:** A worker whose lease has expired must encounter a database-level rejection (e.g., `Update collision` or `FencingTokenError`) if it attempts to commit an execution result.
- **No Falsified Approvals:** Altering the payload of an `ExperimentSpecification` must cryptographically or relationally break its association with an existing `SafetyDecision`.
- **Fail Closed:** If the database becomes unreachable, all in-progress orchestration gracefully halts without initiating infrastructure side effects.

## 2. Testable Acceptance Criteria

### Unit / Component Level
1. **Idempotency Fingerprinting:** Verify that JSON payloads with identical semantic keys but differing insertion orders generate identical SHA-256 fingerprints.
2. **Secret Redaction:** Verify that audit serializers successfully strip credentials before generating database insert statements.
3. **Lease Contexts:** Verify that a `LeaseManager` releasing a lease gracefully handles connection drops.

### Concurrency / Integration Level (Using DB Synchronization)
4. **Concurrent Idempotency:** When 10 workers simultaneously attempt to insert the same `idempotency_key` and fingerprint, exactly 1 succeeds, and 9 receive an `in_progress` response.
5. **Concurrent Lease Acquisition:** When 5 workers attempt to claim an expired lease simultaneously, exactly 1 acquires it and increments the fencing token.
6. **Stale Worker Commits:** A worker that is synthetically paused (via threading events or barriers) until its lease expires, then resumes and attempts to commit an `ExecutionResult`, is explicitly denied by the repository due to a fencing token mismatch.

### Crash Recovery Level
7. **Pre-Execution Crash:** A worker crashes after transitioning a run to `AUTHORIZATION_PENDING`. A recovery worker successfully identifies the expired lease, re-acquires it, and re-executes authorization from scratch.
8. **Uncertain Outcome Enforcement:** A worker is synthetically crashed during `RUNNING` state (live-mode simulation). A recovery worker picks up the expired lease and asserts that `replay()` is blocked, returning `OUTCOME_UNKNOWN` or `MANUAL_REVIEW_REQUIRED`.

## 3. Pre-Requisites for Live Execution

Live execution adapters (e.g., Kubernetes fault injection, network disruption) **cannot** be enabled until:

1. The Postgres-backed `LeaseManager`, `IdempotencyManager`, and `RunRepository` are implemented and merged.
2. The concurrency testing suite (Criteria 4, 5, and 6) runs reliably in CI against a real Postgres container without relying on sleep-based timing.
3. The `OrchestrationController` is updated to pass database-generated `fencing_tokens` down to the `ExecutionContext`.
4. All 196+ existing dry-run safety regression tests pass against the durable implementations.
