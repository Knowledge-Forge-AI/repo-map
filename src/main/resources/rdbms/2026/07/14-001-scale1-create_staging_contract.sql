--liquibase formatted sql
--changeset slair:2026_07_14-001-scale1-create_staging_contract

CREATE TABLE ingestion_stages (
    stage_id TEXT PRIMARY KEY,
    repository_id BIGINT NOT NULL
        REFERENCES repositories(id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL,
    job_id TEXT,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    execution_mode TEXT NOT NULL CHECK (
        execution_mode IN ('direct', 'coordinator')
    ),
    coordinator_instance_id TEXT,
    singleton_fencing_epoch BIGINT NOT NULL DEFAULT 0
        CHECK (singleton_fencing_epoch >= 0),
    graph_lease_fencing_epoch BIGINT NOT NULL DEFAULT 0
        CHECK (graph_lease_fencing_epoch >= 0),
    source_generation TEXT NOT NULL,
    config_generation TEXT NOT NULL,
    extractor_generation TEXT NOT NULL,
    canonicalizer_generation TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'loading' CHECK (state IN (
        'loading', 'prepared', 'validating', 'validated', 'merging',
        'commit_unknown', 'published', 'failed', 'cancelled', 'abandoned',
        'cleanup_pending', 'cleaned', 'quarantined'
    )),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    expected_family_manifest JSONB NOT NULL DEFAULT (
        '{"schema_version":1,"families":["files","legacy_nodes",'
        '"legacy_evidence","legacy_edges","raw_observations",'
        '"canonical_nodes","canonical_edges","canonical_evidence",'
        '"canonical_node_evidence","canonical_edge_evidence"]}'
    )::jsonb,
    expected_row_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_row_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    family_checksums JSONB NOT NULL DEFAULT '{}'::jsonb,
    normalized_byte_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    validation_status TEXT NOT NULL DEFAULT 'not_started' CHECK (
        validation_status IN ('not_started', 'running', 'passed', 'failed')
    ),
    merge_status TEXT NOT NULL DEFAULT 'not_started' CHECK (
        merge_status IN ('not_started', 'running', 'committed', 'rolled_back', 'unknown')
    ),
    publication_reconciliation_state TEXT NOT NULL DEFAULT 'not_started'
        CHECK (
            publication_reconciliation_state IN (
                'not_started', 'required', 'reconciled', 'conflicting'
            )
        ),
    cleanup_eligibility TEXT NOT NULL DEFAULT 'blocked' CHECK (
        cleanup_eligibility IN (
            'blocked', 'eligible', 'expired', 'cleaned', 'quarantined'
        )
    ),
    cleanup_eligible_at TIMESTAMPTZ,
    CHECK (stage_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CHECK (operation_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CHECK (job_id IS NULL OR job_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CHECK (
        coordinator_instance_id IS NULL
        OR coordinator_instance_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    ),
    CHECK (
        (
            execution_mode = 'direct'
            AND job_id IS NULL
            AND coordinator_instance_id IS NULL
            AND singleton_fencing_epoch = 0
            AND graph_lease_fencing_epoch = 0
        )
        OR (
            execution_mode = 'coordinator'
            AND job_id IS NOT NULL
            AND coordinator_instance_id IS NOT NULL
            AND operation_id = job_id
            AND singleton_fencing_epoch > 0
            AND graph_lease_fencing_epoch > 0
        )
    ),
    CHECK (
        source_generation ~ '^sg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}$'
        AND config_generation ~ '^cg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}$'
        AND extractor_generation ~ '^eg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}$'
        AND canonicalizer_generation ~ '^kg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}$'
    ),
    CHECK (created_at <= updated_at AND expires_at >= created_at),
    CHECK (jsonb_typeof(expected_family_manifest) = 'object'),
    CHECK (jsonb_typeof(expected_row_counts) = 'object'),
    CHECK (jsonb_typeof(observed_row_counts) = 'object'),
    CHECK (jsonb_typeof(family_checksums) = 'object'),
    CHECK (jsonb_typeof(normalized_byte_counts) = 'object'),
    CHECK (
        state <> 'commit_unknown'
        OR (
            merge_status = 'unknown'
            AND publication_reconciliation_state IN ('required', 'conflicting')
        )
    ),
    CHECK (
        state <> 'published'
        OR (
            merge_status = 'committed'
            AND publication_reconciliation_state = 'reconciled'
        )
    ),
    CHECK (state <> 'cleaned' OR cleanup_eligibility = 'cleaned'),
    CHECK (state <> 'quarantined' OR cleanup_eligibility = 'quarantined')
);

CREATE INDEX idx_ingestion_stages_expiry
    ON ingestion_stages(expires_at, state, stage_id);

CREATE INDEX idx_ingestion_stages_owner
    ON ingestion_stages(repository_id, operation_id, attempt, stage_id);

CREATE INDEX idx_ingestion_stages_reconciliation
    ON ingestion_stages(
        publication_reconciliation_state,
        state,
        cleanup_eligibility
    );

CREATE TABLE stage_files (
    stage_id TEXT NOT NULL
        REFERENCES ingestion_stages(stage_id) ON DELETE CASCADE,
    family_ordinal BIGINT NOT NULL CHECK (family_ordinal >= 0),
    path TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'unknown',
    role TEXT NOT NULL DEFAULT 'unknown',
    confidence TEXT NOT NULL,
    content_hash TEXT,
    executable BOOLEAN NOT NULL DEFAULT false,
    generated BOOLEAN NOT NULL DEFAULT false,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (stage_id, family_ordinal),
    CHECK (path <> ''),
    CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'),
    CHECK (role IN (
        'config', 'documentation', 'entrypoint', 'generated', 'script',
        'source', 'test', 'unknown'
    )),
    CHECK (confidence IN ('extracted', 'heuristic', 'manual', 'unknown'))
);

CREATE INDEX idx_stage_files_identity
    ON stage_files(stage_id, path);

CREATE TABLE stage_legacy_nodes (
    stage_id TEXT NOT NULL
        REFERENCES ingestion_stages(stage_id) ON DELETE CASCADE,
    family_ordinal BIGINT NOT NULL CHECK (family_ordinal >= 0),
    stable_key TEXT NOT NULL,
    path TEXT,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (stage_id, family_ordinal),
    CHECK (stable_key <> ''),
    CHECK (
        (start_line IS NULL AND end_line IS NULL)
        OR (
            start_line IS NOT NULL
            AND end_line IS NOT NULL
            AND start_line > 0
            AND end_line >= start_line
        )
    )
);

CREATE INDEX idx_stage_legacy_nodes_identity
    ON stage_legacy_nodes(stage_id, stable_key);

CREATE TABLE stage_legacy_evidence (
    stage_id TEXT NOT NULL
        REFERENCES ingestion_stages(stage_id) ON DELETE CASCADE,
    family_ordinal BIGINT NOT NULL CHECK (family_ordinal >= 0),
    stable_key TEXT NOT NULL,
    path TEXT,
    start_line INTEGER,
    end_line INTEGER,
    excerpt TEXT,
    extractor TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (stage_id, family_ordinal),
    CHECK (stable_key <> ''),
    CHECK (
        (start_line IS NULL AND end_line IS NULL)
        OR (
            start_line IS NOT NULL
            AND end_line IS NOT NULL
            AND start_line > 0
            AND end_line >= start_line
        )
    )
);

CREATE INDEX idx_stage_legacy_evidence_identity
    ON stage_legacy_evidence(stage_id, stable_key);

CREATE TABLE stage_legacy_edges (
    stage_id TEXT NOT NULL
        REFERENCES ingestion_stages(stage_id) ON DELETE CASCADE,
    family_ordinal BIGINT NOT NULL CHECK (family_ordinal >= 0),
    stable_key TEXT NOT NULL,
    source_node_stable_key TEXT NOT NULL,
    target_node_stable_key TEXT NOT NULL,
    edge_kind TEXT NOT NULL,
    confidence TEXT NOT NULL,
    evidence_stable_key TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (stage_id, family_ordinal),
    CHECK (stable_key <> ''),
    CHECK (source_node_stable_key <> ''),
    CHECK (target_node_stable_key <> ''),
    CHECK (evidence_stable_key <> ''),
    CHECK (confidence IN ('extracted', 'heuristic', 'manual', 'unknown'))
);

CREATE INDEX idx_stage_legacy_edges_identity
    ON stage_legacy_edges(stage_id, stable_key);

CREATE INDEX idx_stage_legacy_edges_endpoints
    ON stage_legacy_edges(
        stage_id,
        source_node_stable_key,
        target_node_stable_key
    );

CREATE TABLE stage_raw_observations (
    stage_id TEXT NOT NULL
        REFERENCES ingestion_stages(stage_id) ON DELETE CASCADE,
    source_ordinal BIGINT NOT NULL CHECK (source_ordinal >= 0),
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    path TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    payload_hash TEXT NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (stage_id, source_ordinal)
);

CREATE INDEX idx_stage_raw_observations_source
    ON stage_raw_observations(stage_id, source_ordinal);

CREATE TABLE stage_canonical_nodes (
    stage_id TEXT NOT NULL
        REFERENCES ingestion_stages(stage_id) ON DELETE CASCADE,
    family_ordinal BIGINT NOT NULL CHECK (family_ordinal >= 0),
    graph_key_version INTEGER NOT NULL CHECK (graph_key_version >= 1),
    canonical_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    display_name TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence TEXT NOT NULL,
    conflict BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (stage_id, family_ordinal),
    CHECK (canonical_key <> ''),
    CHECK (kind <> ''),
    CHECK (display_name <> ''),
    CHECK (confidence IN ('manual', 'extracted', 'heuristic', 'unknown'))
);

CREATE INDEX idx_stage_canonical_nodes_identity
    ON stage_canonical_nodes(stage_id, graph_key_version, canonical_key);

CREATE TABLE stage_canonical_edges (
    stage_id TEXT NOT NULL
        REFERENCES ingestion_stages(stage_id) ON DELETE CASCADE,
    family_ordinal BIGINT NOT NULL CHECK (family_ordinal >= 0),
    graph_key_version INTEGER NOT NULL CHECK (graph_key_version >= 1),
    source_canonical_key TEXT NOT NULL,
    edge_kind TEXT NOT NULL,
    target_canonical_key TEXT NOT NULL,
    identity_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    identity_metadata_hash TEXT NOT NULL
        CHECK (identity_metadata_hash ~ '^[0-9a-f]{64}$'),
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence TEXT NOT NULL,
    conflict BOOLEAN NOT NULL DEFAULT false,
    PRIMARY KEY (stage_id, family_ordinal),
    CHECK (source_canonical_key <> ''),
    CHECK (target_canonical_key <> ''),
    CHECK (edge_kind <> ''),
    CHECK (confidence IN ('manual', 'extracted', 'heuristic', 'unknown'))
);

CREATE INDEX idx_stage_canonical_edges_identity
    ON stage_canonical_edges(
        stage_id,
        graph_key_version,
        source_canonical_key,
        edge_kind,
        target_canonical_key,
        identity_metadata_hash
    );

CREATE TABLE stage_canonical_evidence (
    stage_id TEXT NOT NULL
        REFERENCES ingestion_stages(stage_id) ON DELETE CASCADE,
    family_ordinal BIGINT NOT NULL CHECK (family_ordinal >= 0),
    graph_key_version INTEGER NOT NULL CHECK (graph_key_version >= 1),
    evidence_key TEXT NOT NULL,
    raw_observation_ordinal BIGINT NOT NULL CHECK (raw_observation_ordinal >= 0),
    raw_schema_version INTEGER NOT NULL CHECK (raw_schema_version > 0),
    raw_kind TEXT NOT NULL,
    raw_source_id TEXT NOT NULL,
    path TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    extractor TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    confidence TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (stage_id, family_ordinal),
    CHECK (evidence_key <> ''),
    CHECK (
        (start_line IS NULL AND end_line IS NULL)
        OR (
            start_line IS NOT NULL
            AND end_line IS NOT NULL
            AND start_line > 0
            AND end_line >= start_line
        )
    ),
    CHECK (confidence IN ('manual', 'extracted', 'heuristic', 'unknown'))
);

CREATE INDEX idx_stage_canonical_evidence_identity
    ON stage_canonical_evidence(stage_id, graph_key_version, evidence_key);

CREATE INDEX idx_stage_canonical_evidence_raw
    ON stage_canonical_evidence(stage_id, raw_observation_ordinal);

CREATE TABLE stage_canonical_node_evidence (
    stage_id TEXT NOT NULL
        REFERENCES ingestion_stages(stage_id) ON DELETE CASCADE,
    family_ordinal BIGINT NOT NULL CHECK (family_ordinal >= 0),
    graph_key_version INTEGER NOT NULL CHECK (graph_key_version >= 1),
    canonical_key TEXT NOT NULL,
    evidence_key TEXT NOT NULL,
    link_kind TEXT NOT NULL,
    PRIMARY KEY (stage_id, family_ordinal),
    CHECK (canonical_key <> ''),
    CHECK (evidence_key <> ''),
    CHECK (link_kind <> '')
);

CREATE INDEX idx_stage_canonical_node_evidence_lookup
    ON stage_canonical_node_evidence(
        stage_id,
        graph_key_version,
        canonical_key,
        evidence_key
    );

CREATE TABLE stage_canonical_edge_evidence (
    stage_id TEXT NOT NULL
        REFERENCES ingestion_stages(stage_id) ON DELETE CASCADE,
    family_ordinal BIGINT NOT NULL CHECK (family_ordinal >= 0),
    graph_key_version INTEGER NOT NULL CHECK (graph_key_version >= 1),
    source_canonical_key TEXT NOT NULL,
    edge_kind TEXT NOT NULL,
    target_canonical_key TEXT NOT NULL,
    identity_metadata_hash TEXT NOT NULL
        CHECK (identity_metadata_hash ~ '^[0-9a-f]{64}$'),
    evidence_key TEXT NOT NULL,
    link_kind TEXT NOT NULL,
    PRIMARY KEY (stage_id, family_ordinal),
    CHECK (source_canonical_key <> ''),
    CHECK (edge_kind <> ''),
    CHECK (target_canonical_key <> ''),
    CHECK (evidence_key <> ''),
    CHECK (link_kind <> '')
);

CREATE INDEX idx_stage_canonical_edge_evidence_lookup
    ON stage_canonical_edge_evidence(
        stage_id,
        graph_key_version,
        source_canonical_key,
        edge_kind,
        target_canonical_key,
        identity_metadata_hash,
        evidence_key
    );

CREATE TABLE graph_publication_authority (
    repository_id BIGINT PRIMARY KEY
        REFERENCES repositories(id) ON DELETE CASCADE,
    singleton_fencing_epoch BIGINT NOT NULL CHECK (singleton_fencing_epoch > 0),
    graph_lease_fencing_epoch BIGINT NOT NULL CHECK (graph_lease_fencing_epoch > 0),
    job_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK (attempt > 0),
    coordinator_instance_id TEXT NOT NULL,
    source_generation TEXT NOT NULL,
    config_generation TEXT NOT NULL,
    extractor_generation TEXT NOT NULL,
    canonicalizer_generation TEXT NOT NULL,
    last_stage_id TEXT NOT NULL,
    last_run_id BIGINT REFERENCES runs(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (job_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CHECK (
        coordinator_instance_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
    ),
    CHECK (last_stage_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CHECK (
        source_generation ~ '^sg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}$'
        AND config_generation ~ '^cg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}$'
        AND extractor_generation ~ '^eg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}$'
        AND canonicalizer_generation ~ '^kg1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}$'
    ),
    UNIQUE (job_id, attempt)
);

CREATE INDEX idx_graph_publication_authority_fencing
    ON graph_publication_authority(
        singleton_fencing_epoch,
        graph_lease_fencing_epoch,
        repository_id
    );

COMMENT ON TABLE ingestion_stages IS
    'SCALE1 durable regular attempt-scoped staging; never publication';
COMMENT ON TABLE graph_publication_authority IS
    'SCALE1 monotonic graph-local projection of coordinator publication authority';

--rollback DO $scale1_rollback$
--rollback BEGIN
--rollback IF EXISTS (
--rollback     SELECT 1 FROM ingestion_stages
--rollback     WHERE state <> 'cleaned'
--rollback        OR publication_reconciliation_state IN ('required', 'conflicting')
--rollback ) THEN
--rollback     RAISE EXCEPTION 'SCALE1 staging rollback refused while unresolved stages exist';
--rollback END IF;
--rollback END
--rollback $scale1_rollback$;
--rollback DROP INDEX idx_graph_publication_authority_fencing;
--rollback DROP TABLE graph_publication_authority;
--rollback DROP INDEX idx_stage_canonical_edge_evidence_lookup;
--rollback DROP TABLE stage_canonical_edge_evidence;
--rollback DROP INDEX idx_stage_canonical_node_evidence_lookup;
--rollback DROP TABLE stage_canonical_node_evidence;
--rollback DROP INDEX idx_stage_canonical_evidence_raw;
--rollback DROP INDEX idx_stage_canonical_evidence_identity;
--rollback DROP TABLE stage_canonical_evidence;
--rollback DROP INDEX idx_stage_canonical_edges_identity;
--rollback DROP TABLE stage_canonical_edges;
--rollback DROP INDEX idx_stage_canonical_nodes_identity;
--rollback DROP TABLE stage_canonical_nodes;
--rollback DROP INDEX idx_stage_raw_observations_source;
--rollback DROP TABLE stage_raw_observations;
--rollback DROP INDEX idx_stage_legacy_edges_endpoints;
--rollback DROP INDEX idx_stage_legacy_edges_identity;
--rollback DROP TABLE stage_legacy_edges;
--rollback DROP INDEX idx_stage_legacy_evidence_identity;
--rollback DROP TABLE stage_legacy_evidence;
--rollback DROP INDEX idx_stage_legacy_nodes_identity;
--rollback DROP TABLE stage_legacy_nodes;
--rollback DROP INDEX idx_stage_files_identity;
--rollback DROP TABLE stage_files;
--rollback DROP INDEX idx_ingestion_stages_reconciliation;
--rollback DROP INDEX idx_ingestion_stages_owner;
--rollback DROP INDEX idx_ingestion_stages_expiry;
--rollback DROP TABLE ingestion_stages;
