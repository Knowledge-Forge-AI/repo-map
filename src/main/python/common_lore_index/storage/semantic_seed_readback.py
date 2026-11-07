"""Configured stored-node retrieval with publication fencing and no inference."""

from __future__ import annotations

from collections.abc import Sequence
import math

from common_lore_index.storage.authority import GraphRunId
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.publication import RunPublicationReceipt, publication_receipt_from_mapping
from common_lore_index.storage.publication_readback import RunPublicationRecord
from common_lore_index.storage.readback_driver import execute_json_readback
from common_lore_index.storage.semantic_candidate_readback import candidate_provenance, observe_candidate_capability
from common_lore_index.storage.semantic_candidates import (
    CandidatePublication, CandidateResult, EmbeddingProfile, checked_identity, unavailable,
)
from common_lore_index.storage.semantic_seed import SimilarNodesQuery
from common_lore_index.storage.semantic_seed_sql import build_seed_query_sql
from common_lore_index.storage.sql_core import sql_literal

_REFUSALS = frozenset({
    "stale_publication", "enrichment_unavailable", "profile_mismatch",
    "seed_node_missing", "seed_embedding_missing", "seed_ambiguous",
    "stale_rebuild", "foreign_publication",
})


def query_similar_nodes(
    psql_args: Sequence[str], *, query: SimilarNodesQuery,
    repository_identity: str, psql_command: str = "psql",
    password: str | None = None, root_path: str = "",
) -> CandidateResult:
    """Resolve a graph receipt, then fence seed and results in one read snapshot."""
    query.validate()
    if query.selected is False:
        return unavailable("disabled")
    checked_identity(repository_identity)
    reason = observe_candidate_capability(psql_args, psql_command=psql_command, password=password)
    if reason is not None:
        return unavailable(reason)
    fields = ", ".join(f"'{field}', run.{field}" for field in RunPublicationReceipt.field_names())
    sql = f"""SELECT json_build_object('publication', (
        SELECT json_build_object('run_id', run.id, {fields}) FROM public.runs run
        JOIN public.repositories repo ON repo.id = run.repository_id
        WHERE repo.repository_identity = {sql_literal(repository_identity)} AND run.status = 'complete'
        ORDER BY run.id DESC LIMIT 1))::text;"""
    try:
        payload = execute_json_readback(sql, psql_args=psql_args, psql_command=psql_command,
            password=password, label="seed publication", expected_shape="object")
    except StorageSchemaError:
        raise StorageSchemaError("semantic seed publication query failed") from None
    assert isinstance(payload, dict)
    record = payload.get("publication")
    if record is None:
        return unavailable("publication_unaccepted")
    if not isinstance(record, dict) or type(record.get("run_id")) is not int or record["run_id"] <= 0:
        raise StorageSchemaError("malformed seed publication readback")
    try:
        receipt = publication_receipt_from_mapping(record)
        if receipt is None or receipt.portable is None:
            return unavailable("publication_unaccepted")
        publication = CandidatePublication(repository_identity,
            RunPublicationRecord(GraphRunId(record["run_id"]), receipt)).validate()
    except ValueError:
        return unavailable("publication_unaccepted")
    return query_seed_candidates(psql_args, publication=publication, query=query,
        psql_command=psql_command, password=password)


def query_seed_candidates(
    psql_args: Sequence[str], *, publication: CandidatePublication, query: SimilarNodesQuery,
    psql_command: str = "psql", password: str | None = None,
) -> CandidateResult:
    """Exact SQL owner after capability observation; errors remain query errors."""
    query.validate()
    if query.selected is False:
        return unavailable("disabled")
    try:
        payload = execute_json_readback(build_seed_query_sql(publication, query),
            psql_args=psql_args, psql_command=psql_command, password=password,
            label="semantic seed candidates", expected_shape="object")
    except StorageSchemaError:
        raise StorageSchemaError("semantic seed query failed") from None
    assert isinstance(payload, dict)
    status = payload.get("status")
    if isinstance(status, str) and status in _REFUSALS:
        return unavailable(status)
    rows, seed, profile_data = payload.get("candidates"), payload.get("seed"), payload.get("profile")
    if status != "ok" or not isinstance(rows, list) or len(rows) > query.limit:
        raise StorageSchemaError("malformed seed candidate readback")
    if not isinstance(seed, dict) or not isinstance(profile_data, dict):
        raise StorageSchemaError("malformed seed candidate readback")
    try:
        profile = EmbeddingProfile(**profile_data).validate()
    except (TypeError, ValueError):
        raise StorageSchemaError("malformed seed profile readback") from None
    if profile.identity != query.profile_identity or profile.dimensions != query.dimensions:
        raise StorageSchemaError("seed profile identity mismatch")
    portable = publication.publication.receipt.portable
    assert portable is not None
    snapshots = {binding: snapshot for binding, _, snapshot in portable.snapshot_vector}
    if (seed.get("canonical_key") != query.canonical_key
        or not isinstance(seed.get("source_binding_id"), str)
        or seed.get("source_binding_id") not in snapshots
        or snapshots[seed["source_binding_id"]] != seed.get("snapshot_id")
        or (query.source_binding_id is not None and seed.get("source_binding_id") != query.source_binding_id)):
        raise StorageSchemaError("malformed seed identity readback")
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("canonical_key"), str)
            or not 1 <= len(row["canonical_key"]) <= 4096
            or not isinstance(row.get("source_binding_id"), str)
            or type(row.get("distance")) not in (int, float)
            or not math.isfinite(row["distance"]) or not 0 <= row["distance"] <= 2
            or (row.get("canonical_key"), row.get("source_binding_id")) ==
                (seed["canonical_key"], seed["source_binding_id"])
            or row.get("source_binding_id") not in snapshots
            or snapshots[row["source_binding_id"]] != row.get("snapshot_id")
            or not isinstance(row.get("evidence"), list) or not 1 <= len(row["evidence"]) <= query.evidence_limit):
            raise StorageSchemaError("malformed seed candidate readback")
    provenance = candidate_provenance(publication, profile, query.rebuild_id)
    provenance["seed"] = seed
    provenance["snapshot_contract"] = "receipt-fenced seed and candidates in one SQL statement"
    return CandidateResult("ok", None, tuple(rows), provenance)
