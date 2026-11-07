--liquibase formatted sql
--changeset slair:2026_10_31-001-cloe-lexical-create-derived-schema

DO $cloe_lexical_guard$
DECLARE
    expected_owner oid := (SELECT datdba FROM pg_database WHERE datname = current_database());
    schema_oid oid := to_regnamespace('cloe_lexical');
    actual_owner oid;
    actual_marker text;
    foreign_obj_count bigint;
BEGIN
    IF schema_oid IS NULL THEN
        EXECUTE 'CREATE SCHEMA cloe_lexical';
        EXECUTE 'COMMENT ON SCHEMA cloe_lexical IS ''cloe-lexical-schema:1''';
    ELSE
        SELECT nspowner, obj_description(oid, 'pg_namespace')
        INTO actual_owner, actual_marker
        FROM pg_namespace
        WHERE oid = schema_oid;

        IF actual_owner <> expected_owner THEN
            RAISE EXCEPTION 'cloe_lexical schema or object custody is not owned by the database owner';
        END IF;

        IF COALESCE(actual_marker, '') <> 'cloe-lexical-schema:1' THEN
            RAISE EXCEPTION 'cloe_lexical schema is missing the expected cloe-lexical-schema:1 marker';
        END IF;

        SELECT count(*) INTO foreign_obj_count
        FROM pg_class c
        WHERE c.relnamespace = schema_oid
          AND c.relowner <> expected_owner;
        IF foreign_obj_count > 0 THEN
            RAISE EXCEPTION 'cloe_lexical schema or object custody is not owned by the database owner';
        END IF;

        SELECT count(*) INTO foreign_obj_count
        FROM pg_class c
        WHERE c.relnamespace = schema_oid
          AND c.relkind IN ('r', 'p', 'v', 'm', 'f', 'S')
          AND c.relname NOT IN ('generations', 'authority', 'documents', 'chunks', 'omissions');
        IF foreign_obj_count > 0 THEN
            RAISE EXCEPTION 'cloe_lexical contains unexpected relation objects';
        END IF;

        SELECT count(*) INTO foreign_obj_count
        FROM pg_proc p
        WHERE p.pronamespace = schema_oid;
        IF foreign_obj_count > 0 THEN
            RAISE EXCEPTION 'cloe_lexical contains unexpected routine objects';
        END IF;
    END IF;
END
$cloe_lexical_guard$;

REVOKE ALL ON SCHEMA cloe_lexical FROM PUBLIC;

CREATE TABLE IF NOT EXISTS cloe_lexical.generations (
    repository_id BIGINT NOT NULL REFERENCES public.repositories(id) ON DELETE CASCADE,
    lexical_generation_id TEXT NOT NULL CHECK (lexical_generation_id ~ '^lexgen1:[0-9a-f]{64}$'),
    run_id BIGINT NOT NULL REFERENCES public.runs(id) ON DELETE CASCADE,
    publication_bundle_id TEXT NOT NULL CHECK (publication_bundle_id ~ '^bundle1:[0-9a-f]{64}$'),
    snapshot_manifest_id TEXT NOT NULL CHECK (snapshot_manifest_id ~ '^snapmanifest1:[0-9a-f]{64}$'),
    extraction_receipt_id TEXT NOT NULL CHECK (extraction_receipt_id ~ '^receipt1:[0-9a-f]{64}$'),
    graph_candidate_id TEXT NOT NULL CHECK (graph_candidate_id ~ '^cand1:[0-9a-f]{64}$'),
    snapshot_vector_json TEXT NOT NULL CHECK (snapshot_vector_json <> ''),
    publication_receipt_json TEXT NOT NULL DEFAULT '{}' CHECK (publication_receipt_json <> ''),
    representation_version TEXT NOT NULL CHECK (representation_version = 'cloe-lexical-pg-fts-v1'),
    text_config_regconfig TEXT NOT NULL CHECK (text_config_regconfig = 'pg_catalog.simple'),
    ranking_function TEXT NOT NULL CHECK (ranking_function = 'ts_rank_cd(weight={0.1,0.2,0.4,1.0},normalization=32)'),
    normalization_flags INTEGER NOT NULL CHECK (normalization_flags = 32),
    alias_split_rule_version TEXT NOT NULL CHECK (alias_split_rule_version = 'identifier-path-split-v1'),
    policy_digest TEXT NOT NULL CHECK (policy_digest ~ '^sha256:[0-9a-f]{64}$'),
    resolved_graph_privacy TEXT NOT NULL CHECK (resolved_graph_privacy = 'public-dev'),
    binding_policy_digests_json TEXT NOT NULL CHECK (binding_policy_digests_json <> ''),
    admitted_binding_ids_json TEXT NOT NULL CHECK (admitted_binding_ids_json <> ''),
    excluded_binding_ids_json TEXT NOT NULL CHECK (excluded_binding_ids_json <> ''),
    projected_document_count INTEGER NOT NULL CHECK (projected_document_count >= 0),
    projected_chunk_count INTEGER NOT NULL CHECK (projected_chunk_count >= 0),
    omitted_record_count INTEGER NOT NULL CHECK (omitted_record_count >= 0),
    aggregate_input_bytes BIGINT NOT NULL CHECK (aggregate_input_bytes >= 0),
    aggregate_projected_bytes BIGINT NOT NULL CHECK (aggregate_projected_bytes >= 0),
    state TEXT NOT NULL CHECK (state IN ('building', 'published', 'revoked', 'invalidated')),
    builder_owner_id TEXT,
    lease_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    revocation_reason TEXT,
    PRIMARY KEY (repository_id, lexical_generation_id),
    UNIQUE (
        repository_id, lexical_generation_id, run_id,
        publication_bundle_id, snapshot_manifest_id, policy_digest
    ),
    CONSTRAINT cloe_lexical_generations_state_audit_check CHECK (
        (state <> 'published' OR published_at IS NOT NULL)
        AND (
            state NOT IN ('revoked', 'invalidated')
            OR (revoked_at IS NOT NULL AND revocation_reason IS NOT NULL AND revocation_reason <> '')
        )
    )
);

CREATE TABLE IF NOT EXISTS cloe_lexical.authority (
    repository_id BIGINT PRIMARY KEY REFERENCES public.repositories(id) ON DELETE CASCADE,
    lexical_generation_id TEXT NOT NULL,
    run_id BIGINT NOT NULL REFERENCES public.runs(id) ON DELETE CASCADE,
    publication_bundle_id TEXT NOT NULL CHECK (publication_bundle_id ~ '^bundle1:[0-9a-f]{64}$'),
    snapshot_manifest_id TEXT NOT NULL CHECK (snapshot_manifest_id ~ '^snapmanifest1:[0-9a-f]{64}$'),
    policy_digest TEXT NOT NULL CHECK (policy_digest ~ '^sha256:[0-9a-f]{64}$'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (
        repository_id, lexical_generation_id, run_id,
        publication_bundle_id, snapshot_manifest_id, policy_digest
    )
        REFERENCES cloe_lexical.generations(
            repository_id, lexical_generation_id, run_id,
            publication_bundle_id, snapshot_manifest_id, policy_digest
        ) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cloe_lexical.documents (
    repository_id BIGINT NOT NULL,
    lexical_generation_id TEXT NOT NULL,
    document_ordinal INTEGER NOT NULL CHECK (document_ordinal >= 0),
    binding_id TEXT NOT NULL CHECK (binding_id ~ '^bind1:[0-9a-f]{64}$'),
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    snapshot_id TEXT NOT NULL CHECK (snapshot_id ~ '^snap1:[0-9a-f]{64}$'),
    source_relative_path TEXT NOT NULL CHECK (
        source_relative_path <> ''
        AND left(source_relative_path, 1) <> '/'
    ),
    file_content_sha256 TEXT NOT NULL CHECK (file_content_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    normalized_byte_length INTEGER NOT NULL CHECK (
        normalized_byte_length >= 0 AND normalized_byte_length <= 262144
    ),
    line_count INTEGER NOT NULL CHECK (
        (normalized_byte_length = 0 AND line_count = 0)
        OR (normalized_byte_length > 0 AND line_count >= 1)
    ),
    chunk_count INTEGER NOT NULL CHECK (chunk_count >= 1),
    normalized_text TEXT NOT NULL,
    artifact_privacy TEXT NOT NULL CHECK (artifact_privacy IN ('public-dev', 'public', 'raw_source')),
    evidence_retention TEXT NOT NULL CHECK (evidence_retention = 'full-authorized'),
    PRIMARY KEY (repository_id, lexical_generation_id, binding_id, source_relative_path),
    UNIQUE (repository_id, lexical_generation_id, document_ordinal),
    FOREIGN KEY (repository_id, lexical_generation_id)
        REFERENCES cloe_lexical.generations(repository_id, lexical_generation_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cloe_lexical.chunks (
    repository_id BIGINT NOT NULL,
    lexical_generation_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL CHECK (chunk_id ~ '^pchunk1:[0-9a-f]{64}$'),
    binding_id TEXT NOT NULL CHECK (binding_id ~ '^bind1:[0-9a-f]{64}$'),
    binding_revision INTEGER NOT NULL CHECK (binding_revision > 0),
    snapshot_id TEXT NOT NULL CHECK (snapshot_id ~ '^snap1:[0-9a-f]{64}$'),
    source_relative_path TEXT NOT NULL CHECK (source_relative_path <> ''),
    chunk_ordinal INTEGER NOT NULL CHECK (chunk_ordinal >= 0),
    start_line INTEGER NOT NULL CHECK (
        (byte_length = 0 AND chunk_ordinal = 0 AND start_line = 0 AND end_line = 0)
        OR (start_line >= 1 AND end_line >= start_line)
    ),
    end_line INTEGER NOT NULL CHECK (end_line >= start_line),
    byte_length INTEGER NOT NULL CHECK (byte_length >= 0 AND byte_length <= 8192),
    chunk_sha256 TEXT NOT NULL CHECK (chunk_sha256 ~ '^sha256:[0-9a-f]{64}$'),
    chunk_text TEXT NOT NULL,
    alias_tokens_text TEXT NOT NULL,
    ranked_vector TSVECTOR NOT NULL,
    phrase_vector TSVECTOR NOT NULL,
    artifact_privacy TEXT NOT NULL CHECK (artifact_privacy IN ('public-dev', 'public', 'raw_source')),
    PRIMARY KEY (repository_id, lexical_generation_id, chunk_id),
    UNIQUE (repository_id, lexical_generation_id, binding_id, source_relative_path, chunk_ordinal),
    FOREIGN KEY (repository_id, lexical_generation_id, binding_id, source_relative_path)
        REFERENCES cloe_lexical.documents(
            repository_id, lexical_generation_id, binding_id, source_relative_path
        ) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cloe_lexical.omissions (
    repository_id BIGINT NOT NULL,
    lexical_generation_id TEXT NOT NULL,
    omission_ordinal INTEGER NOT NULL CHECK (omission_ordinal >= 0),
    binding_id TEXT NOT NULL CHECK (binding_id <> ''),
    source_relative_path TEXT,
    reason_code TEXT NOT NULL CHECK (reason_code <> ''),
    detail TEXT NOT NULL CHECK (detail <> ''),
    PRIMARY KEY (repository_id, lexical_generation_id, omission_ordinal),
    FOREIGN KEY (repository_id, lexical_generation_id)
        REFERENCES cloe_lexical.generations(repository_id, lexical_generation_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cloe_lexical_chunks_ranked_gin
    ON cloe_lexical.chunks USING GIN (ranked_vector);

CREATE INDEX IF NOT EXISTS idx_cloe_lexical_chunks_phrase_gin
    ON cloe_lexical.chunks USING GIN (phrase_vector);

CREATE INDEX IF NOT EXISTS idx_cloe_lexical_chunks_scope
    ON cloe_lexical.chunks (
        repository_id, lexical_generation_id, binding_id,
        source_relative_path, start_line, end_line, chunk_id
    );

CREATE INDEX IF NOT EXISTS idx_cloe_lexical_documents_scope
    ON cloe_lexical.documents (
        repository_id, lexical_generation_id, binding_id, source_relative_path
    );

CREATE INDEX IF NOT EXISTS idx_cloe_lexical_omissions_scope
    ON cloe_lexical.omissions (
        repository_id, lexical_generation_id, binding_id, omission_ordinal
    );

REVOKE ALL ON ALL TABLES IN SCHEMA cloe_lexical FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA cloe_lexical FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA cloe_lexical REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA cloe_lexical REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA cloe_lexical REVOKE ALL ON FUNCTIONS FROM PUBLIC;

DO $cloe_lexical_roles$
DECLARE
    role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY[
        'repomap_read_status',
        'repomap_refresh_publication',
        'repomap_coordinator_control'
    ]
    LOOP
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = role_name) THEN
            EXECUTE format('REVOKE ALL ON SCHEMA cloe_lexical FROM %I', role_name);
            EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA cloe_lexical FROM %I', role_name);
            EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA cloe_lexical FROM %I', role_name);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA cloe_lexical REVOKE ALL ON TABLES FROM %I', role_name);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA cloe_lexical REVOKE ALL ON SEQUENCES FROM %I', role_name);
            EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA cloe_lexical REVOKE ALL ON FUNCTIONS FROM %I', role_name);
        END IF;
    END LOOP;
END
$cloe_lexical_roles$;

--rollback DROP SCHEMA IF EXISTS cloe_lexical CASCADE;
