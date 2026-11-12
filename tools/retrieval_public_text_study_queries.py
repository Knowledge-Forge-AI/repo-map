"""Study batch import, exact read and observed-ANN statement over study relations (study sections 8-9).

The exact statement mirrors ``build_candidate_query_sql`` and the ANN statement
mirrors ``build_hnsw_ann_statement``: the same distance operator, tie order,
evidence predicate, evidence order/limit and statuses, with only the study
relation names, study/arm/batch filters, the study profile fields and one
in-statement relation fence substituted. No planner, cost or statistics setting
appears; the ANN plan is observed, never predicted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from common_lore_index.storage.semantic_candidate_sql import accepted_candidate_publication_sql
from common_lore_index.storage.semantic_candidates import (
    PGVECTOR_VERSION, CandidatePublication, EmbeddingProfile, checked_vector,
)
from common_lore_index.storage.sql_core import sql_literal
from retrieval_public_text_request import ARM_PTX, ARM_V1
from retrieval_public_text_study_catalog import StudyCatalog
from retrieval_public_text_study_schema import (
    BATCH_ID, DIMENSIONS, MAX_ROWS, StudyEmbeddingProfile, StudySchemaRefusal, digest_ok, profile_fields, qualified,
)
from retrieval_semantic_ann_scope import match_candidate_publication
from retrieval_semantic_provenance import VerifiedPublicationPin

EXACT_STATUSES = frozenset({"study_relation_changed", "stale_publication", "enrichment_unavailable", "ok"})
ANN_STATUSES = frozenset({
    "study_relation_changed", "stale_publication", "stale_rebuild", "profile_mismatch", "unsupported_extension",
    "rebuild_integrity_mismatch", "source_scope_unavailable", "ok",
})
_LINK = "link.link_kind NOT IN ('inferred', 'inferred_from_edge')"
_ROW_ORDER = 'distance, canonical_key COLLATE "C", source_binding_id COLLATE "C"'


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise StudySchemaRefusal(code)


@dataclass(frozen=True)
class StudyEntry:
    canonical_key: str
    source_binding_id: str
    snapshot_id: str
    input_digest: str
    descriptor_identity: str | None
    truncated: bool
    vector: tuple[float, ...] = field(repr=False)


@dataclass(frozen=True)
class StudyBatch:
    batch_id: str
    generation: int
    arm: str
    profile: EmbeddingProfile | StudyEmbeddingProfile
    input_identity: str
    seal_identity: str
    capability: str
    entries: tuple[StudyEntry, ...] = field(repr=False)


def publication_snapshots(publication: CandidatePublication, pin: VerifiedPublicationPin) -> dict[str, str]:
    """The candidate publication must be the pin's current publication, binding for binding."""
    try:
        publication.validate()
        match_candidate_publication(publication, pin)
    except Exception:
        raise StudySchemaRefusal("study_publication_mismatch") from None
    portable = publication.publication.receipt.portable
    assert portable is not None
    snapshots = {binding: snapshot for binding, _, snapshot in portable.snapshot_vector}
    _require(snapshots == {b: s[1] for b, s in pin.snapshot_by_binding().items()}, "study_publication_mismatch")
    return snapshots


def validate_batch(catalog: StudyCatalog, batch: StudyBatch, publication: CandidatePublication,
                   pin: VerifiedPublicationPin) -> None:
    """Type/field/vector/descriptor validation; nothing reaches SQL before this passes."""
    _require(type(catalog) is StudyCatalog and type(batch) is StudyBatch and type(batch.generation) is int
             and batch.generation in (1, 2) and batch.arm in (ARM_V1, ARM_PTX) and batch.generation == pin.generation
             and batch.batch_id == catalog.names.batch_id(batch.generation, batch.arm)
             and digest_ok(batch.input_identity) and digest_ok(batch.seal_identity)
             and type(batch.entries) is tuple and 1 <= len(batch.entries) <= MAX_ROWS, "study_import_invalid")
    profile_fields(batch.profile, batch.arm)
    snapshots = publication_snapshots(publication, pin)
    seen: set[tuple[str, str]] = set()
    for entry in batch.entries:
        _require(type(entry) is StudyEntry and type(entry.canonical_key) is str
                 and 1 <= len(entry.canonical_key) <= 4096 and "\x00" not in entry.canonical_key
                 and type(entry.truncated) is bool and digest_ok(entry.input_digest)
                 and (entry.canonical_key, entry.source_binding_id) not in seen, "study_import_invalid")
        seen.add((entry.canonical_key, entry.source_binding_id))
        _require(entry.source_binding_id in pin.admitted_public_bindings
                 and entry.source_binding_id not in pin.denied_bindings
                 and snapshots.get(entry.source_binding_id) == entry.snapshot_id, "study_entry_mismatch")
        _require((entry.descriptor_identity is None and entry.truncated is False) if batch.arm == ARM_V1
                 else digest_ok(entry.descriptor_identity), "study_import_invalid")
        try:
            checked_vector(entry.vector, DIMENSIONS)
        except (TypeError, ValueError):
            raise StudySchemaRefusal("study_import_invalid") from None
    # The capability is the sealed arm's own: a v2 arm may be token_partial from query-only truncation with
    # untruncated documents, while any truncated document requires token_partial; v1 is always complete.
    allowed = ("complete",) if batch.arm == ARM_V1 else ("complete", "token_partial")
    documents_truncated = any(entry.truncated for entry in batch.entries)
    _require(batch.capability in allowed and (not documents_truncated or batch.capability == "token_partial"),
             "study_import_invalid")


def _vector(values: Sequence[float]) -> str:
    return sql_literal("[" + ",".join(str(float(v)) for v in values) + "]")


def build_import_sql(catalog: StudyCatalog, batch: StudyBatch, publication: CandidatePublication,
                     pin: VerifiedPublicationPin) -> str:
    """One REPEATABLE READ transaction mirroring production import, with an exact-count rollback."""
    validate_batch(catalog, batch, publication, pin)
    identity, profile = profile_fields(batch.profile, batch.arm)
    accepted = accepted_candidate_publication_sql(publication)
    receipt = publication.publication.receipt
    portable = receipt.portable
    assert portable is not None
    names, entry_table = catalog.names, qualified(catalog.names.entry_table)
    metadata = {
        "batch_id": batch.batch_id, "study_identity": names.study_identity, "arm": batch.arm,
        "repository_identity": publication.repository_identity, "receipt_identity": publication.receipt_identity,
        **dict(zip(receipt.generations.field_names(), (str(v) for v in receipt.generations.values()), strict=True)),
        "publication_bundle_id": portable.publication_bundle_id, "snapshot_manifest_id": portable.snapshot_manifest_id,
        "profile_identity": identity, **profile, "privacy_class": "public", "input_identity": batch.input_identity,
        "seal_identity": batch.seal_identity, "capability": batch.capability,
    }
    values = ",\n".join(
        "(" + ", ".join((sql_literal(e.canonical_key), sql_literal(e.source_binding_id), sql_literal(e.snapshot_id),
                         sql_literal(e.input_digest),
                         "NULL::text" if e.descriptor_identity is None else sql_literal(e.descriptor_identity),
                         "true" if e.truncated else "false", _vector(e.vector) + "::repomap_vector.vector")) + ")"
        for e in batch.entries)
    count = len(batch.entries)
    return f"""BEGIN ISOLATION LEVEL REPEATABLE READ;
DO $ptx_import$
BEGIN
    IF current_user <> {sql_literal(names.owner)} OR NOT {catalog.fence_sql()} THEN
        RAISE EXCEPTION 'study relation identity changed';
    END IF;
    IF NOT EXISTS (WITH {accepted} SELECT 1 FROM accepted) THEN
        RAISE EXCEPTION 'study publication is not current and accepted';
    END IF;
END;
$ptx_import$;
INSERT INTO {qualified(names.batch_table)} ({", ".join(metadata)}, generation, run_id, dimensions, row_count)
VALUES ({", ".join(sql_literal(value) for value in metadata.values())}, {batch.generation},
    {publication.publication.run_id}, {DIMENSIONS}, {count});
WITH input(canonical_key, source_binding_id, snapshot_id, input_digest, descriptor_identity, truncated, embedding)
    AS (VALUES {values}),
{accepted}
INSERT INTO {entry_table} (batch_id, arm, canonical_key, source_binding_id, snapshot_id, input_digest,
    descriptor_identity, truncated, dimensions, embedding)
SELECT {sql_literal(batch.batch_id)}, {sql_literal(batch.arm)}, input.canonical_key, input.source_binding_id,
    input.snapshot_id, input.input_digest, input.descriptor_identity, input.truncated, {DIMENSIONS}, input.embedding
FROM input JOIN accepted ON true JOIN public.canonical_nodes node
    ON node.repository_id = accepted.repository_id AND node.canonical_key = input.canonical_key
    AND node.graph_key_version = 1 AND node.last_seen_run_id = accepted.id
WHERE EXISTS (SELECT 1 FROM public.canonical_node_evidence link
    JOIN public.canonical_evidence evidence ON evidence.id = link.canonical_evidence_id
    WHERE link.canonical_node_id = node.id AND evidence.run_id = accepted.id
      AND evidence.repository_id = accepted.repository_id
      AND evidence.metadata_json->>'binding_id' = input.source_binding_id
      AND evidence.metadata_json->>'snapshot_id' = input.snapshot_id);
DO $ptx_count$
BEGIN
    IF (SELECT count(*) FROM {entry_table} WHERE batch_id = {sql_literal(batch.batch_id)}) <> {count} THEN
        RAISE EXCEPTION 'study batch contains a node without accepted source evidence';
    END IF;
END;
$ptx_count$;
COMMIT;"""


@dataclass(frozen=True)
class StudyQuery:
    """One bound vector read against one study batch; there is no caller SQL, table or role."""

    catalog: StudyCatalog
    batch_id: str
    arm: str
    profile: EmbeddingProfile | StudyEmbeddingProfile
    publication: CandidatePublication
    source_binding_id: str
    vector: tuple[float, ...] = field(repr=False)
    limit: int = 20
    evidence_limit: int = 5

    def validate(self) -> StudyQuery:
        match = BATCH_ID.fullmatch(self.batch_id) if type(self.batch_id) is str else None
        _require(type(self.catalog) is StudyCatalog and match is not None and self.arm in (ARM_V1, ARM_PTX)
                 and self.batch_id == self.catalog.names.batch_id(int(match.group(1)), self.arm), "study_import_invalid")
        profile_fields(self.profile, self.arm)
        try:
            self.publication.validate()
            checked_vector(self.vector, DIMENSIONS)
        except (TypeError, ValueError):
            raise StudySchemaRefusal("study_import_invalid") from None
        _require(type(self.limit) is int and 1 <= self.limit <= 100 and type(self.evidence_limit) is int
                 and 1 <= self.evidence_limit <= 20 and type(self.source_binding_id) is str
                 and 1 <= len(self.source_binding_id) <= 4096 and "\x00" not in self.source_binding_id,
                 "study_import_invalid")
        return self


def _metadata_filters(query: StudyQuery) -> str:
    receipt = query.publication.publication.receipt
    portable = receipt.portable
    assert portable is not None
    _identity, profile = profile_fields(query.profile, query.arm)
    values = (*profile.items(), *zip(receipt.generations.field_names(), receipt.generations.values(), strict=True),
              ("publication_bundle_id", portable.publication_bundle_id),
              ("snapshot_manifest_id", portable.snapshot_manifest_id))
    return " AND ".join(f"batch.{name} = {sql_literal(str(value))}" for name, value in values)


def _batch_join(query: StudyQuery) -> str:
    return (f"{qualified(query.catalog.names.batch_table)} batch JOIN accepted"
            f" ON batch.repository_identity = {sql_literal(query.publication.repository_identity)}"
            " AND batch.run_id = accepted.id"
            f" AND batch.receipt_identity = {sql_literal(query.publication.receipt_identity)}"
            f" WHERE (SELECT ok FROM fence) AND batch.batch_id = {sql_literal(query.batch_id)}"
            f" AND batch.study_identity = {sql_literal(query.catalog.names.study_identity)}"
            f" AND batch.arm = {sql_literal(query.arm)}")


def _profile_filters(query: StudyQuery) -> str:
    identity, _profile = profile_fields(query.profile, query.arm)
    return (f"batch.profile_identity = {sql_literal(identity)} AND batch.dimensions = {DIMENSIONS}"
            f" AND batch.privacy_class = 'public' AND {_metadata_filters(query)}")


def _extension_sql() -> str:
    return ("EXISTS (SELECT 1 FROM pg_catalog.pg_extension ext JOIN pg_catalog.pg_namespace n"
            f" ON n.oid = ext.extnamespace WHERE ext.extname = 'vector' AND ext.extversion = '{PGVECTOR_VERSION}'"
            " AND n.nspname = 'repomap_vector')")


def _evidence_exists() -> str:
    return ("EXISTS (SELECT 1 FROM public.canonical_node_evidence link JOIN public.canonical_evidence evidence"
            " ON evidence.id = link.canonical_evidence_id WHERE link.canonical_node_id = node.id"
            " AND evidence.repository_id = accepted.repository_id AND evidence.run_id = accepted.id"
            " AND evidence.graph_key_version = 1 AND evidence.metadata_json->>'binding_id' = entry.source_binding_id"
            f" AND evidence.metadata_json->>'snapshot_id' = entry.snapshot_id AND {_LINK})")


def _expanded(alias: str, query: StudyQuery, *, graph_key: bool) -> str:
    graph = " AND evidence.graph_key_version = 1" if graph_key else ""
    return (f"SELECT {alias}.*, (SELECT COALESCE(json_agg(row_to_json(items)), '[]'::json) FROM ("
            "SELECT evidence.evidence_key, evidence.path, evidence.start_line, evidence.end_line, evidence.raw_kind,"
            " evidence.extractor, evidence.extractor_version, evidence.confidence"
            " FROM public.canonical_node_evidence link JOIN public.canonical_evidence evidence"
            " ON evidence.id = link.canonical_evidence_id JOIN accepted ON evidence.repository_id = accepted.repository_id"
            f" WHERE link.canonical_node_id = {alias}.node_id AND evidence.run_id = accepted.id{graph}"
            f" AND evidence.metadata_json->>'binding_id' = {alias}.source_binding_id"
            f" AND evidence.metadata_json->>'snapshot_id' = {alias}.snapshot_id AND {_LINK}"
            f' ORDER BY evidence.evidence_key COLLATE "C" LIMIT {query.evidence_limit}) items) AS evidence FROM {alias}')


_SELECTED = ("node.id AS node_id, node.canonical_key, node.kind, node.display_name, node.confidence, node.conflict,"
             " entry.source_binding_id, entry.input_digest, entry.snapshot_id, entry.descriptor_identity")


def build_exact_statement(query: StudyQuery) -> str:
    """Mirror of the production exact query with study substitutions and the relation fence."""
    q = query.validate()
    entry = qualified(q.catalog.names.entry_table)
    return f"""WITH {accepted_candidate_publication_sql(q.publication)},
    fence AS MATERIALIZED (SELECT {q.catalog.fence_sql()} AS ok),
    matching AS MATERIALIZED (
        SELECT batch.* FROM {_batch_join(q)} AND {_profile_filters(q)}
          AND batch.row_count = (SELECT count(*) FROM {entry} e WHERE e.batch_id = batch.batch_id)
          AND {_extension_sql()}
    ), distances AS MATERIALIZED (
        SELECT {_SELECTED},
            entry.embedding OPERATOR(repomap_vector.<=>) {_vector(q.vector)}::repomap_vector.vector AS distance
        FROM matching JOIN accepted ON accepted.id = matching.run_id
        JOIN {entry} entry ON entry.batch_id = matching.batch_id AND entry.arm = matching.arm
        JOIN public.canonical_nodes node ON node.repository_id = accepted.repository_id
          AND node.canonical_key = entry.canonical_key
        WHERE node.graph_key_version = 1 AND node.last_seen_run_id = accepted.id
          AND entry.source_binding_id = {sql_literal(q.source_binding_id)}
          AND repomap_vector.vector_dims(entry.embedding) = {DIMENSIONS} AND {_evidence_exists()}
    ), nearest AS MATERIALIZED (
        SELECT * FROM distances ORDER BY {_ROW_ORDER} LIMIT {q.limit}
    ), expanded AS ({_expanded("nearest", q, graph_key=False)})
    SELECT json_build_object(
        'status', CASE WHEN NOT (SELECT ok FROM fence) THEN 'study_relation_changed'
            WHEN NOT EXISTS (SELECT 1 FROM accepted) THEN 'stale_publication'
            WHEN NOT EXISTS (SELECT 1 FROM matching) THEN 'enrichment_unavailable' ELSE 'ok' END,
        'candidates', (SELECT COALESCE(json_agg(row_to_json(expanded) ORDER BY {_ROW_ORDER}), '[]'::json)
            FROM expanded))::text"""


def exact_sql(query: StudyQuery) -> str:
    return (f'SET ROLE "{query.catalog.names.owner}";\nBEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n'
            f"{build_exact_statement(query)};\nCOMMIT;\n")


def build_ann_statement(query: StudyQuery, *, snapshot_id: str, ann_scan_limit: int) -> str:
    """Mirror of the maintained HNSW statement; ORDER BY equals the owned index expression; column ``result``."""
    q = query.validate()
    _require(type(ann_scan_limit) is int and q.limit <= ann_scan_limit <= MAX_ROWS
             and type(snapshot_id) is str and 1 <= len(snapshot_id) <= 4096, "study_import_invalid")
    entry = qualified(q.catalog.names.entry_table)
    order = (f"(entry.embedding::repomap_vector.vector({DIMENSIONS})) OPERATOR(repomap_vector.<=>) "
             f"{_vector(q.vector)}::repomap_vector.vector({DIMENSIONS})")
    scope = "scope.source_binding_id = entry.source_binding_id AND scope.snapshot_id = entry.snapshot_id"
    return f"""WITH source_scope(source_binding_id, snapshot_id) AS MATERIALIZED (
    VALUES ({sql_literal(q.source_binding_id)}, {sql_literal(snapshot_id)})),
{accepted_candidate_publication_sql(q.publication)},
fence AS MATERIALIZED (SELECT {q.catalog.fence_sql()} AS ok),
candidate_batch AS (SELECT batch.* FROM {_batch_join(q)}),
profile_batch AS (SELECT batch.* FROM candidate_batch batch WHERE {_profile_filters(q)}),
extension_status AS (SELECT {_extension_sql()} AS available),
matching AS MATERIALIZED (
    SELECT batch.* FROM profile_batch batch CROSS JOIN extension_status
    WHERE extension_status.available AND batch.row_count BETWEEN 1 AND {MAX_ROWS}
      AND batch.row_count = (SELECT count(*) FROM {entry} e WHERE e.batch_id = batch.batch_id)
),
ann_scan AS (
    SELECT {_SELECTED}, {order} AS distance
    FROM matching JOIN accepted ON accepted.id = matching.run_id
    JOIN {entry} entry ON entry.batch_id = matching.batch_id
    JOIN source_scope scope ON {scope}
    JOIN public.canonical_nodes node ON node.repository_id = accepted.repository_id
      AND node.canonical_key = entry.canonical_key
    WHERE node.graph_key_version = 1 AND node.last_seen_run_id = accepted.id
      AND entry.source_binding_id = {sql_literal(q.source_binding_id)}
      AND entry.batch_id = {sql_literal(q.batch_id)} AND entry.dimensions = {DIMENSIONS}
      AND entry.arm = {sql_literal(q.arm)}
      AND repomap_vector.vector_dims(entry.embedding) = {DIMENSIONS} AND {_evidence_exists()}
    ORDER BY {order}
    FETCH FIRST {ann_scan_limit} ROWS WITH TIES
),
ranked AS MATERIALIZED (SELECT * FROM ann_scan ORDER BY {_ROW_ORDER} LIMIT {q.limit}),
expanded AS ({_expanded("ranked", q, graph_key=True)})
SELECT json_build_object(
    'status', CASE WHEN NOT (SELECT ok FROM fence) THEN 'study_relation_changed'
        WHEN NOT EXISTS (SELECT 1 FROM accepted) THEN 'stale_publication'
        WHEN NOT EXISTS (SELECT 1 FROM candidate_batch) THEN 'stale_rebuild'
        WHEN NOT EXISTS (SELECT 1 FROM profile_batch) THEN 'profile_mismatch'
        WHEN NOT EXISTS (SELECT 1 FROM extension_status WHERE available) THEN 'unsupported_extension'
        WHEN NOT EXISTS (SELECT 1 FROM matching) THEN 'rebuild_integrity_mismatch'
        WHEN NOT EXISTS (SELECT 1 FROM matching batch JOIN {entry} entry ON entry.batch_id = batch.batch_id
            JOIN source_scope scope ON {scope}) THEN 'source_scope_unavailable'
        ELSE 'ok' END,
    'candidates', (SELECT COALESCE(json_agg(row_to_json(expanded) ORDER BY {_ROW_ORDER}), '[]'::json) FROM expanded),
    'ann_scan_limit', {ann_scan_limit}
)::text AS result"""


def plan_selects_index(plan: object, *, index_name: str, table_name: str) -> bool:
    """True only for an executed Index Scan node on the owned index and the entry relation."""
    if not (type(plan) is list and len(plan) == 1 and isinstance(plan[0], dict) and isinstance(plan[0].get("Plan"), dict)):
        return False
    pending: list[object] = [plan[0]["Plan"]]
    while pending:
        node = pending.pop()
        if not isinstance(node, dict):
            return False
        loops = node.get("Actual Loops")
        if (node.get("Node Type"), node.get("Index Name"), node.get("Relation Name")) == (
                "Index Scan", index_name, table_name) and type(loops) is int and loops >= 1:
            return True
        children = node.get("Plans", [])
        if not isinstance(children, list):
            return False
        pending.extend(children)
    return False


def candidate_payload(payload: object, *, statuses: frozenset[str], limit: int) -> tuple[str, tuple[dict[str, Any], ...]]:
    """(status, rows) from one statement payload; any other shape refuses."""
    _require(isinstance(payload, Mapping) and payload.get("status") in statuses, "study_import_invalid")
    assert isinstance(payload, Mapping)
    rows = payload.get("candidates")
    _require(isinstance(rows, list) and len(rows) <= limit and all(isinstance(row, dict) for row in rows)
             and (payload["status"] == "ok" or not rows), "study_import_invalid")
    assert isinstance(rows, list)
    return str(payload["status"]), tuple(rows)


__all__ = [
    "ANN_STATUSES", "EXACT_STATUSES", "StudyBatch", "StudyEntry", "StudyQuery", "build_ann_statement",
    "build_exact_statement", "build_import_sql", "candidate_payload", "exact_sql", "plan_selects_index",
    "publication_snapshots", "validate_batch",
]
