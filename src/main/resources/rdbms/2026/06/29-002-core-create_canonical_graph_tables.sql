--liquibase formatted sql
--changeset slair:2026_06_29-002-core-create_canonical_graph_tables

CREATE TABLE canonical_nodes (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL
        REFERENCES repositories(id) ON DELETE CASCADE,
    graph_key_version INTEGER NOT NULL,
    canonical_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    display_name TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence TEXT NOT NULL,
    conflict BOOLEAN NOT NULL DEFAULT false,
    first_seen_run_id BIGINT REFERENCES runs(id) ON DELETE SET NULL,
    last_seen_run_id BIGINT REFERENCES runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repository_id, graph_key_version, canonical_key),
    CHECK (graph_key_version >= 1),
    CHECK (canonical_key <> ''),
    CHECK (kind <> ''),
    CHECK (display_name <> ''),
    CHECK (confidence IN ('manual', 'extracted', 'heuristic', 'unknown'))
);

CREATE INDEX idx_canonical_nodes_kind
    ON canonical_nodes(repository_id, graph_key_version, kind);

CREATE INDEX idx_canonical_nodes_last_seen_run
    ON canonical_nodes(last_seen_run_id);

CREATE TABLE canonical_edges (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL
        REFERENCES repositories(id) ON DELETE CASCADE,
    graph_key_version INTEGER NOT NULL,
    source_canonical_key TEXT NOT NULL,
    edge_kind TEXT NOT NULL,
    target_canonical_key TEXT NOT NULL,
    identity_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    identity_metadata_hash TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence TEXT NOT NULL,
    conflict BOOLEAN NOT NULL DEFAULT false,
    first_seen_run_id BIGINT REFERENCES runs(id) ON DELETE SET NULL,
    last_seen_run_id BIGINT REFERENCES runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (
        repository_id,
        graph_key_version,
        source_canonical_key,
        edge_kind,
        target_canonical_key,
        identity_metadata_hash
    ),
    FOREIGN KEY (repository_id, graph_key_version, source_canonical_key)
        REFERENCES canonical_nodes(repository_id, graph_key_version, canonical_key)
        ON DELETE CASCADE,
    FOREIGN KEY (repository_id, graph_key_version, target_canonical_key)
        REFERENCES canonical_nodes(repository_id, graph_key_version, canonical_key)
        ON DELETE CASCADE,
    CHECK (graph_key_version >= 1),
    CHECK (source_canonical_key <> ''),
    CHECK (target_canonical_key <> ''),
    CHECK (identity_metadata_hash ~ '^[0-9a-f]{64}$'),
    CHECK (
        edge_kind IN (
            'defines',
            'executes',
            'sources',
            'reads_env',
            'writes_env',
            'mutates_host',
            'imports',
            'exposes_script',
            'links_to',
            'references',
            'styles',
            'depends_on',
            'wraps',
            'tests'
        )
    ),
    CHECK (confidence IN ('manual', 'extracted', 'heuristic', 'unknown'))
);

CREATE INDEX idx_canonical_edges_source
    ON canonical_edges(repository_id, graph_key_version, source_canonical_key);

CREATE INDEX idx_canonical_edges_target
    ON canonical_edges(repository_id, graph_key_version, target_canonical_key);

CREATE INDEX idx_canonical_edges_kind
    ON canonical_edges(repository_id, graph_key_version, edge_kind);

CREATE TABLE canonical_evidence (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL
        REFERENCES repositories(id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL
        REFERENCES runs(id) ON DELETE CASCADE,
    graph_key_version INTEGER NOT NULL,
    raw_observation_id BIGINT
        REFERENCES raw_observations(id) ON DELETE SET NULL,
    evidence_key TEXT NOT NULL,
    raw_observation_ordinal INTEGER NOT NULL,
    raw_schema_version INTEGER NOT NULL,
    raw_kind TEXT NOT NULL,
    raw_source_id TEXT NOT NULL,
    path TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    extractor TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    confidence TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, graph_key_version, evidence_key),
    CHECK (graph_key_version >= 1),
    CHECK (evidence_key <> ''),
    CHECK (raw_observation_ordinal >= 0),
    CHECK (raw_schema_version > 0),
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

CREATE INDEX idx_canonical_evidence_raw_observation
    ON canonical_evidence(raw_observation_id);

CREATE INDEX idx_canonical_evidence_path
    ON canonical_evidence(repository_id, path);

CREATE TABLE canonical_node_evidence (
    canonical_node_id BIGINT NOT NULL
        REFERENCES canonical_nodes(id) ON DELETE CASCADE,
    canonical_evidence_id BIGINT NOT NULL
        REFERENCES canonical_evidence(id) ON DELETE CASCADE,
    link_kind TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (canonical_node_id, canonical_evidence_id, link_kind),
    CHECK (link_kind <> '')
);

CREATE INDEX idx_canonical_node_evidence_evidence
    ON canonical_node_evidence(canonical_evidence_id);

CREATE TABLE canonical_edge_evidence (
    canonical_edge_id BIGINT NOT NULL
        REFERENCES canonical_edges(id) ON DELETE CASCADE,
    canonical_evidence_id BIGINT NOT NULL
        REFERENCES canonical_evidence(id) ON DELETE CASCADE,
    link_kind TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (canonical_edge_id, canonical_evidence_id, link_kind),
    CHECK (link_kind <> '')
);

CREATE INDEX idx_canonical_edge_evidence_evidence
    ON canonical_edge_evidence(canonical_evidence_id);

--rollback DROP INDEX idx_canonical_edge_evidence_evidence;
--rollback DROP TABLE canonical_edge_evidence;
--rollback DROP INDEX idx_canonical_node_evidence_evidence;
--rollback DROP TABLE canonical_node_evidence;
--rollback DROP INDEX idx_canonical_evidence_path;
--rollback DROP INDEX idx_canonical_evidence_raw_observation;
--rollback DROP TABLE canonical_evidence;
--rollback DROP INDEX idx_canonical_edges_kind;
--rollback DROP INDEX idx_canonical_edges_target;
--rollback DROP INDEX idx_canonical_edges_source;
--rollback DROP TABLE canonical_edges;
--rollback DROP INDEX idx_canonical_nodes_last_seen_run;
--rollback DROP INDEX idx_canonical_nodes_kind;
--rollback DROP TABLE canonical_nodes;
