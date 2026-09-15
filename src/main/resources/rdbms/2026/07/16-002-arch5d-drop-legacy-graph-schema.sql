--liquibase formatted sql
--changeset slair:2026_07_16-002-arch5d-drop-legacy-graph-schema

DO $arch5d_identity_guard$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM repositories
        WHERE repository_identity IS NULL
    ) THEN
        RAISE EXCEPTION
            'legacy schema removal requires stable repository identity';
    END IF;
END
$arch5d_identity_guard$;

ALTER TABLE ingestion_stages
    ALTER COLUMN expected_family_manifest SET DEFAULT (
        '{"schema_version":1,"families":["files","raw_observations",'
        '"canonical_nodes","canonical_edges","canonical_evidence",'
        '"canonical_node_evidence","canonical_edge_evidence"]}'
    )::jsonb;

DROP TABLE stage_legacy_edges;
DROP TABLE stage_legacy_evidence;
DROP TABLE stage_legacy_nodes;

DROP TABLE edges;
DROP TABLE evidence;
DROP TABLE nodes;
