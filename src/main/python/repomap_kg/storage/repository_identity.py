"""Stable repository identity reconciliation SQL."""

from __future__ import annotations

import re

from repomap_kg.storage.errors import StorageSchemaError


_REPOSITORY_IDENTITY_PATTERN = re.compile(
    r"^repo1:[A-Za-z0-9][A-Za-z0-9._-]{0,123}$"
)


def repository_identity_state_sql(
    repository_identity: str,
    root_path: str,
) -> str:
    """Return a private-input, count-only repository identity state query."""

    _validate_identity_inputs(repository_identity, "repository", root_path)
    identity = _sql_literal(repository_identity)
    root = _sql_literal(root_path)
    return (
        "SELECT count(*), "
        f"count(*) FILTER (WHERE repository_identity = {identity}), "
        "count(*) FILTER (WHERE repository_identity IS NOT NULL "
        f"AND repository_identity <> {identity}), "
        f"count(*) FILTER (WHERE root_path = {root}) "
        "FROM repositories;\n"
    )


def repository_identity_reconciliation_sql(
    repository_identity: str,
    repository_name: str,
    root_path: str,
) -> str:
    """Build one transaction reconciling path-keyed repository ownership."""

    _validate_identity_inputs(repository_identity, repository_name, root_path)
    identity = _sql_literal(repository_identity)
    name = _sql_literal(repository_name)
    root = _sql_literal(root_path)
    return f"""BEGIN;
LOCK TABLE repositories IN SHARE ROW EXCLUSIVE MODE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM repositories
        WHERE repository_identity IS NOT NULL
          AND repository_identity <> {identity}
    ) THEN
        RAISE EXCEPTION 'conflicting stable repository identity';
    END IF;
END
$$;

INSERT INTO repositories(name, root_path, repository_identity)
SELECT {name}, {root}, {identity}
WHERE NOT EXISTS (SELECT 1 FROM repositories);

CREATE TEMP TABLE repomap_identity_survivor ON COMMIT DROP AS
SELECT id
FROM repositories
ORDER BY
    (repository_identity = {identity}) DESC NULLS LAST,
    (root_path = {root}) DESC,
    id
LIMIT 1;
ALTER TABLE repomap_identity_survivor ADD PRIMARY KEY (id);

UPDATE runs
SET repository_id = (SELECT id FROM repomap_identity_survivor)
WHERE repository_id <> (SELECT id FROM repomap_identity_survivor);

CREATE TEMP TABLE repomap_file_map ON COMMIT DROP AS
SELECT id AS old_id, keeper_id AS new_id
FROM (
    SELECT
        id,
        first_value(id) OVER (
            PARTITION BY path
            ORDER BY
                (repository_id = (SELECT id FROM repomap_identity_survivor)) DESC,
                id
        ) AS keeper_id
    FROM files
) ranked
WHERE id <> keeper_id;
ALTER TABLE repomap_file_map ADD PRIMARY KEY (old_id);

DO $repomap_legacy_file_ownership$
BEGIN
    IF num_nonnulls(
        to_regclass('public.nodes'),
        to_regclass('public.evidence'),
        to_regclass('public.edges')
    ) NOT IN (0, 3) THEN
        RAISE EXCEPTION 'legacy graph schema is incomplete';
    END IF;
    IF to_regclass('public.nodes') IS NOT NULL THEN
        UPDATE nodes target
        SET file_id = mapping.new_id
        FROM repomap_file_map mapping
        WHERE target.file_id = mapping.old_id;
        UPDATE evidence target
        SET file_id = mapping.new_id
        FROM repomap_file_map mapping
        WHERE target.file_id = mapping.old_id;
    END IF;
END
$repomap_legacy_file_ownership$;

DELETE FROM files target
USING repomap_file_map mapping
WHERE target.id = mapping.old_id;
UPDATE files
SET repository_id = (SELECT id FROM repomap_identity_survivor)
WHERE repository_id <> (SELECT id FROM repomap_identity_survivor);

DO $repomap_legacy_graph_ownership$
BEGIN
    IF to_regclass('public.nodes') IS NOT NULL THEN
        CREATE TEMP TABLE repomap_node_map ON COMMIT DROP AS
        SELECT id AS old_id, keeper_id AS new_id
        FROM (
            SELECT
                id,
                first_value(id) OVER (
                    PARTITION BY stable_key
                    ORDER BY
                        (
                            repository_id = (
                                SELECT id FROM repomap_identity_survivor
                            )
                        ) DESC,
                        id
                ) AS keeper_id
            FROM nodes
        ) ranked
        WHERE id <> keeper_id;
        ALTER TABLE repomap_node_map ADD PRIMARY KEY (old_id);

        UPDATE edges target
        SET src_node_id = mapping.new_id
        FROM repomap_node_map mapping
        WHERE target.src_node_id = mapping.old_id;
        UPDATE edges target
        SET dst_node_id = mapping.new_id
        FROM repomap_node_map mapping
        WHERE target.dst_node_id = mapping.old_id;
        DELETE FROM nodes target
        USING repomap_node_map mapping
        WHERE target.id = mapping.old_id;
        UPDATE nodes
        SET repository_id = (SELECT id FROM repomap_identity_survivor)
        WHERE repository_id <> (SELECT id FROM repomap_identity_survivor);

        CREATE TEMP TABLE repomap_evidence_map ON COMMIT DROP AS
        SELECT id AS old_id, keeper_id AS new_id
        FROM (
            SELECT
                id,
                first_value(id) OVER (
                    PARTITION BY stable_key
                    ORDER BY
                        (
                            repository_id = (
                                SELECT id FROM repomap_identity_survivor
                            )
                        ) DESC,
                        id
                ) AS keeper_id
            FROM evidence
        ) ranked
        WHERE id <> keeper_id;
        ALTER TABLE repomap_evidence_map ADD PRIMARY KEY (old_id);

        UPDATE edges target
        SET evidence_id = mapping.new_id
        FROM repomap_evidence_map mapping
        WHERE target.evidence_id = mapping.old_id;
        DELETE FROM evidence target
        USING repomap_evidence_map mapping
        WHERE target.id = mapping.old_id;
        UPDATE evidence
        SET repository_id = (SELECT id FROM repomap_identity_survivor)
        WHERE repository_id <> (SELECT id FROM repomap_identity_survivor);

        DELETE FROM edges target
        USING (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY stable_key
                    ORDER BY
                        (
                            repository_id = (
                                SELECT id FROM repomap_identity_survivor
                            )
                        ) DESC,
                        id
                ) AS identity_rank
            FROM edges
        ) ranked
        WHERE target.id = ranked.id
          AND ranked.identity_rank > 1;
        UPDATE edges
        SET repository_id = (SELECT id FROM repomap_identity_survivor)
        WHERE repository_id <> (SELECT id FROM repomap_identity_survivor);
    END IF;
END
$repomap_legacy_graph_ownership$;

UPDATE raw_observations
SET repository_id = (SELECT id FROM repomap_identity_survivor)
WHERE repository_id <> (SELECT id FROM repomap_identity_survivor);
UPDATE canonical_evidence
SET repository_id = (SELECT id FROM repomap_identity_survivor)
WHERE repository_id <> (SELECT id FROM repomap_identity_survivor);

CREATE TEMP TABLE repomap_canonical_node_map ON COMMIT DROP AS
SELECT id AS old_id, keeper_id AS new_id
FROM (
    SELECT
        id,
        first_value(id) OVER (
            PARTITION BY graph_key_version, canonical_key
            ORDER BY
                (repository_id = (SELECT id FROM repomap_identity_survivor)) DESC,
                id
        ) AS keeper_id
    FROM canonical_nodes
) ranked
WHERE id <> keeper_id;
ALTER TABLE repomap_canonical_node_map ADD PRIMARY KEY (old_id);

UPDATE canonical_nodes
SET repository_id = (SELECT id FROM repomap_identity_survivor)
WHERE repository_id <> (SELECT id FROM repomap_identity_survivor)
  AND id NOT IN (SELECT old_id FROM repomap_canonical_node_map);

CREATE TEMP TABLE repomap_canonical_edge_map ON COMMIT DROP AS
SELECT id AS old_id, keeper_id AS new_id
FROM (
    SELECT
        id,
        first_value(id) OVER (
            PARTITION BY
                graph_key_version,
                source_canonical_key,
                edge_kind,
                target_canonical_key,
                identity_metadata_hash
            ORDER BY
                (repository_id = (SELECT id FROM repomap_identity_survivor)) DESC,
                id
        ) AS keeper_id
    FROM canonical_edges
) ranked
WHERE id <> keeper_id;
ALTER TABLE repomap_canonical_edge_map ADD PRIMARY KEY (old_id);

INSERT INTO canonical_edge_evidence(
    canonical_edge_id, canonical_evidence_id, link_kind, created_at
)
SELECT mapping.new_id, link.canonical_evidence_id, link.link_kind, link.created_at
FROM canonical_edge_evidence link
JOIN repomap_canonical_edge_map mapping
  ON mapping.old_id = link.canonical_edge_id
ON CONFLICT DO NOTHING;
DELETE FROM canonical_edge_evidence link
USING repomap_canonical_edge_map mapping
WHERE link.canonical_edge_id = mapping.old_id;
DELETE FROM canonical_edges target
USING repomap_canonical_edge_map mapping
WHERE target.id = mapping.old_id;
UPDATE canonical_edges
SET repository_id = (SELECT id FROM repomap_identity_survivor)
WHERE repository_id <> (SELECT id FROM repomap_identity_survivor);

INSERT INTO canonical_node_evidence(
    canonical_node_id, canonical_evidence_id, link_kind, created_at
)
SELECT mapping.new_id, link.canonical_evidence_id, link.link_kind, link.created_at
FROM canonical_node_evidence link
JOIN repomap_canonical_node_map mapping
  ON mapping.old_id = link.canonical_node_id
ON CONFLICT DO NOTHING;
DELETE FROM canonical_node_evidence link
USING repomap_canonical_node_map mapping
WHERE link.canonical_node_id = mapping.old_id;
DELETE FROM canonical_nodes target
USING repomap_canonical_node_map mapping
WHERE target.id = mapping.old_id;

UPDATE ingestion_stages
SET repository_id = (SELECT id FROM repomap_identity_survivor)
WHERE repository_id <> (SELECT id FROM repomap_identity_survivor);

CREATE TEMP TABLE repomap_authority_winner ON COMMIT DROP AS
SELECT repository_id
FROM graph_publication_authority
ORDER BY
    singleton_fencing_epoch DESC,
    graph_lease_fencing_epoch DESC,
    repository_id DESC
LIMIT 1;
DELETE FROM graph_publication_authority
WHERE repository_id <> COALESCE(
    (SELECT repository_id FROM repomap_authority_winner),
    repository_id
);
UPDATE graph_publication_authority
SET repository_id = (SELECT id FROM repomap_identity_survivor)
WHERE repository_id = (SELECT repository_id FROM repomap_authority_winner)
  AND repository_id <> (SELECT id FROM repomap_identity_survivor);

DELETE FROM repositories
WHERE id <> (SELECT id FROM repomap_identity_survivor);
UPDATE repositories
SET name = {name},
    root_path = {root},
    repository_identity = {identity}
WHERE id = (SELECT id FROM repomap_identity_survivor);

COMMIT;
"""


def _validate_identity_inputs(
    repository_identity: str,
    repository_name: str,
    root_path: str,
) -> None:
    validate_repository_identity(repository_identity)
    if not repository_name or "\x00" in repository_name:
        raise StorageSchemaError("repository name is invalid")
    if not root_path or "\x00" in root_path:
        raise StorageSchemaError("repository source location is invalid")


def validate_repository_identity(repository_identity: str) -> str:
    """Return one validated versioned repository identity."""

    if (
        not isinstance(repository_identity, str)
        or not _REPOSITORY_IDENTITY_PATTERN.fullmatch(repository_identity)
    ):
        raise StorageSchemaError("stable repository identity is invalid")
    return repository_identity


def repository_upsert_sql(
    repository_name: str,
    root_path: str,
    repository_identity: str | None = None,
) -> str:
    """Build stable or historical repository upsert SQL."""

    if repository_identity is None:
        return (
            "INSERT INTO repositories(name, root_path) "
            f"VALUES ({_sql_literal(repository_name)}, {_sql_literal(root_path)}) "
            "ON CONFLICT (root_path) DO UPDATE SET name = EXCLUDED.name "
            "RETURNING id"
        )
    identity = validate_repository_identity(repository_identity)
    return (
        "INSERT INTO repositories(name, root_path, repository_identity) "
        f"VALUES ({_sql_literal(repository_name)}, {_sql_literal(root_path)}, "
        f"{_sql_literal(identity)}) "
        "ON CONFLICT (repository_identity) "
        "WHERE repository_identity IS NOT NULL DO UPDATE SET "
        "name = EXCLUDED.name, root_path = EXCLUDED.root_path RETURNING id"
    )


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
