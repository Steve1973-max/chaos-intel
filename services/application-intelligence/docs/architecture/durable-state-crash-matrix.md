# CHAOS-INTEL: Durable State Crash Matrix

This matrix categorizes crash points across the orchestration pipeline, assessing what state is durable, what a recovering worker observes, and the mandatory recovery action.

## Crash Point Matrix

| Execution Phase / Crash Point | Durable State (Pre-Crash) | Observed State on Recovery | Safe to Retry? | Reconciliation Required | Invariants to Maintain |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Run Creation** | None. (Orchestrator hasn't persisted the run yet). | Request missing / dropped. | **Yes**. (Client can retry safely). | None. | No orphans created. |
| **2. Idempotency Reservation** | `idempotency_record` exists as `in_progress`. | `in_progress` idempotency key without an active run. | **Yes**. | Yes (stale record cleanup). | Release/timeout stale idempotency locks. |
| **3. Lease Acquisition** | `run` created, `lease` acquired. | `run` is `CREATED`, `lease` is expired or actively held by dead worker. | **Yes**. | Yes (lease expiration). | Fencing tokens incremented on lease re-acquisition. |
| **4. Preflight Completion** | `run` is `CREATED`. | Preflight wasn't committed to DB. | **Yes**. | None. | Must rerun preflight from scratch. |
| **5. Authorization** | Preflight committed, state is `AUTHORIZATION_PENDING`. | `AUTHORIZATION_PENDING`. | **Yes**. | None. | `authorize_run` must be re-executed completely. |
| **6. Dispatch Intent (Adapter Resolved)**| State is `AUTHORIZED`, plan generated. | `AUTHORIZED`. No execution recorded. | **Yes**. | None. | Plan must be dynamically regenerated to ensure targets haven't shifted. |
| **7. Operation Execution (Dry-Run)** | State is `AUTHORIZED`. Adapter executing. | `AUTHORIZED`. Adapter execution lost in memory. | **Yes**. | None. | Dry-runs are inherently safe to retry. |
| **8. Operation Execution (Live)** | State is `RUNNING` or `AUTHORIZED`. Adapter executing. | `RUNNING` / `OUTCOME_UNKNOWN`. | **NO**. | **Manual Review Required**. | NEVER auto-replay an uncertain infrastructure mutation. |
| **9. Operation Result Returned** | External mutation finished, but not committed to DB. | `OUTCOME_UNKNOWN`. | **NO**. | **Independent Evidence Validation**. | Worker must poll infrastructure/adapter to ascertain result. |
| **10. Audit Append & Run Update** | State transaction partially completed. | Database rolls back the transaction atomically. Falls back to Step 8/9. | **Depends**. | See Step 8/9. | Audit logs and state transitions MUST commit atomically. |
| **11. Idempotency Result Publication**| Run is `COMPLETED`, audit logged. Idempotency not updated. | `COMPLETED` run exists. Idempotency still `in_progress`. | **Safe to Re-publish**. | Internal system sweep to sync idempotency state with run state. | Client requesting status must fetch from Run ID if idempotency fails. |

## Explicit Treatment of Uncertain Outcomes

An uncertain outcome occurs when a worker initiates a real-world side effect (e.g., shutting down a pod) but crashes before recording the adapter's `ExecutionResult` to the database.

1. **State:** The lease expires, and a recovery worker assumes control. The run state is marked `RUNNING` or `OUTCOME_UNKNOWN`.
2. **Action:** The recovery worker **must not** replay the operation.
3. **Reconciliation:** The worker transitions the run to `RECOVERY_CHECK` and uses the adapter's `verify_recovery()` or `observe()` capabilities to probe the environment. If the state cannot be deterministically mapped to the expected output, the run is flagged `MANUAL_REVIEW_REQUIRED` and halted.
