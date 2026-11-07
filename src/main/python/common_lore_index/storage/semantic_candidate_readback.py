"""Optional query owner using the maintained PostgreSQL JSON readback seam."""

from __future__ import annotations

from collections.abc import Sequence

from common_lore_index.storage.authority import GraphRunId
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.publication import RunPublicationReceipt, publication_receipt_from_mapping
from common_lore_index.storage.publication_readback import RunPublicationRecord
from common_lore_index.storage.sql_core import sql_literal
from common_lore_index.storage.readback_driver import execute_json_readback
from common_lore_index.storage.semantic_candidate_sql import (
    CAPABILITY_PROBE_SQL, build_candidate_query_sql, build_embedding_profiles_sql,
)
from common_lore_index.storage.semantic_candidates import (
    CandidatePublication, CandidateQuery, CandidateResult, EmbeddingProfile, PGVECTOR_VERSION, unavailable,
    EmbeddingProfilesQuery, EmbeddingProfilesResult, profiles_unavailable, validated_profile_entry, checked_identity,
)


def query_semantic_candidates(
    psql_args: Sequence[str], *, query: CandidateQuery,
    psql_command: str = "psql", password: str | None = None,
    root_path: str = "", repository_identity: str | None = None,
) -> CandidateResult:
    """Read bounded candidates; construction and disabled calls perform no IO."""
    if query.selected is False:
        return unavailable("disabled")
    query.validate()
    if repository_identity is not None and repository_identity != query.publication.repository_identity:
        return unavailable("graph_scope_mismatch")
    reason = observe_candidate_capability(psql_args, psql_command=psql_command, password=password)
    if reason is not None:
        return unavailable(reason)
    try:
        payload = execute_json_readback(
            build_candidate_query_sql(query), label="semantic candidates", psql_args=psql_args,
            psql_command=psql_command, password=password, expected_shape="object",
        )
    except StorageSchemaError:
        raise StorageSchemaError("semantic candidate query failed") from None
    assert isinstance(payload, dict)
    status = payload.get("status")
    if status in {"stale_publication", "enrichment_unavailable"}:
        return unavailable(status)
    rows = payload.get("candidates")
    if status != "ok" or not isinstance(rows, list) or len(rows) > query.limit or any(not isinstance(row, dict) for row in rows):
        raise StorageSchemaError("malformed candidate readback")
    return CandidateResult("ok", None, tuple(rows), candidate_provenance(
        query.publication, query.profile, query.rebuild_id
    ))


def observe_candidate_capability(
    psql_args: Sequence[str], *, psql_command: str = "psql", password: str | None = None,
) -> str | None:
    """Only optional-capability probe failures become bounded unavailability."""
    try:
        facts = execute_json_readback(
            CAPABILITY_PROBE_SQL, label="candidate capability", psql_args=psql_args,
            psql_command=psql_command, password=password, expected_shape="object",
        )
    except StorageSchemaError:
        return "observation_failed"
    assert isinstance(facts, dict)
    if facts.get("installed_version") is None:
        return "extension_absent"
    if (facts.get("installed_version"), facts.get("installation_schema")) != (
        PGVECTOR_VERSION, "repomap_vector"
    ):
        return "extension_unsupported"
    if facts.get("schema_version") != "repomap-enrichment-schema:1" or facts.get("objects_present") is not True:
        return "enrichment_schema_absent_or_unsupported"
    return None


def candidate_provenance(
    publication: CandidatePublication, profile: EmbeddingProfile, rebuild_id: str,
) -> dict[str, object]:
    receipt = publication.publication.receipt
    return {
        "repository_identity": publication.repository_identity,
        "run_id": publication.publication.run_id,
        "receipt_identity": publication.receipt_identity,
        "publication": receipt.public_mapping(),
        "generations": dict(zip(receipt.generations.field_names(), receipt.generations.values(), strict=True)),
        "profile": profile.__dict__, "profile_identity": profile.identity,
        "rebuild_id": rebuild_id, "privacy_class": "public", "search": "exact",
        "input_digest_validation": "enrichment_principal_assertion",
    }

_PROFILE_REFUSALS = frozenset({
    "stale_publication", "extension_unsupported", "enrichment_schema_absent_or_unsupported",
    "no_import", "stale_rebuild", "invalid_rebuild",
})


def query_embedding_profiles(
    psql_args: Sequence[str], *, query: EmbeddingProfilesQuery, repository_identity: str,
    psql_command: str = "psql", password: str | None = None, root_path: str = "",
) -> EmbeddingProfilesResult:
    query.validate()
    if query.selected is False:
        return profiles_unavailable("disabled")
    checked_identity(repository_identity)
    reason = observe_candidate_capability(psql_args, psql_command=psql_command, password=password)
    if reason is not None:
        return profiles_unavailable(reason)
    fields = ", ".join(f"'{field}', run.{field}" for field in RunPublicationReceipt.field_names())
    sql = f"""SELECT json_build_object('publication', (
        SELECT json_build_object('run_id', run.id, {fields}) FROM public.runs run
        JOIN public.repositories repo ON repo.id = run.repository_id
        WHERE repo.repository_identity = {sql_literal(repository_identity)} AND run.status = 'complete'
        ORDER BY run.id DESC LIMIT 1))::text;"""
    payload = _read(sql, psql_args, psql_command, password)
    record = payload.get("publication")
    if record is None:
        return profiles_unavailable("publication_unaccepted")
    try:
        publication = _publication(record, repository_identity)
    except (KeyError, TypeError, ValueError):
        return profiles_unavailable("publication_unaccepted")
    payload = _read(build_embedding_profiles_sql(publication, query), psql_args, psql_command, password)
    return _profiles_result(payload, publication, query)


def _publication(record: object, repository_identity: str) -> CandidatePublication:
    if not isinstance(record, dict) or type(record.get("run_id")) is not int or record["run_id"] <= 0:
        raise ValueError("invalid publication")
    receipt = publication_receipt_from_mapping(record)
    if receipt is None or receipt.portable is None:
        raise ValueError("unaccepted publication")
    bindings = [binding for binding, _, _ in receipt.portable.snapshot_vector]
    if len(bindings) != len(set(bindings)):
        raise ValueError("ambiguous publication source scope")
    return CandidatePublication(repository_identity,
        RunPublicationRecord(GraphRunId(record["run_id"]), receipt)).validate()


def _read(sql: str, psql_args: Sequence[str], psql_command: str, password: str | None) -> dict:
    try:
        payload = execute_json_readback(sql, psql_args=psql_args, psql_command=psql_command,
            password=password, label="embedding profiles", expected_shape="object")
    except StorageSchemaError:
        raise StorageSchemaError("embedding profile query failed") from None
    if not isinstance(payload, dict):
        raise StorageSchemaError("malformed embedding profile readback")
    return payload


def _profiles_result(payload: dict, publication: CandidatePublication,
                     query: EmbeddingProfilesQuery) -> EmbeddingProfilesResult:
    status = payload.get("status")
    if isinstance(status, str) and status in _PROFILE_REFUSALS:
        return profiles_unavailable(status)
    rows = payload.get("profiles")
    excluded = payload.get("has_excluded_rebuilds")
    if (status != "ok" or not isinstance(rows, list) or not 1 <= len(rows) <= query.limit + 1
            or type(excluded) is not bool):
        raise StorageSchemaError("malformed embedding profile readback")
    try:
        entries = [validated_profile_entry(row, publication) for row in rows]
    except (KeyError, TypeError, ValueError):
        return profiles_unavailable("invalid_identity")
    identities = [entry["rebuild_id"] for entry in entries]
    if len(identities) != len(set(identities)):
        return profiles_unavailable("ambiguous_identity")
    entries.sort(key=lambda entry: entry["rebuild_id"])
    receipt = publication.publication.receipt
    return EmbeddingProfilesResult("ok", profiles=tuple(entries[:query.limit]),
        has_more=len(entries) > query.limit, has_excluded_rebuilds=excluded, provenance={
            "repository_identity": publication.repository_identity,
            "run_id": publication.publication.run_id,
            "receipt_identity": publication.receipt_identity,
            "publication": receipt.public_mapping(),
            "generations": dict(zip(receipt.generations.field_names(), receipt.generations.values(), strict=True)),
            "privacy_class": "public", "pgvector_version": "0.8.7",
            "snapshot_contract": "receipt-fenced metadata and source evidence in one SQL statement",
        })
