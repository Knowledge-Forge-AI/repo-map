--liquibase formatted sql
--changeset slair:2026_06_29-001-core-create_raw_observations

CREATE TABLE raw_observations (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL
        REFERENCES repositories(id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL
        REFERENCES runs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    path TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, ordinal),
    CHECK (ordinal >= 0),
    CHECK (schema_version > 0),
    CHECK (payload_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX idx_raw_observations_repository_run
    ON raw_observations(repository_id, run_id, ordinal);

CREATE INDEX idx_raw_observations_kind
    ON raw_observations(repository_id, kind);

CREATE INDEX idx_raw_observations_payload_hash
    ON raw_observations(repository_id, payload_hash);

--rollback DROP INDEX idx_raw_observations_payload_hash;
--rollback DROP INDEX idx_raw_observations_kind;
--rollback DROP INDEX idx_raw_observations_repository_run;
--rollback DROP TABLE raw_observations;
