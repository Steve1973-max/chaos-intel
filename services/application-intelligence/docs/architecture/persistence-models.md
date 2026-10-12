# CHAOS-INTEL: Persistence Models & Interfaces

## 1. Model Responsibilities

The newly introduced `src.execution.persistence.models` module isolates SQLAlchemy ORM definitions from public API and Pydantic validation schemas.
- **ExperimentRunModel:** The durable system of record for the `ExperimentRun`. Tracks state, version (for optimistic concurrency), and metadata.
- **RunTransitionHistoryModel:** An immutable ledger of all state changes for a run, mapping `previous_state` -> `new_state` and linking to an `expected_version` and `new_version`.
- **IdempotencyRecordModel:** Handles atomic workflow reservations. Uniquely keyed on application, operation, and the digest of an idempotency key. Maps canonical request fingerprints to detect divergence.
- **LeaseRecordModel:** Manages distributed mutual exclusion per resource, defining the current owner, an expiry timestamp, and a monotonically incrementing `fencing_token`.
- **AuditEventModel:** Captures append-only structured audit logs mapping correlation and causation IDs, completely independent of live memory, and stores redacted metadata JSON payloads.
- **OutboxEventModel:** Facilitates the Transactional Outbox pattern. Stores events generated during a transaction that need to be published to external buses *after* successful commit.

## 2. Key Constraints and Indexes

- **Version Increment Constraint:** `RunTransitionHistoryModel` enforces at the DB level that `new_version > expected_version`.
- **Idempotency Scope:** `IdempotencyRecordModel` applies a `UniqueConstraint` on `(application_id, operation_scope, idempotency_key_digest)` preventing parallel creation of reservations for the same requested intent.
- **Lease Integrity:** `LeaseRecordModel` enforces uniqueness on `resource_id` (since only one active lease can exist per resource at a given time) and a check constraint ensuring `fencing_token > 0`. Database fencing alone cannot protect external systems that do not enforce fencing or equivalent idempotency.
- **Foreign Keys:** `RunTransitionHistoryModel` maintains a strict foreign-key relationship back to `ExperimentRunModel`.

## 3. Transaction Requirements

The models natively support transactional atomicity. Crucially:
- Updating an `ExperimentRunModel` state AND inserting a corresponding `RunTransitionHistoryModel` MUST occur in the same explicit database transaction.
- Inserting an `AuditEventModel` MUST occur in the same explicit transaction as the lifecycle state change it describes.
- `OutboxEventModel` rows MUST be inserted in the exact same transaction committing the actual resource mutations. Consumers of these outbox events are expected to be idempotent because outbox delivery can be repeated. 
- The interfaces module defines a `TransactionBoundary` protocol featuring a context manager to explicitly enforce this requirement across concrete repositories.

## 4. Security and Redaction

- `IdempotencyRecordModel` explicitly drops raw idempotency keys from persistence. Instead, it stores `idempotency_key_digest`, protecting sensitive keys from unauthorized reverse-engineering via DB dumps.
- `AuditEventModel` expects the application layer to aggressively redact metadata before passing it to the repository layer, enforcing a column named `redacted_metadata`.
- Pydantic models with sensitive internal attributes are strictly blocked from being accidentally cast to SQLAlchemy JSON maps; careful data-transfer-objects (DTOs) map into these SQL models.

## 5. Unimplemented Behavior

- **Database Connections:** No engine initialization, session lifecycle management, or asyncpg drivers exist yet.
- **Migrations:** Alembic is entirely unimplemented; no tables exist in any live/shared database yet.
- **Concrete Implementations:** The `interfaces.py` defines Protocols (like `RunRepository`), but actual concrete repository classes executing `SELECT ... FOR UPDATE` or `INSERT ... ON CONFLICT` logic do not yet exist.
- **Orchestrator Integration:** `OrchestrationController` continues to use its process-local memory bounds.

## 6. Required Deliverables for Step 12C.2B

Step 12C.2B must deliver:
1. Alembic environment setup and the initial migration scripts defining the DDL schema.
2. Concrete repository implementations conforming to the defined Protocols.
3. Actual test coverage executing repository logic against an ephemeral integration database (e.g., SQLite in-memory or a Postgres Testcontainer).
