-- Initial PostgreSQL schema initialization for CHAOS-INTEL Platform
CREATE TABLE IF NOT EXISTS applications (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    source_type VARCHAR(64) NOT NULL DEFAULT 'directory',
    source_location TEXT NOT NULL,
    file_hash VARCHAR(64),
    status VARCHAR(32) NOT NULL DEFAULT 'registered' CONSTRAINT check_valid_app_status CHECK (status IN ('registered', 'analyzing', 'analyzed', 'failed')),
    metadata_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_app_name ON applications(name);

CREATE TABLE IF NOT EXISTS background_jobs (
    id VARCHAR(64) PRIMARY KEY,
    task_name VARCHAR(128) NOT NULL,
    correlation_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued' CONSTRAINT check_valid_job_status CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'dead_letter')),
    priority INT NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB,
    error JSONB,
    retry_count INT NOT NULL DEFAULT 0,
    max_retries INT NOT NULL DEFAULT 3,
    timeout_seconds INT NOT NULL DEFAULT 300,
    worker_id VARCHAR(128),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_job_status_priority ON background_jobs(status, priority);
CREATE INDEX IF NOT EXISTS idx_jobs_correlation_id ON background_jobs(correlation_id);

-- Execution Persistence & Reliability Tables
CREATE TABLE IF NOT EXISTS experiment_runs (
    id VARCHAR(36) PRIMARY KEY,
    application_id VARCHAR NOT NULL,
    experiment_id VARCHAR NOT NULL,
    safety_decision_id VARCHAR NOT NULL,
    approval_id VARCHAR,
    state VARCHAR NOT NULL,
    version INT NOT NULL DEFAULT 1 CONSTRAINT check_version_positive CHECK (version > 0),
    correlation_id VARCHAR NOT NULL,
    metadata_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_experiment_runs_app ON experiment_runs(application_id);
CREATE INDEX IF NOT EXISTS idx_experiment_runs_exp ON experiment_runs(experiment_id);

CREATE TABLE IF NOT EXISTS run_transitions (
    id VARCHAR(36) PRIMARY KEY,
    run_id VARCHAR(36) NOT NULL REFERENCES experiment_runs(id),
    previous_state VARCHAR,
    new_state VARCHAR NOT NULL,
    expected_version INT NOT NULL,
    new_version INT NOT NULL,
    actor VARCHAR NOT NULL,
    reason VARCHAR,
    correlation_id VARCHAR,
    causation_id VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_run_transition_version UNIQUE (run_id, new_version),
    CONSTRAINT check_version_increment CHECK (new_version > expected_version)
);

CREATE INDEX IF NOT EXISTS idx_run_transitions_run_id ON run_transitions(run_id);

CREATE TABLE IF NOT EXISTS idempotency_records (
    id VARCHAR(36) PRIMARY KEY,
    application_id VARCHAR NOT NULL,
    operation_scope VARCHAR NOT NULL,
    idempotency_key_digest VARCHAR NOT NULL,
    fingerprint VARCHAR NOT NULL,
    owner_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'in_progress' CONSTRAINT check_valid_idempotency_status CHECK (status IN ('in_progress', 'completed')),
    terminal_result JSONB,
    uncertain_outcome INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT uq_idempotency_scope UNIQUE (application_id, operation_scope, idempotency_key_digest)
);

CREATE INDEX IF NOT EXISTS idx_idempotency_lookup ON idempotency_records(application_id, operation_scope, idempotency_key_digest);

CREATE TABLE IF NOT EXISTS leases (
    id VARCHAR(36) PRIMARY KEY,
    resource_id VARCHAR NOT NULL UNIQUE,
    owner_id VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'active' CONSTRAINT check_valid_lease_status CHECK (status IN ('active', 'released', 'expired')),
    version INT NOT NULL DEFAULT 1 CONSTRAINT check_lease_version_positive CHECK (version > 0),
    fencing_token INT NOT NULL DEFAULT 1 CONSTRAINT check_fencing_token_positive CHECK (fencing_token > 0),
    acquired_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    released_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_leases_resource_id ON leases(resource_id);

CREATE TABLE IF NOT EXISTS audit_events (
    id VARCHAR(36) PRIMARY KEY,
    run_id VARCHAR REFERENCES experiment_runs(id),
    application_id VARCHAR,
    experiment_id VARCHAR,
    event_type VARCHAR NOT NULL,
    outcome VARCHAR NOT NULL,
    actor VARCHAR NOT NULL,
    previous_state VARCHAR,
    current_state VARCHAR,
    correlation_id VARCHAR,
    causation_id VARCHAR,
    redacted_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_events(run_id);

CREATE TABLE IF NOT EXISTS transactional_outbox (
    id VARCHAR(36) PRIMARY KEY,
    event_type VARCHAR NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    delivered_at TIMESTAMP WITH TIME ZONE,
    delivery_status VARCHAR NOT NULL DEFAULT 'pending' CONSTRAINT check_valid_delivery_status CHECK (delivery_status IN ('pending', 'delivered', 'failed')),
    retry_count INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_outbox_status ON transactional_outbox(delivery_status);

