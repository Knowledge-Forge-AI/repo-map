"""Set-based SCALE4 validation and merge SQL for canonical graph rows."""

from __future__ import annotations

from repomap_kg.storage.sql_core import sql_literal
from repomap_kg.storage.staging_duplicate_guard import identity_conflict_guard
from repomap_kg.storage.staging_family_catalog import (
    descriptors_for_merge_scope, merge_operations_for_scope,
)
from repomap_kg.storage.staging_family_contracts import DuplicatePolicy, ValidationRule
from repomap_kg.storage.staging_merge_operations import MergeOperation, MergeScope
from repomap_kg.storage.staging_merge import (
    MergeContext, build_source_index_merge_statements,
)

__all__ = ("build_canonical_merge_statements",)


def build_canonical_merge_statements(
    context: MergeContext,
) -> tuple[str, ...]:
    """Build caller-owned validation and merge statements for canonical rows."""

    context.validate()
    stage = sql_literal(context.stage_id)
    repository = str(context.repository_id)
    run = str(context.run_id)
    builders = {
        MergeOperation.CANONICAL_RAW_REFERENCE: lambda: _raw_reference_guard(stage, repository, run),
        MergeOperation.CANONICAL_NODES: lambda: _canonical_nodes_merge(stage, run),
        MergeOperation.CANONICAL_EVIDENCE: lambda: _canonical_evidence_merge(stage, repository, run),
        MergeOperation.CANONICAL_EDGE_REFERENCE: lambda: _canonical_edge_reference_guard(stage, repository),
        MergeOperation.CANONICAL_EDGES: lambda: _canonical_edges_merge(stage, repository, run),
        MergeOperation.CANONICAL_NODE_EVIDENCE_REFERENCE: lambda: _canonical_node_evidence_reference_guard(stage, repository, run),
        MergeOperation.CANONICAL_NODE_EVIDENCE: lambda: _canonical_node_evidence_merge(stage, repository, run),
        MergeOperation.CANONICAL_EDGE_EVIDENCE_REFERENCE: lambda: _canonical_edge_evidence_reference_guard(stage, repository, run),
        MergeOperation.CANONICAL_EDGE_EVIDENCE: lambda: _canonical_edge_evidence_merge(stage, repository, run),
    }
    operations = tuple(
        builders[binding.operation]()
        for binding in merge_operations_for_scope(MergeScope.CANONICAL)
    )
    return (build_source_index_merge_statements(context)[0], _proposal_guard(stage), *operations)


def _proposal_guard(stage: str) -> str:
    conflicts = "".join(
        identity_conflict_guard(descriptor, stage, "SCALE4")
        for descriptor in descriptors_for_merge_scope(MergeScope.CANONICAL)
        if descriptor.duplicate_policy is DuplicatePolicy.IDENTICAL_ONLY
        and ValidationRule.IDENTITY_CONFLICT in descriptor.validation_rules
    )
    return f"""DO $scale4$
BEGIN
{conflicts}END
$scale4$;"""


def _raw_reference_guard(stage: str, repository: str, run: str) -> str:
    return f"""DO $scale4$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM stage_canonical_evidence staged
        LEFT JOIN raw_observations raw
          ON raw.repository_id = {repository}
         AND raw.run_id = {run}
         AND raw.ordinal = staged.raw_observation_ordinal
        WHERE staged.stage_id = {stage}
          AND (
              raw.id IS NULL
              OR raw.schema_version IS DISTINCT FROM staged.raw_schema_version
              OR raw.kind IS DISTINCT FROM staged.raw_kind
              OR raw.source_id IS DISTINCT FROM staged.raw_source_id
              OR raw.path IS DISTINCT FROM staged.path
          )
    ) THEN
        RAISE EXCEPTION 'SCALE4 raw observation reference is missing';
    END IF;
END
$scale4$;"""


def _canonical_nodes_merge(stage: str, run: str) -> str:
    return f"""WITH proposals AS (
    SELECT DISTINCT ON (s.graph_key_version, s.canonical_key)
        header.repository_id,
        s.graph_key_version,
        s.canonical_key,
        s.kind,
        s.display_name,
        s.metadata_json,
        s.confidence,
        s.conflict
    FROM stage_canonical_nodes s
    JOIN ingestion_stages header ON header.stage_id = s.stage_id
    WHERE s.stage_id = {stage}
    ORDER BY s.graph_key_version, s.canonical_key, s.family_ordinal
)
INSERT INTO canonical_nodes(
    repository_id, graph_key_version, canonical_key, kind, display_name,
    metadata_json, confidence, conflict, first_seen_run_id, last_seen_run_id
)
SELECT repository_id, graph_key_version, canonical_key, kind, display_name,
       metadata_json, confidence, conflict, {run}, {run}
FROM proposals
ON CONFLICT (repository_id, graph_key_version, canonical_key) DO UPDATE SET
    kind = EXCLUDED.kind,
    display_name = EXCLUDED.display_name,
    metadata_json = EXCLUDED.metadata_json,
    confidence = EXCLUDED.confidence,
    conflict = EXCLUDED.conflict,
    last_seen_run_id = EXCLUDED.last_seen_run_id,
    updated_at = now();"""


def _canonical_evidence_merge(stage: str, repository: str, run: str) -> str:
    return f"""WITH proposals AS (
    SELECT DISTINCT ON (s.graph_key_version, s.evidence_key)
        header.repository_id,
        raw.id AS raw_observation_id,
        s.graph_key_version,
        s.evidence_key,
        s.raw_observation_ordinal,
        s.raw_schema_version,
        s.raw_kind,
        s.raw_source_id,
        s.path,
        s.start_line,
        s.end_line,
        s.extractor,
        s.extractor_version,
        s.confidence,
        s.metadata_json
    FROM stage_canonical_evidence s
    JOIN ingestion_stages header ON header.stage_id = s.stage_id
    JOIN raw_observations raw
      ON raw.repository_id = {repository}
     AND raw.run_id = {run}
     AND raw.ordinal = s.raw_observation_ordinal
    WHERE s.stage_id = {stage}
    ORDER BY s.graph_key_version, s.evidence_key, s.family_ordinal
)
INSERT INTO canonical_evidence(
    repository_id, run_id, graph_key_version, raw_observation_id,
    evidence_key, raw_observation_ordinal, raw_schema_version, raw_kind,
    raw_source_id, path, start_line, end_line, extractor, extractor_version,
    confidence, metadata_json
)
SELECT repository_id, {run}, graph_key_version, raw_observation_id,
       evidence_key, raw_observation_ordinal, raw_schema_version, raw_kind,
       raw_source_id, path, start_line, end_line, extractor, extractor_version,
       confidence, metadata_json
FROM proposals
ON CONFLICT (run_id, graph_key_version, evidence_key) DO UPDATE SET
    raw_observation_id = EXCLUDED.raw_observation_id,
    raw_observation_ordinal = EXCLUDED.raw_observation_ordinal,
    raw_schema_version = EXCLUDED.raw_schema_version,
    raw_kind = EXCLUDED.raw_kind,
    raw_source_id = EXCLUDED.raw_source_id,
    path = EXCLUDED.path,
    start_line = EXCLUDED.start_line,
    end_line = EXCLUDED.end_line,
    extractor = EXCLUDED.extractor,
    extractor_version = EXCLUDED.extractor_version,
    confidence = EXCLUDED.confidence,
    metadata_json = EXCLUDED.metadata_json;"""


def _canonical_edge_reference_guard(stage: str, repository: str) -> str:
    return f"""DO $scale4$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM stage_canonical_edges staged
        WHERE staged.stage_id = {stage}
          AND (
              NOT EXISTS (
                  SELECT 1
                  FROM canonical_nodes src
                  WHERE src.repository_id = {repository}
                    AND src.graph_key_version = staged.graph_key_version
                    AND src.canonical_key = staged.source_canonical_key
              )
              OR NOT EXISTS (
                  SELECT 1
                  FROM canonical_nodes dst
                  WHERE dst.repository_id = {repository}
                    AND dst.graph_key_version = staged.graph_key_version
                    AND dst.canonical_key = staged.target_canonical_key
              )
          )
    ) THEN
        RAISE EXCEPTION 'SCALE4 canonical edge reference is missing';
    END IF;
END
$scale4$;"""


def _canonical_edges_merge(stage: str, repository: str, run: str) -> str:
    return f"""WITH proposals AS (
    SELECT DISTINCT ON (
        s.graph_key_version, s.source_canonical_key, s.edge_kind,
        s.target_canonical_key, s.identity_metadata_hash
    )
        header.repository_id,
        s.graph_key_version,
        s.source_canonical_key,
        s.edge_kind,
        s.target_canonical_key,
        s.identity_metadata_json,
        s.identity_metadata_hash,
        s.metadata_json,
        s.confidence,
        s.conflict
    FROM stage_canonical_edges s
    JOIN ingestion_stages header ON header.stage_id = s.stage_id
    JOIN canonical_nodes src
      ON src.repository_id = {repository}
     AND src.graph_key_version = s.graph_key_version
     AND src.canonical_key = s.source_canonical_key
    JOIN canonical_nodes dst
      ON dst.repository_id = {repository}
     AND dst.graph_key_version = s.graph_key_version
     AND dst.canonical_key = s.target_canonical_key
    WHERE s.stage_id = {stage}
    ORDER BY s.graph_key_version, s.source_canonical_key, s.edge_kind,
             s.target_canonical_key, s.identity_metadata_hash,
             s.family_ordinal
)
INSERT INTO canonical_edges(
    repository_id, graph_key_version, source_canonical_key, edge_kind,
    target_canonical_key, identity_metadata_json, identity_metadata_hash,
    metadata_json, confidence, conflict, first_seen_run_id, last_seen_run_id
)
SELECT repository_id, graph_key_version, source_canonical_key, edge_kind,
       target_canonical_key, identity_metadata_json, identity_metadata_hash,
       metadata_json, confidence, conflict, {run}, {run}
FROM proposals
ON CONFLICT (
    repository_id, graph_key_version, source_canonical_key, edge_kind,
    target_canonical_key, identity_metadata_hash
) DO UPDATE SET
    identity_metadata_json = EXCLUDED.identity_metadata_json,
    metadata_json = EXCLUDED.metadata_json,
    confidence = EXCLUDED.confidence,
    conflict = EXCLUDED.conflict,
    last_seen_run_id = EXCLUDED.last_seen_run_id,
    updated_at = now();"""


def _canonical_node_evidence_reference_guard(
    stage: str, repository: str, run: str
) -> str:
    return f"""DO $scale4$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM (
            SELECT staged.graph_key_version, staged.canonical_key
            FROM stage_canonical_node_evidence staged
            WHERE staged.stage_id = {stage}
        ) AS staged
        FULL JOIN (
            SELECT node.graph_key_version, node.canonical_key
            FROM canonical_nodes node
            WHERE node.repository_id = {repository}
        ) AS node
          ON node.graph_key_version = staged.graph_key_version
         AND node.canonical_key = staged.canonical_key
        -- Keep the full join when final-transaction statistics are stale.
        WHERE COALESCE(staged.canonical_key, '') <> ''
          AND node.canonical_key IS NULL
    ) THEN
        RAISE EXCEPTION 'SCALE4 canonical node-evidence reference is missing';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM (
            SELECT staged.graph_key_version, staged.evidence_key
            FROM stage_canonical_node_evidence staged
            WHERE staged.stage_id = {stage}
        ) AS staged
        FULL JOIN (
            SELECT evidence.graph_key_version, evidence.evidence_key
            FROM canonical_evidence evidence
            WHERE evidence.repository_id = {repository}
              AND evidence.run_id = {run}
        ) AS evidence
          ON evidence.graph_key_version = staged.graph_key_version
         AND evidence.evidence_key = staged.evidence_key
        -- Keep the full join when final-transaction statistics are stale.
        WHERE COALESCE(staged.evidence_key, '') <> ''
          AND evidence.evidence_key IS NULL
    ) THEN
        RAISE EXCEPTION 'SCALE4 canonical node-evidence reference is missing';
    END IF;
END
$scale4$;"""


def _canonical_node_evidence_merge(stage: str, repository: str, run: str) -> str:
    return f"""WITH staged_links AS MATERIALIZED (
    SELECT
        s.graph_key_version,
        s.canonical_key,
        s.evidence_key,
        s.link_kind
    FROM stage_canonical_node_evidence s
    WHERE s.stage_id = {stage}
    GROUP BY s.graph_key_version, s.canonical_key, s.evidence_key, s.link_kind
),
proposals AS (
    SELECT
        node.id AS canonical_node_id,
        evidence.id AS canonical_evidence_id,
        s.link_kind
    FROM staged_links s
    JOIN canonical_nodes node
      ON node.repository_id = {repository}
     AND node.graph_key_version = s.graph_key_version
     AND node.canonical_key = s.canonical_key
    JOIN canonical_evidence evidence
      ON evidence.repository_id = {repository}
     AND evidence.run_id = {run}
     AND evidence.graph_key_version = s.graph_key_version
     AND evidence.evidence_key = s.evidence_key
)
INSERT INTO canonical_node_evidence(
    canonical_node_id, canonical_evidence_id, link_kind
)
SELECT canonical_node_id, canonical_evidence_id, link_kind
FROM proposals
ON CONFLICT DO NOTHING;"""


def _canonical_edge_evidence_reference_guard(
    stage: str, repository: str, run: str
) -> str:
    return f"""DO $scale4$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM stage_canonical_edge_evidence staged
        LEFT JOIN canonical_edges edge
          ON edge.repository_id = {repository}
         AND edge.graph_key_version = staged.graph_key_version
         AND edge.source_canonical_key = staged.source_canonical_key
         AND edge.edge_kind = staged.edge_kind
         AND edge.target_canonical_key = staged.target_canonical_key
         AND edge.identity_metadata_hash = staged.identity_metadata_hash
        LEFT JOIN canonical_evidence evidence
          ON evidence.repository_id = {repository}
         AND evidence.run_id = {run}
         AND evidence.graph_key_version = staged.graph_key_version
         AND evidence.evidence_key = staged.evidence_key
        WHERE staged.stage_id = {stage}
          AND (edge.id IS NULL OR evidence.id IS NULL)
    ) THEN
        RAISE EXCEPTION 'SCALE4 canonical edge-evidence reference is missing';
    END IF;
END
$scale4$;"""


def _canonical_edge_evidence_merge(stage: str, repository: str, run: str) -> str:
    return f"""WITH proposals AS (
    SELECT DISTINCT ON (
        s.graph_key_version, s.source_canonical_key, s.edge_kind,
        s.target_canonical_key, s.identity_metadata_hash,
        s.evidence_key, s.link_kind
    )
        edge.id AS canonical_edge_id,
        evidence.id AS canonical_evidence_id,
        s.link_kind
    FROM stage_canonical_edge_evidence s
    JOIN canonical_edges edge
      ON edge.repository_id = {repository}
     AND edge.graph_key_version = s.graph_key_version
     AND edge.source_canonical_key = s.source_canonical_key
     AND edge.edge_kind = s.edge_kind
     AND edge.target_canonical_key = s.target_canonical_key
     AND edge.identity_metadata_hash = s.identity_metadata_hash
    JOIN canonical_evidence evidence
      ON evidence.repository_id = {repository}
     AND evidence.run_id = {run}
     AND evidence.graph_key_version = s.graph_key_version
     AND evidence.evidence_key = s.evidence_key
    WHERE s.stage_id = {stage}
    ORDER BY s.graph_key_version, s.source_canonical_key, s.edge_kind,
             s.target_canonical_key, s.identity_metadata_hash,
             s.evidence_key, s.link_kind, s.family_ordinal
)
INSERT INTO canonical_edge_evidence(
    canonical_edge_id, canonical_evidence_id, link_kind
)
SELECT canonical_edge_id, canonical_evidence_id, link_kind
FROM proposals
ON CONFLICT DO NOTHING;"""
