--liquibase formatted sql
--changeset slair:2026_06_28-001-core-create_graph_tables

CREATE TABLE repositories (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    root_path TEXT NOT NULL,
    remote_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (root_path)
);

CREATE TABLE runs (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    git_commit TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',
    tool_versions_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (status IN ('running', 'complete', 'failed'))
);

CREATE TABLE files (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'unknown',
    role TEXT NOT NULL DEFAULT 'unknown',
    content_hash TEXT,
    executable BOOLEAN NOT NULL DEFAULT false,
    generated BOOLEAN NOT NULL DEFAULT false,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (repository_id, path),
    CHECK (
        role IN (
            'config',
            'documentation',
            'entrypoint',
            'generated',
            'script',
            'source',
            'test',
            'unknown'
        )
    ),
    CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$')
);

CREATE TABLE nodes (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    file_id BIGINT REFERENCES files(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    stable_key TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (repository_id, stable_key),
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

CREATE TABLE evidence (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    file_id BIGINT REFERENCES files(id) ON DELETE SET NULL,
    start_line INTEGER,
    end_line INTEGER,
    excerpt TEXT,
    extractor TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
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

CREATE TABLE edges (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    src_node_id BIGINT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    dst_node_id BIGINT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    confidence TEXT NOT NULL,
    evidence_id BIGINT NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (confidence IN ('extracted', 'heuristic', 'manual', 'unknown'))
);

CREATE INDEX idx_runs_repository_id ON runs(repository_id);
CREATE INDEX idx_files_repository_role ON files(repository_id, role);
CREATE INDEX idx_nodes_repository_kind ON nodes(repository_id, kind);
CREATE INDEX idx_edges_repository_kind ON edges(repository_id, kind);

--rollback DROP TABLE edges;
--rollback DROP TABLE evidence;
--rollback DROP TABLE nodes;
--rollback DROP TABLE files;
--rollback DROP TABLE runs;
--rollback DROP TABLE repositories;
