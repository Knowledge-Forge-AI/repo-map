--liquibase formatted sql
--changeset repomap:2026_07_13-001-async2-create-control-schema

CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    job_kind TEXT NOT NULL CHECK (job_kind = 'refresh_graph'),
    graph_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    requester TEXT NOT NULL,
    idempotency_digest TEXT NOT NULL CHECK (length(idempotency_digest) = 64),
    request_fingerprint TEXT NOT NULL CHECK (length(request_fingerprint) = 64),
    priority_class TEXT NOT NULL CHECK (priority_class IN ('manual', 'automatic')),
    priority_value SMALLINT NOT NULL CHECK (priority_value BETWEEN 0 AND 100),
    source_generation TEXT NOT NULL,
    config_generation TEXT NOT NULL,
    extractor_generation TEXT NOT NULL,
    canonicalizer_generation TEXT NOT NULL,
    operation_options JSONB NOT NULL DEFAULT '{}'::jsonb,
    state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN (
        'queued', 'claimed', 'starting', 'running', 'cancel_requested',
        'cancelling', 'succeeded', 'failed', 'cancelled', 'superseded',
        'quarantined', 'reconciliation_required'
    )),
    publication_state TEXT NOT NULL DEFAULT 'not_started' CHECK (
        publication_state IN (
            'not_applicable', 'not_started', 'prepared',
            'transaction_started', 'committed', 'rolled_back',
            'commit_unknown'
        )
    ),
    CHECK (state <> 'succeeded' OR publication_state = 'committed'),
    CHECK (
        state NOT IN ('failed', 'cancelled', 'superseded')
        OR publication_state IN ('not_started', 'prepared', 'rolled_back')
    ),
    CHECK (state <> 'queued' OR publication_state <> 'commit_unknown'),
    current_attempt INTEGER NOT NULL DEFAULT 0 CHECK (current_attempt >= 0),
    next_eligible_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    phase TEXT NOT NULL DEFAULT 'waiting' CHECK (phase IN (
        'waiting', 'starting', 'preflight', 'discovery', 'extraction',
        'canonicalization', 'storage_prepare', 'storage_publish',
        'verification', 'cleanup', 'complete'
    )),
    progress_completed BIGINT NOT NULL DEFAULT 0 CHECK (progress_completed >= 0),
    progress_total BIGINT CHECK (
        progress_total IS NULL OR progress_total >= progress_completed
    ),
    error_category TEXT,
    cancel_requested_at TIMESTAMPTZ,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    replacement_job_id TEXT REFERENCES jobs(job_id),
    parent_job_id TEXT REFERENCES jobs(job_id),
    UNIQUE (requester, job_kind, graph_id, idempotency_digest)
);

CREATE TABLE coordinator_instances (
    singleton_scope TEXT PRIMARY KEY CHECK (singleton_scope = 'control'),
    instance_id TEXT NOT NULL,
    fencing_epoch BIGINT NOT NULL CHECK (fencing_epoch > 0),
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    stopped_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('active', 'stopped')),
    UNIQUE (instance_id, fencing_epoch)
);

CREATE TABLE job_attempts (
    job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE RESTRICT,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    coordinator_instance_id TEXT NOT NULL,
    fencing_epoch BIGINT NOT NULL CHECK (fencing_epoch > 0),
    is_current BOOLEAN NOT NULL DEFAULT true,
    worker_identity TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    source_generation TEXT NOT NULL,
    config_generation TEXT NOT NULL,
    extractor_generation TEXT NOT NULL,
    canonicalizer_generation TEXT NOT NULL,
    result_category TEXT,
    publication_state TEXT NOT NULL DEFAULT 'not_started' CHECK (
        publication_state IN (
            'not_applicable', 'not_started', 'prepared',
            'transaction_started', 'committed', 'rolled_back',
            'commit_unknown'
        )
    ),
    run_identity TEXT,
    diagnostic_summary TEXT,
    PRIMARY KEY (job_id, attempt)
);

CREATE UNIQUE INDEX uq_job_attempts_current
    ON job_attempts(job_id) WHERE is_current;

CREATE TABLE graph_leases (
    graph_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    coordinator_instance_id TEXT NOT NULL,
    fencing_epoch BIGINT NOT NULL CHECK (fencing_epoch > 0),
    worker_identity TEXT,
    acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    UNIQUE (job_id, attempt),
    FOREIGN KEY (job_id, attempt)
        REFERENCES job_attempts(job_id, attempt) ON DELETE RESTRICT
);

CREATE TABLE coalescing_state (
    graph_id TEXT NOT NULL,
    job_kind_family TEXT NOT NULL CHECK (job_kind_family = 'refresh_graph'),
    desired_source_generation TEXT NOT NULL,
    desired_config_generation TEXT NOT NULL,
    desired_extractor_generation TEXT NOT NULL,
    desired_canonicalizer_generation TEXT NOT NULL,
    dirty BOOLEAN NOT NULL DEFAULT false,
    paused BOOLEAN NOT NULL DEFAULT false,
    reason_categories TEXT[] NOT NULL DEFAULT '{}',
    queued_job_id TEXT REFERENCES jobs(job_id),
    running_job_id TEXT REFERENCES jobs(job_id),
    next_reconcile_at TIMESTAMPTZ,
    last_hint_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (graph_id, job_kind_family)
);

CREATE TABLE synthetic_publication_markers (
    job_id TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    graph_id TEXT NOT NULL,
    run_identity TEXT NOT NULL,
    source_generation TEXT NOT NULL,
    config_generation TEXT NOT NULL,
    extractor_generation TEXT NOT NULL,
    canonicalizer_generation TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('committed', 'conflicting')),
    published_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (job_id, attempt),
    UNIQUE (graph_id, run_identity),
    FOREIGN KEY (job_id, attempt)
        REFERENCES job_attempts(job_id, attempt) ON DELETE RESTRICT
);

CREATE INDEX idx_jobs_claim
    ON jobs(state, next_eligible_at, priority_value DESC, submitted_at, job_id);
CREATE INDEX idx_jobs_graph_state ON jobs(graph_id, state);
CREATE INDEX idx_jobs_finished ON jobs(finished_at, job_id);
CREATE INDEX idx_job_attempts_finished ON job_attempts(finished_at, job_id, attempt);
CREATE INDEX idx_graph_leases_expiry ON graph_leases(expires_at, graph_id);
CREATE INDEX idx_graph_leases_owner
    ON graph_leases(coordinator_instance_id, fencing_epoch);
CREATE INDEX idx_coalescing_reconcile
    ON coalescing_state(paused, dirty, next_reconcile_at);

COMMENT ON TABLE jobs IS 'repomap-control-schema:1';

--rollback DROP TABLE synthetic_publication_markers;
--rollback DROP TABLE coalescing_state;
--rollback DROP TABLE graph_leases;
--rollback DROP TABLE job_attempts;
--rollback DROP TABLE coordinator_instances;
--rollback DROP TABLE jobs;
