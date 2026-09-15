"""SQL builders for RepoMap storage load and upsert preparation."""

from __future__ import annotations

import json
from collections.abc import Sequence

from repomap_kg.storage.rows import (
    CanonicalEdgeEvidenceLinkRow,
    CanonicalEdgeRow,
    CanonicalEvidenceRow,
    CanonicalLoadRows,
    CanonicalNodeEvidenceLinkRow,
    CanonicalNodeRow,
    FileRow,
    RawObservationRow,
    canonical_json_text,
)
from repomap_kg.storage.publication import RunPublicationReceipt
from repomap_kg.storage.repository_identity import repository_upsert_sql
from repomap_kg.storage.sql_core import sql_bool, sql_int_or_null, sql_literal

__all__ = (
    "build_canonical_ingest_sql",
    "repository_run_prefix_sql",
    "run_completion_statements",
    "canonical_ingest_statements",
    "file_load_summary_select_sql",
    "canonical_load_summary_select_sql",
    "file_upsert_sql",
    "raw_observation_upsert_sql",
    "canonical_node_upsert_sql",
    "canonical_edge_upsert_sql",
    "canonical_evidence_upsert_sql",
    "canonical_node_evidence_upsert_sql",
    "canonical_edge_evidence_upsert_sql",
)


def build_canonical_ingest_sql(
    raw_rows: Sequence[RawObservationRow],
    canonical_rows: CanonicalLoadRows,
    *,
    repository_name: str,
    root_path: str,
    git_commit: str | None = None,
    run_status: str = "complete",
    repository_identity: str | None = None,
) -> str:
    statements = repository_run_prefix_sql(
        repository_name=repository_name,
        root_path=root_path,
        git_commit=git_commit,
        run_status=run_status,
        repository_identity=repository_identity,
    )
    statements.extend(canonical_ingest_statements(raw_rows, canonical_rows))
    statements.extend(run_completion_statements(run_status))
    statements.extend(
        [
            "COMMIT;",
            canonical_load_summary_select_sql(raw_rows, canonical_rows),
        ]
    )
    return "\n".join(statements) + "\n"


def repository_run_prefix_sql(
    *,
    repository_name: str,
    root_path: str,
    git_commit: str | None,
    run_status: str,
    publication_receipt: RunPublicationReceipt | None = None,
    repository_identity: str | None = None,
) -> list[str]:
    receipt_columns = ""
    receipt_values = ""
    if publication_receipt is not None:
        values = publication_receipt.to_mapping()
        receipt_columns = ", " + ", ".join(values)
        receipt_values = ", " + ", ".join(
            sql_literal(str(value)) for value in values.values()
        )
    return [
        "BEGIN;",
        repository_upsert_sql(repository_name, root_path, repository_identity),
        "\\gset repo_",
        (
            "INSERT INTO runs(repository_id, git_commit, status"
            f"{receipt_columns}) VALUES ("
            f":repo_id, {sql_literal(git_commit)}, {sql_literal(run_status)}"
            f"{receipt_values}) "
            "RETURNING id"
        ),
        "\\gset run_",
    ]


def run_completion_statements(run_status: str) -> list[str]:
    if run_status != "complete":
        return []
    return [
        (
            "UPDATE runs "
            "SET finished_at = now() "
            "WHERE id = :run_id AND status = 'complete';"
        )
    ]


def canonical_ingest_statements(
    raw_rows: Sequence[RawObservationRow],
    canonical_rows: CanonicalLoadRows,
) -> list[str]:
    statements: list[str] = []
    statements.extend(raw_observation_upsert_sql(row) for row in raw_rows)
    statements.extend(canonical_node_upsert_sql(row) for row in canonical_rows.nodes)
    statements.extend(canonical_edge_upsert_sql(row) for row in canonical_rows.edges)
    statements.extend(
        canonical_evidence_upsert_sql(row) for row in canonical_rows.evidence
    )
    statements.extend(
        canonical_node_evidence_upsert_sql(row)
        for row in canonical_rows.node_evidence_links
    )
    statements.extend(
        canonical_edge_evidence_upsert_sql(row)
        for row in canonical_rows.edge_evidence_links
    )
    return statements


def file_load_summary_select_sql(
    file_count: int, *, include_publication_receipt: bool = False
) -> str:
    receipt_fields = ""
    if include_publication_receipt:
        receipt_fields = "".join(
            f", '{field}', (SELECT runs.{field} FROM runs "
            "WHERE runs.id = :run_id::bigint)"
            for field in RunPublicationReceipt.field_names()
        )
    return (
        "SELECT json_build_object("
        "'repository_id', :repo_id::bigint, "
        "'run_id', :run_id::bigint, "
        f"'files', {file_count}{receipt_fields}"
        ")::text;"
    )


def canonical_load_summary_select_sql(
    raw_rows: Sequence[RawObservationRow],
    canonical_rows: CanonicalLoadRows,
) -> str:
    return _canonical_load_summary_select_sql_counts(
        raw_observations=len(raw_rows),
        canonical_nodes=len(canonical_rows.nodes),
        canonical_edges=len(canonical_rows.edges),
        canonical_evidence=len(canonical_rows.evidence),
        canonical_node_evidence_links=len(canonical_rows.node_evidence_links),
        canonical_edge_evidence_links=len(canonical_rows.edge_evidence_links),
    )


def _canonical_load_summary_select_sql_counts(
    *,
    raw_observations: int,
    canonical_nodes: int,
    canonical_edges: int,
    canonical_evidence: int,
    canonical_node_evidence_links: int,
    canonical_edge_evidence_links: int,
) -> str:
    return (
        "SELECT json_build_object("
        "'repository_id', :repo_id::bigint, "
        "'run_id', :run_id::bigint, "
        f"'raw_observations', {raw_observations}, "
        f"'canonical_nodes', {canonical_nodes}, "
        f"'canonical_edges', {canonical_edges}, "
        f"'canonical_evidence', {canonical_evidence}, "
        "'canonical_node_evidence_links', "
        f"{canonical_node_evidence_links}, "
        "'canonical_edge_evidence_links', "
        f"{canonical_edge_evidence_links}"
        ")::text;"
    )


def file_upsert_sql(row: FileRow) -> str:
    return (
        "INSERT INTO files("
        "repository_id, last_seen_run_id, path, language, role, content_hash, "
        "executable, generated, metadata_json"
        ") VALUES ("
        ":repo_id, :run_id, "
        f"{sql_literal(row.path)}, "
        f"{sql_literal(row.language)}, "
        f"{sql_literal(row.role)}, "
        f"{sql_literal(row.content_hash)}, "
        f"{sql_bool(row.executable)}, "
        f"{sql_bool(row.generated)}, "
        f"{sql_literal(json.dumps(row.metadata_json, sort_keys=True))}::jsonb"
        ") ON CONFLICT (repository_id, path) DO UPDATE SET "
        "last_seen_run_id = EXCLUDED.last_seen_run_id, "
        "language = EXCLUDED.language, "
        "role = EXCLUDED.role, "
        "content_hash = EXCLUDED.content_hash, "
        "executable = EXCLUDED.executable, "
        "generated = EXCLUDED.generated, "
        "metadata_json = EXCLUDED.metadata_json;"
    )


def raw_observation_upsert_sql(row: RawObservationRow) -> str:
    payload_json = canonical_json_text(row.payload_json)
    return "\n".join(
        [
            (
                "SELECT CAST("
                "'raw observation payload hash mismatch ' || now()::text "
                "AS integer) "
                "WHERE EXISTS ("
                "SELECT 1 FROM raw_observations "
                "WHERE run_id = :run_id "
                f"AND ordinal = {row.ordinal} "
                f"AND payload_hash <> {sql_literal(row.payload_hash)}"
                ");"
            ),
            (
                "INSERT INTO raw_observations("
                "repository_id, run_id, ordinal, schema_version, kind, source_id, "
                "path, payload_json, payload_hash"
                ") VALUES ("
                ":repo_id, :run_id, "
                f"{row.ordinal}, "
                f"{row.schema_version}, "
                f"{sql_literal(row.kind)}, "
                f"{sql_literal(row.source_id)}, "
                f"{sql_literal(row.path)}, "
                f"{sql_literal(payload_json)}::jsonb, "
                f"{sql_literal(row.payload_hash)}"
                ") ON CONFLICT (run_id, ordinal) DO UPDATE SET "
                "schema_version = EXCLUDED.schema_version, "
                "kind = EXCLUDED.kind, "
                "source_id = EXCLUDED.source_id, "
                "path = EXCLUDED.path, "
                "payload_json = EXCLUDED.payload_json, "
                "payload_hash = EXCLUDED.payload_hash;"
            ),
        ]
    )


def canonical_node_upsert_sql(row: CanonicalNodeRow) -> str:
    return (
        "INSERT INTO canonical_nodes("
        "repository_id, graph_key_version, canonical_key, kind, display_name, "
        "metadata_json, confidence, conflict, first_seen_run_id, last_seen_run_id"
        ") VALUES ("
        ":repo_id, "
        f"{row.graph_key_version}, "
        f"{sql_literal(row.canonical_key)}, "
        f"{sql_literal(row.kind)}, "
        f"{sql_literal(row.display_name)}, "
        f"{sql_literal(canonical_json_text(row.metadata_json))}::jsonb, "
        f"{sql_literal(row.confidence)}, "
        f"{sql_bool(row.conflict)}, "
        ":run_id, :run_id"
        ") ON CONFLICT (repository_id, graph_key_version, canonical_key) "
        "DO UPDATE SET "
        "kind = EXCLUDED.kind, "
        "display_name = EXCLUDED.display_name, "
        "metadata_json = EXCLUDED.metadata_json, "
        "confidence = EXCLUDED.confidence, "
        "conflict = EXCLUDED.conflict, "
        "last_seen_run_id = EXCLUDED.last_seen_run_id, "
        "updated_at = now();"
    )


def canonical_edge_upsert_sql(row: CanonicalEdgeRow) -> str:
    return (
        "INSERT INTO canonical_edges("
        "repository_id, graph_key_version, source_canonical_key, edge_kind, "
        "target_canonical_key, identity_metadata_json, identity_metadata_hash, "
        "metadata_json, confidence, conflict, first_seen_run_id, last_seen_run_id"
        ") VALUES ("
        ":repo_id, "
        f"{row.graph_key_version}, "
        f"{sql_literal(row.source_key)}, "
        f"{sql_literal(row.edge_kind)}, "
        f"{sql_literal(row.target_key)}, "
        f"{sql_literal(canonical_json_text(row.identity_metadata_json))}::jsonb, "
        f"{sql_literal(row.identity_metadata_hash)}, "
        f"{sql_literal(canonical_json_text(row.metadata_json))}::jsonb, "
        f"{sql_literal(row.confidence)}, "
        f"{sql_bool(row.conflict)}, "
        ":run_id, :run_id"
        ") ON CONFLICT ("
        "repository_id, graph_key_version, source_canonical_key, edge_kind, "
        "target_canonical_key, identity_metadata_hash"
        ") DO UPDATE SET "
        "identity_metadata_json = EXCLUDED.identity_metadata_json, "
        "metadata_json = EXCLUDED.metadata_json, "
        "confidence = EXCLUDED.confidence, "
        "conflict = EXCLUDED.conflict, "
        "last_seen_run_id = EXCLUDED.last_seen_run_id, "
        "updated_at = now();"
    )


def canonical_evidence_upsert_sql(row: CanonicalEvidenceRow) -> str:
    return (
        "INSERT INTO canonical_evidence("
        "repository_id, run_id, graph_key_version, raw_observation_id, "
        "evidence_key, raw_observation_ordinal, raw_schema_version, raw_kind, "
        "raw_source_id, path, start_line, end_line, extractor, "
        "extractor_version, confidence, metadata_json"
        ") SELECT "
        ":repo_id, :run_id, "
        f"{row.graph_key_version}, "
        "raw_observations.id, "
        f"{sql_literal(row.evidence_key)}, "
        f"{row.raw_observation_ordinal}, "
        f"{row.raw_schema_version}, "
        f"{sql_literal(row.raw_kind)}, "
        f"{sql_literal(row.raw_source_id)}, "
        f"{sql_literal(row.path)}, "
        f"{sql_int_or_null(row.start_line)}, "
        f"{sql_int_or_null(row.end_line)}, "
        f"{sql_literal(row.extractor)}, "
        f"{sql_literal(row.extractor_version)}, "
        f"{sql_literal(row.confidence)}, "
        f"{sql_literal(canonical_json_text(row.metadata_json))}::jsonb "
        "FROM raw_observations "
        "WHERE raw_observations.run_id = :run_id "
        f"AND raw_observations.ordinal = {row.raw_observation_ordinal} "
        "ON CONFLICT (run_id, graph_key_version, evidence_key) DO UPDATE SET "
        "raw_observation_id = EXCLUDED.raw_observation_id, "
        "raw_observation_ordinal = EXCLUDED.raw_observation_ordinal, "
        "raw_schema_version = EXCLUDED.raw_schema_version, "
        "raw_kind = EXCLUDED.raw_kind, "
        "raw_source_id = EXCLUDED.raw_source_id, "
        "path = EXCLUDED.path, "
        "start_line = EXCLUDED.start_line, "
        "end_line = EXCLUDED.end_line, "
        "extractor = EXCLUDED.extractor, "
        "extractor_version = EXCLUDED.extractor_version, "
        "confidence = EXCLUDED.confidence, "
        "metadata_json = EXCLUDED.metadata_json;"
    )


def canonical_node_evidence_upsert_sql(row: CanonicalNodeEvidenceLinkRow) -> str:
    return (
        "INSERT INTO canonical_node_evidence("
        "canonical_node_id, canonical_evidence_id, link_kind"
        ") SELECT canonical_nodes.id, canonical_evidence.id, "
        f"{sql_literal(row.link_kind)} "
        "FROM canonical_nodes "
        "JOIN canonical_evidence ON canonical_evidence.repository_id = :repo_id "
        "AND canonical_evidence.run_id = :run_id "
        f"AND canonical_evidence.evidence_key = {sql_literal(row.evidence_key)} "
        "WHERE canonical_nodes.repository_id = :repo_id "
        f"AND canonical_nodes.canonical_key = {sql_literal(row.canonical_key)} "
        "AND canonical_nodes.graph_key_version = "
        "canonical_evidence.graph_key_version "
        "ON CONFLICT DO NOTHING;"
    )


def canonical_edge_evidence_upsert_sql(row: CanonicalEdgeEvidenceLinkRow) -> str:
    return (
        "INSERT INTO canonical_edge_evidence("
        "canonical_edge_id, canonical_evidence_id, link_kind"
        ") SELECT canonical_edges.id, canonical_evidence.id, "
        f"{sql_literal(row.link_kind)} "
        "FROM canonical_edges "
        "JOIN canonical_evidence ON canonical_evidence.repository_id = :repo_id "
        "AND canonical_evidence.run_id = :run_id "
        f"AND canonical_evidence.evidence_key = {sql_literal(row.evidence_key)} "
        "WHERE canonical_edges.repository_id = :repo_id "
        f"AND canonical_edges.graph_key_version = {row.graph_key_version} "
        f"AND canonical_edges.source_canonical_key = {sql_literal(row.source_key)} "
        f"AND canonical_edges.edge_kind = {sql_literal(row.edge_kind)} "
        f"AND canonical_edges.target_canonical_key = {sql_literal(row.target_key)} "
        "AND canonical_edges.identity_metadata_hash = "
        f"{sql_literal(row.identity_metadata_hash)} "
        "AND canonical_edges.graph_key_version = "
        "canonical_evidence.graph_key_version "
        "ON CONFLICT DO NOTHING;"
    )
