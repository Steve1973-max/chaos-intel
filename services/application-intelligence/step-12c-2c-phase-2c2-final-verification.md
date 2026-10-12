# CHAOS-INTEL — PHASE 2C.2 FINAL VERIFICATION
## WRITE-PATH PROTECTION AUDIT

### 1. Files Inspected and Modified
**Inspected:**
- `src/execution/persistence/repositories.py` (`SqlAlchemyLeaseRepository`, `SqlAlchemyRunRepository`, `SqlAlchemyIdempotencyRepository`)
- `src/execution/persistence/models.py` (`LeaseRecordModel`, `ExperimentRunModel`)

**Modified:**
- `tests/test_durable_leases.py`: Added the strictly requested focused regression test (`test_7_stale_owner_rejected_from_lease_writes`) which demonstrates that a stale owner attempting a protected write against the lease repository is correctly rejected.

### 2. Tracing the Fencing Token
- **Acquisition:** A lease is initially acquired via `SqlAlchemyLeaseRepository.acquire()`. If a new row is created, the `fencing_token` is initialized to 1. If an expired lease is taken over, `fencing_token` is monotonically incremented `+= 1`.
- **Persistence:** The `fencing_token` is persisted durably to the database via `LeaseRecordModel`.
- **Renewal/Release:** Both `repo.renew` and `repo.release` expect the caller to present the correct `fencing_token`. The token is strictly matched against the database before committing the renewal or release.
- **Resource Association:** The token is tied exclusively to the unique `resource_id`.

### 3. Actual Protected Database Writes & Missing Contracts
A critical audit of the current persistence implementations reveals a major contract gap regarding "domain writes":

- **Lease Writes (Protected):** Write APIs acting on the lease itself (`renew`, `release`) **do** validate the current fencing token atomically within the same transaction. If Owner 1 attempts to renew a lease with token 1 after Owner 2 acquired token 2, the write is safely blocked with a `LeaseOwnershipError`.
- **Domain Writes / Run State Transitions (UNPROTECTED):** There is currently **no protected write API** for domain events (e.g. `ExperimentRun` state transitions). `SqlAlchemyRunRepository.transition_state` enforces optimistic concurrency by expecting a specific `expected_version`, but it **does not accept or validate a fencing token**.
- **Audit/Idempotency (UNPROTECTED):** Similarly, the `SqlAlchemyIdempotencyRepository.publish_result()` only checks that `owner_id` matches the reservation owner, ignoring fencing tokens entirely.

**Conclusion:** Durable lease fencing currently only protects *itself*. It does **not** protect actual domain database writes against stale workers. A stale worker whose lease expired can still successfully write an `ExperimentRun` state transition if the run's optimistic version happens to match.

### 4. Test Results
- **SQLite Regression Test (`test_7_stale_owner_rejected_from_lease_writes`)**: Passed successfully. It executes the precise scenario requested against a native lease write (a renewal), proving that Owner 1's token is obsolete and the write is rejected while Owner 2's state remains intact.
- **Full Test Suite:**
  ```text
  collected 234 items
  ...
  ================== 230 passed, 4 skipped, 1 warning in 4.16s ==================
  ```
- **PostgreSQL Distinction:** The 4 skips explicitly correspond to the testcontainers-dependent PostgreSQL persistence tests. PostgreSQL concurrency has **not** been verified, as Docker was unavailable to run those tests locally. All successful assertions ran strictly against the SQLite dialect.

### 5. Remaining Blockers
To genuinely protect domain writes against stale workers, the following gaps must be closed in future phases:
1. **Contract Expansion:** `RunRepository`, `IdempotencyRepository`, and `AuditRepository` interfaces must be expanded to accept a `fencing_token` argument during write operations.
2. **Atomic Verification:** The `SqlTransactionBoundary` (or the repositories themselves) must be modified to read and validate the `LeaseRecordModel.fencing_token` atomically within the same transaction block (`with_for_update`) executing the domain writes.

*(Execution halted as requested; no orchestration integrations or outbox systems were invented or activated).*
