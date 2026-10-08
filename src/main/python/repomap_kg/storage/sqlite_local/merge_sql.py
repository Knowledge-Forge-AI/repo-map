"""Set-based SQLite Local merge statements for the seven logical families.

The SQLite form of ``storage.staging_merge`` and
``storage.canonical_staging_merge``: files take the last proposal by
``family_ordinal``; canonical nodes, edges and evidence take the first; links
are set-deduplicated; guards refuse missing raw/node/edge/evidence references.
Statements read connection-local ``temp.stage_<family>`` tables and bind only
the run id.
"""

from __future__ import annotations

from repomap_kg.storage.staging_family_rows import StageFamily

# (statement, guard message): a guard statement refuses when it returns a row;
# a ``None`` guard marks a mutation bound to ``:run``.
MERGE_STATEMENTS: dict[str, tuple[tuple[str, str | None], ...]] = {
    "files": ((
        "INSERT INTO files(path, language, role, content_hash, executable, generated, "
        "metadata_json, last_seen_run_id) "
        "SELECT path, language, role, content_hash, executable, generated, metadata_json, :run "
        "FROM (SELECT *, row_number() OVER (PARTITION BY path ORDER BY family_ordinal DESC) "
        "AS proposal FROM temp.stage_files) WHERE proposal = 1 "
        "ON CONFLICT(path) DO UPDATE SET last_seen_run_id = excluded.last_seen_run_id, "
        "language = excluded.language, role = excluded.role, "
        "content_hash = excluded.content_hash, executable = excluded.executable, "
        "generated = excluded.generated, metadata_json = excluded.metadata_json",
        None,
    ),),
    "raw_observations": ((
        "INSERT INTO raw_observations(run_id, ordinal, schema_version, kind, source_id, path, "
        "payload_json, payload_hash) "
        "SELECT DISTINCT :run, source_ordinal, schema_version, kind, source_id, path, "
        "payload_json, payload_hash FROM temp.stage_raw_observations",
        None,
    ),),
    "canonical_nodes": ((
        "INSERT INTO canonical_nodes(graph_key_version, canonical_key, kind, display_name, "
        "metadata_json, confidence, conflict, first_seen_run_id, last_seen_run_id) "
        "SELECT graph_key_version, canonical_key, kind, display_name, metadata_json, "
        "confidence, conflict, :run, :run FROM (SELECT *, row_number() OVER ("
        "PARTITION BY graph_key_version, canonical_key ORDER BY family_ordinal) AS proposal "
        "FROM temp.stage_canonical_nodes) WHERE proposal = 1 "
        "ON CONFLICT(graph_key_version, canonical_key) DO UPDATE SET kind = excluded.kind, "
        "display_name = excluded.display_name, metadata_json = excluded.metadata_json, "
        "confidence = excluded.confidence, conflict = excluded.conflict, "
        "last_seen_run_id = excluded.last_seen_run_id",
        None,
    ),),
    "canonical_evidence": (
        (
            "SELECT 1 FROM temp.stage_canonical_evidence staged "
            "LEFT JOIN raw_observations raw ON raw.run_id = ? "
            "AND raw.ordinal = staged.raw_observation_ordinal "
            "WHERE raw.ordinal IS NULL OR raw.schema_version IS NOT staged.raw_schema_version "
            "OR raw.kind IS NOT staged.raw_kind OR raw.source_id IS NOT staged.raw_source_id "
            "OR raw.path IS NOT staged.path",
            "raw observation reference is missing",
        ),
        (
            "INSERT INTO canonical_evidence(run_id, graph_key_version, evidence_key, "
            "raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id, path, "
            "start_line, end_line, extractor, extractor_version, confidence, metadata_json) "
            "SELECT :run, graph_key_version, evidence_key, raw_observation_ordinal, "
            "raw_schema_version, raw_kind, raw_source_id, path, start_line, end_line, "
            "extractor, extractor_version, confidence, metadata_json FROM (SELECT *, "
            "row_number() OVER (PARTITION BY graph_key_version, evidence_key "
            "ORDER BY family_ordinal) AS proposal FROM temp.stage_canonical_evidence) "
            "WHERE proposal = 1",
            None,
        ),
    ),
    "canonical_edges": (
        (
            "SELECT 1 FROM temp.stage_canonical_edges staged WHERE NOT EXISTS ("
            "SELECT 1 FROM canonical_nodes src WHERE src.graph_key_version = "
            "staged.graph_key_version AND src.canonical_key = staged.source_canonical_key) "
            "OR NOT EXISTS (SELECT 1 FROM canonical_nodes dst WHERE dst.graph_key_version = "
            "staged.graph_key_version AND dst.canonical_key = staged.target_canonical_key)",
            "canonical edge reference is missing",
        ),
        (
            "INSERT INTO canonical_edges(graph_key_version, source_canonical_key, edge_kind, "
            "target_canonical_key, identity_metadata_json, identity_metadata_hash, "
            "metadata_json, confidence, conflict, first_seen_run_id, last_seen_run_id) "
            "SELECT graph_key_version, source_canonical_key, edge_kind, target_canonical_key, "
            "identity_metadata_json, identity_metadata_hash, metadata_json, confidence, "
            "conflict, :run, :run FROM (SELECT *, row_number() OVER (PARTITION BY "
            "graph_key_version, source_canonical_key, edge_kind, target_canonical_key, "
            "identity_metadata_hash ORDER BY family_ordinal) AS proposal "
            "FROM temp.stage_canonical_edges) WHERE proposal = 1 "
            "ON CONFLICT(graph_key_version, source_canonical_key, edge_kind, "
            "target_canonical_key, identity_metadata_hash) DO UPDATE SET "
            "identity_metadata_json = excluded.identity_metadata_json, "
            "metadata_json = excluded.metadata_json, confidence = excluded.confidence, "
            "conflict = excluded.conflict, last_seen_run_id = excluded.last_seen_run_id",
            None,
        ),
    ),
    "canonical_node_evidence": (
        (
            "SELECT 1 FROM temp.stage_canonical_node_evidence staged WHERE NOT EXISTS ("
            "SELECT 1 FROM canonical_nodes node WHERE node.graph_key_version = "
            "staged.graph_key_version AND node.canonical_key = staged.canonical_key) "
            "OR NOT EXISTS (SELECT 1 FROM canonical_evidence evidence WHERE "
            "evidence.run_id = ? AND evidence.graph_key_version = staged.graph_key_version "
            "AND evidence.evidence_key = staged.evidence_key)",
            "canonical node-evidence reference is missing",
        ),
        (
            "INSERT INTO canonical_node_evidence(canonical_node_id, canonical_evidence_id, "
            "link_kind) SELECT DISTINCT node.id, evidence.id, staged.link_kind "
            "FROM temp.stage_canonical_node_evidence staged "
            "JOIN canonical_nodes node ON node.graph_key_version = staged.graph_key_version "
            "AND node.canonical_key = staged.canonical_key "
            "JOIN canonical_evidence evidence ON evidence.run_id = :run "
            "AND evidence.graph_key_version = staged.graph_key_version "
            "AND evidence.evidence_key = staged.evidence_key WHERE true "
            "ON CONFLICT DO NOTHING",
            None,
        ),
    ),
    "canonical_edge_evidence": (
        (
            "SELECT 1 FROM temp.stage_canonical_edge_evidence staged WHERE NOT EXISTS ("
            "SELECT 1 FROM canonical_edges edge WHERE edge.graph_key_version = "
            "staged.graph_key_version AND edge.source_canonical_key = "
            "staged.source_canonical_key AND edge.edge_kind = staged.edge_kind "
            "AND edge.target_canonical_key = staged.target_canonical_key "
            "AND edge.identity_metadata_hash = staged.identity_metadata_hash) "
            "OR NOT EXISTS (SELECT 1 FROM canonical_evidence evidence WHERE "
            "evidence.run_id = ? AND evidence.graph_key_version = staged.graph_key_version "
            "AND evidence.evidence_key = staged.evidence_key)",
            "canonical edge-evidence reference is missing",
        ),
        (
            "INSERT INTO canonical_edge_evidence(canonical_edge_id, canonical_evidence_id, "
            "link_kind) SELECT DISTINCT edge.id, evidence.id, staged.link_kind "
            "FROM temp.stage_canonical_edge_evidence staged "
            "JOIN canonical_edges edge ON edge.graph_key_version = staged.graph_key_version "
            "AND edge.source_canonical_key = staged.source_canonical_key "
            "AND edge.edge_kind = staged.edge_kind "
            "AND edge.target_canonical_key = staged.target_canonical_key "
            "AND edge.identity_metadata_hash = staged.identity_metadata_hash "
            "JOIN canonical_evidence evidence ON evidence.run_id = :run "
            "AND evidence.graph_key_version = staged.graph_key_version "
            "AND evidence.evidence_key = staged.evidence_key WHERE true "
            "ON CONFLICT DO NOTHING",
            None,
        ),
    ),
}


def family_statements(family: StageFamily) -> tuple[tuple[str, str | None], ...]:
    return MERGE_STATEMENTS[family]


__all__ = ("MERGE_STATEMENTS", "family_statements")
