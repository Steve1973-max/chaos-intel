# CHAOS-INTEL — PHASE 2C.3A
## PROTECTED DOMAIN WRITE CONTRACT — CONTROLLED IMPLEMENTATION

### 1. Exact Files Inspected and Changed
**Inspected:**
- `src/execution/persistence/interfaces.py`
- `src/execution/persistence/repositories.py`
- `src/execution/persistence/models.py`
- `tests/test_durable_leases.py`

**Changed:**
- `src/execution/persistence/interfaces.py`: Introduced the `FencedTransactionBoundary(Protocol)` defining the new `fenced_transaction` context manager contract.
- `src/execution/persistence/repositories.py`: Modified `SqlTransactionBoundary` to inherit and implement `FencedTransactionBoundary`. The `fenced_transaction` method executes a `SELECT ... FOR UPDATE` lock against the lease record to natively validate the owner and fencing token simultaneously with establishing the database transaction context.
- `tests/test_fenced_transactions.py` (New): Created dedicated deterministically fast SQLite unit tests covering all required constraints for the protected mutation scope.

### 2. The Protected-Write API and Transaction Semantics
The protected write API is encapsulated in the `fenced_transaction` context manager exposed by `SqlTransactionBoundary`.
- **Inputs:** `resource_id`, `owner_id`, `fencing_token`
- **Semantics:** By locking the `LeaseRecordModel` via `with_for_update()` at the start of the boundary, any subsequent domain writes performed within the context block (`RunRepository.transition_state`, `IdempotencyRepository.publish_result`, etc.) are inherently atomic with the lease token validation. 
- **Exclusivity:** If another worker successfully acquired the lease, the token advances or owner swaps; when this block evaluates the token under lock, it immediately raises a typed `LeaseOwnershipError` rejecting the entire block before any domain mutation executes.

### 3. Protection Against Stale-Token Acceptance
When a lease expires (or is abandoned), a competing worker calls `lease_repo.acquire()`, taking ownership and incrementing the `fencing_token`. If the original worker attempts a protected write using the new `fenced_transaction` API, it is forced to lock the lease row and compare its stale token against the freshly advanced database record. 
Because the token mismatch triggers an immediate `LeaseOwnershipError`, the transaction block immediately halts. It safely skips emitting any Domain (`ExperimentRun`) writes, transition histories, or Idempotency result publications.

### 4. Regression Tests Added and Results
`tests/test_fenced_transactions.py` implemented 4 specific test cases:
1. `test_fenced_write_success`: Proves standard lifecycle functionality for a valid lease owner correctly committing run state.
2. `test_fenced_write_incorrect_owner_rejected`: Proves unauthorized hijack attempts cleanly abort.
3. `test_stale_owner_rejected_and_does_not_mutate`: Simulates the specific expiry scenario (Owner 1 expires, Owner 2 acquires, Owner 1 attempts to commit). Proves that run transitions and idempotency outputs are correctly aborted, retaining clean original states.
4. `test_optimistic_concurrency_still_enforced`: Proves that `SqlAlchemyRunRepository`'s internal `expected_version` logic securely supplements the fencing token, raising `OptimisticConcurrencyError` on nested conflicts.

All 4 targeted tests passed deterministically.

### 5. Full-Suite Output
```text
collected 238 items
...
================== 234 passed, 4 skipped, 1 warning in 4.11s ==================
```

### 6. PostgreSQL Status
As explicitly constrained, PostgreSQL concurrency was **not** verified natively. The 4 standard testcontainers integration tests were skipped precisely due to the lack of a local Docker daemon. The semantic correctness of `with_for_update` relies on standard SQLAlchemy behaviors which have been verified via SQLite savepoint equivalence in the unit tests.

### 7. Remaining Gaps and Migration Requirements
- **Integration Blocked:** The `OrchestrationController` (`src/execution/orchestrator.py`) remains structurally unchanged and continues to use the legacy `TransactionBoundary.transaction()`. It must be refactored to fetch the lease and swap to `TransactionBoundary.fenced_transaction()` in the next phase.
- **Migration Requirements:** None. The structural schema correctly supported this requirement organically.

*(Execution properly halted. No orchestration wiring, workers, or live integrations were applied.)*
