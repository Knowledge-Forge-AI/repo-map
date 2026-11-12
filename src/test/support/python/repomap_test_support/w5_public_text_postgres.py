"""Disposable-cluster execution for the public-text study: psql, owned objects, exact and observed ANN.

Test support only. Every psql process uses ``-X`` and ``ON_ERROR_STOP=1`` and
removes ambient ``PGOPTIONS`` so no planner setting is inherited or forced. No
caller SQL, table, role or index name is accepted, and no role or grant is
added. Owned indexes are registered only in the immutable ``StudyCatalog``;
every use re-checks its complete child-object inventory. One ANN observation is
one psql process with ``-qAt0``: a read-write REPEATABLE READ transaction whose
analyzed TEMP CTAS and materialized rows come from the same execution. A batch
without a registered owned index never completes. Cleanup fences every recorded
object before any drop and proves each object's own absence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import os
import types
from typing import Any, TypedDict, cast

from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.psql import run_psql
from common_lore_index.storage.semantic_candidate_sql import accepted_candidate_publication_sql
from common_lore_index.storage.semantic_candidates import CandidatePublication, CandidateQuery, EmbeddingProfile, digest_json
from common_lore_index.storage.sql_core import sql_literal
from repomap_test_support.w5_experiment_postgres import PostgresHandle, _scope_for_query
from retrieval_public_text_descriptors import PublicTextPreparation
from retrieval_public_text_request import ARM_PTX, ARM_V1
from retrieval_public_text_response import ArmSeal, StudyGenerationSeal
from retrieval_public_text_study_catalog import (
    StudyCatalog, absence_sql, build_cleanup_sql, build_create_sql, build_index_sql, cleanup_objects, parse_absence,
    parse_index_catalog, parse_relation_state, relation_state_sql,
)
from retrieval_public_text_study_queries import (
    ANN_STATUSES, EXACT_STATUSES, StudyBatch, StudyEntry, StudyQuery, build_ann_statement, build_import_sql,
    candidate_payload, exact_sql, plan_selects_index,
)
from retrieval_public_text_study_schema import (
    StudyEmbeddingProfile, StudyNames, StudySchemaRefusal, index_catalog_sql, index_item_sql, quote,
)
from retrieval_semantic_ann_sql import DEFAULT_EF_SEARCH, DEFAULT_ITERATIVE_SCAN
from retrieval_semantic_experiment_contracts import ExperimentRefusal
from retrieval_semantic_generator_inputs import PublicGenerationInput
from retrieval_semantic_generator_kernel import SemanticMode
from retrieval_semantic_provenance import VerifiedPublicationPin

ANN_RECORD_COUNT = 5


def _env() -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop("PGOPTIONS", None)
    return environment


def run_study_sql(postgres: PostgresHandle, sql: str, *, nul: bool = False) -> str:
    """One psql process; ``nul`` selects the NUL record separator for the ANN transaction."""
    command = [postgres.psql_command, *postgres.psql_args, "-X", "-qAt0" if nul else "-qAt", "-v", "ON_ERROR_STOP=1"]
    return run_psql(command, input_text=sql, env=_env()).stdout


def _as_owner(names: StudyNames, sql: str) -> str:
    return f'SET ROLE "{names.owner}";\n{sql}\n'


def _json_object(stdout: str) -> dict[str, Any]:
    try:
        value = json.loads(stdout)
    except ValueError:
        raise StorageSchemaError("study readback did not return one JSON document") from None
    if not isinstance(value, dict):
        raise StorageSchemaError("study readback did not return an object")
    return value


def create_study_relations(postgres: PostgresHandle, names: StudyNames) -> StudyCatalog:
    """Create both relations and record them with their constraint-index children; no index registered yet."""
    payload = _json_object(run_study_sql(postgres, _as_owner(names, build_create_sql(names))))
    return StudyCatalog(parse_relation_state(payload, names))


def read_relation_state(postgres: PostgresHandle, names: StudyNames) -> dict[str, Any]:
    return _json_object(run_study_sql(postgres, _as_owner(names, relation_state_sql(names))))


def import_batch(postgres: PostgresHandle, catalog: StudyCatalog, batch: StudyBatch,
                 publication: CandidatePublication, pin: VerifiedPublicationPin) -> None:
    run_study_sql(postgres, _as_owner(catalog.names, build_import_sql(catalog, batch, publication, pin)))


def create_batch_index(postgres: PostgresHandle, catalog: StudyCatalog, batch_id: str) -> StudyCatalog:
    """Create one owned index behind the full fence; return the new catalog with it registered."""
    run_study_sql(postgres, _as_owner(catalog.names, build_index_sql(catalog, batch_id)))
    readback = run_study_sql(postgres, _as_owner(catalog.names, index_catalog_sql(catalog.names, batch_id)))
    return catalog.with_index(parse_index_catalog(_json_object(readback), catalog, batch_id))


def v1_entries(seal: ArmSeal, v1_input: PublicGenerationInput, pin: VerifiedPublicationPin) -> tuple[StudyEntry, ...]:
    """v1 vectors keyed by the original v1 representation digest; a refused v1 arm imports nothing."""
    if not (type(seal) is ArmSeal and seal.arm == ARM_V1 and seal.capability == "complete"
            and type(v1_input) is PublicGenerationInput):
        raise StudySchemaRefusal("study_entry_mismatch")
    documents = {doc.record_id: doc.representation for doc in v1_input.documents}
    snapshots = pin.snapshot_by_binding()
    entries = []
    for record in (r for r in seal.records if r.mode is SemanticMode.DOCUMENT):
        rep = documents.get(record.record_id[3:]) if record.record_id.startswith("v1.") else None
        if rep is None or rep.input_digest != record.source_identity or record.truncated or (
                snapshots.get(rep.source_binding_id, (0, None))[1] != rep.snapshot_id):
            raise StudySchemaRefusal("study_entry_mismatch")
        entries.append(StudyEntry(rep.canonical_key, rep.source_binding_id, rep.snapshot_id, rep.input_digest,
                                  None, False, record.vector))
    if not entries or len(entries) != len(documents):
        raise StudySchemaRefusal("study_entry_mismatch")
    return tuple(entries)


def v2_entries(seal: ArmSeal, preparation: PublicTextPreparation, pin: VerifiedPublicationPin) -> tuple[StudyEntry, ...]:
    """v2 entries equal the sealed descriptors one-to-one in preparation order, bound to the pin."""
    if not (type(seal) is ArmSeal and seal.arm == ARM_PTX and seal.capability in ("complete", "token_partial")
            and type(preparation) is PublicTextPreparation
            and preparation.publication_identity == str(digest_json(pin.to_dict()))):
        raise StudySchemaRefusal("study_entry_mismatch")
    sealed = [record for record in seal.records if record.mode is SemanticMode.DOCUMENT]
    if not sealed or [r.source_identity for r in sealed] != [doc.identity for doc in preparation.documents]:
        raise StudySchemaRefusal("study_entry_mismatch")
    snapshots = pin.snapshot_by_binding()
    entries = []
    for record, document in zip(sealed, preparation.documents, strict=True):
        d = document.descriptor
        if snapshots.get(d["source_binding_id"], (0, None))[1] != d["snapshot_id"]:
            raise StudySchemaRefusal("study_entry_mismatch")
        entries.append(StudyEntry(d["canonical_key"], d["source_binding_id"], d["snapshot_id"], d["input_digest"],
                                  document.identity, record.truncated, record.vector))
    return tuple(entries)


def sealed_batch(names: StudyNames, seal: StudyGenerationSeal, arm: str,
                 profile: EmbeddingProfile | StudyEmbeddingProfile, *, pin: VerifiedPublicationPin,
                 v1_input: PublicGenerationInput | None = None,
                 preparation: PublicTextPreparation | None = None) -> StudyBatch:
    """A batch whose generation, identities and capability are the actual sealed arm's, never inferred."""
    if not (type(seal) is StudyGenerationSeal and arm in (ARM_V1, ARM_PTX) and arm in seal.arms
            and type(pin) is VerifiedPublicationPin and seal.generation == pin.generation
            and seal.publication_identity == str(digest_json(pin.to_dict()))):
        raise StudySchemaRefusal("study_entry_mismatch")
    arm_seal = seal.arms[arm]
    if arm == ARM_V1 and v1_input is not None:
        entries = v1_entries(arm_seal, v1_input, pin)
    elif arm == ARM_PTX and preparation is not None:
        entries = v2_entries(arm_seal, preparation, pin)
    else:
        raise StudySchemaRefusal("study_entry_mismatch")
    return StudyBatch(names.batch_id(seal.generation, arm), seal.generation, arm, profile, seal.input_identity,
                      seal.seal_identity, arm_seal.capability, entries)


@dataclass(frozen=True)
class StudyRead:
    """One exact or ANN read: closed state/reason, private rows, public digests and lengths only."""

    state: str
    reason: str | None
    rows: tuple[dict[str, Any], ...] = field(default=(), repr=False)
    result_sha256: str | None = None
    result_length: int | None = None
    plan_sha256: str | None = None
    plan_length: int | None = None
    index_selected: bool | None = None
    records: Any = field(default=None, repr=False, compare=False)


def _digest(raw: bytes) -> tuple[str, int]:
    return "sha256:" + hashlib.sha256(raw).hexdigest(), len(raw)


def scoped_snapshot(publication: CandidatePublication, pin: VerifiedPublicationPin, binding_id: str) -> str:
    """Binding refusals through the unchanged ``_scope_for_query`` semantics, before any vector SQL."""
    query = cast(CandidateQuery, types.SimpleNamespace(publication=publication, source_binding_id=binding_id))
    scope = _scope_for_query(query, pin)
    return scope[0][1]


def exact_read(postgres: PostgresHandle, query: StudyQuery, pin: VerifiedPublicationPin) -> StudyRead:
    """Exact read in one REPEATABLE READ READ ONLY transaction as the owner; refusals precede SQL."""
    try:
        scoped_snapshot(query.publication, pin, query.source_binding_id)
        stdout = run_study_sql(postgres, exact_sql(query))
        status, rows = candidate_payload(_json_object(stdout), statuses=EXACT_STATUSES, limit=query.limit)
        pin.revalidate_current()
    except ExperimentRefusal as exc:
        return StudyRead("refused", exc.code)
    except (StorageSchemaError, StudySchemaRefusal, ValueError):
        return StudyRead("failed", "exact_sql_failed")
    if status != "ok":
        return StudyRead("refused" if status == "study_relation_changed" else "unavailable", status)
    sha, length = _digest(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return StudyRead("completed", None, rows, sha, length)


def temp_privilege(postgres: PostgresHandle, names: StudyNames) -> bool:
    """Separate preflight; absence means ``unavailable/temp_privilege_absent`` and no grant is ever added."""
    out = run_study_sql(postgres, _as_owner(names, "SELECT has_database_privilege(current_database(), 'TEMP');"))
    if out.strip() not in ("t", "f"):
        raise StorageSchemaError("TEMP privilege readback was malformed")
    return out.strip() == "t"


def _flight_sql(query: StudyQuery, stage: str, temp_name: str) -> str:
    index = query.catalog.index_for(query.batch_id)
    index_sql = "NULL::boolean" if index is None else (
        "EXISTS (SELECT 1 FROM pg_catalog.pg_class c JOIN pg_catalog.pg_index i ON i.indexrelid = c.oid"
        f" WHERE c.oid = '{index.oid}'::oid AND {index_item_sql('c', 'i')} = {sql_literal(index.item)})")
    return (f"SELECT json_build_object('stage', '{stage}', 'current_user', current_user,"
            " 'temp_privilege', has_database_privilege(current_database(), 'TEMP'),"
            f" 'relations_unchanged', {query.catalog.fence_sql()}, 'index_unchanged', {index_sql},"
            f" 'accepted', EXISTS (WITH {accepted_candidate_publication_sql(query.publication)} SELECT 1 FROM accepted),"
            " 'temp_persistence', (SELECT c.relpersistence::text FROM pg_catalog.pg_class c"
            f" WHERE c.oid = to_regclass({sql_literal('pg_temp.' + temp_name)})))::text;")


def ann_transaction_sql(query: StudyQuery, *, snapshot_id: str, temp_name: str, ann_scan_limit: int) -> str:
    """Preflight, EXPLAIN ANALYZE of a TEMP CTAS, its rows, postflight, COMMIT, then absence: five records."""
    statement = build_ann_statement(query, snapshot_id=snapshot_id, ann_scan_limit=ann_scan_limit)
    temp = quote(temp_name)
    return (f'SET ROLE "{query.catalog.names.owner}";\nBEGIN ISOLATION LEVEL REPEATABLE READ;\n'
            f"SET LOCAL hnsw.ef_search = '{DEFAULT_EF_SEARCH}';\n"
            f"SET LOCAL hnsw.iterative_scan = '{DEFAULT_ITERATIVE_SCAN}';\n"
            f"{_flight_sql(query, 'preflight', temp_name)}\n"
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)\nCREATE TEMP TABLE {temp} ON COMMIT DROP AS\n{statement};\n"
            f"SELECT result FROM pg_temp.{temp};\n{_flight_sql(query, 'postflight', temp_name)}\nCOMMIT;\n"
            f"SELECT to_regclass({sql_literal('pg_temp.' + temp_name)}) IS NULL;\n")


@dataclass(frozen=True)
class AnnRecords:
    """The five NUL-terminated records of one ANN transaction; raw plan/result bytes stay private."""

    preflight: Mapping[str, Any]
    plan: Any = field(repr=False)
    result: Mapping[str, Any] = field(repr=False)
    postflight: Mapping[str, Any]
    temp_dropped: bool
    plan_raw: bytes = field(repr=False)
    result_raw: bytes = field(repr=False)


class _StudyReadCommon(TypedDict):
    result_sha256: str
    result_length: int
    plan_sha256: str
    plan_length: int
    index_selected: bool
    records: AnnRecords


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(items)
    if len(result) != len(items):
        raise ValueError("duplicate JSON key")
    return result


def _no_constant(_value: str) -> Any:
    raise ValueError("non-finite JSON constant")


def parse_ann_records(stdout: object) -> AnnRecords | None:
    """Exactly five NUL-terminated records, else ``None`` (``failed/ann_output_shape``)."""
    if type(stdout) is not str or not stdout.endswith("\0"):
        return None
    parts = stdout[:-1].split("\0")
    if len(parts) != ANN_RECORD_COUNT or parts[4] not in ("t", "f"):
        return None
    try:
        decoded = [json.loads(part, object_pairs_hook=_pairs, parse_constant=_no_constant) for part in parts[:4]]
    except (ValueError, RecursionError):
        return None
    if not all(isinstance(decoded[i], dict) for i in (0, 2, 3)):
        return None
    return AnnRecords(decoded[0], decoded[1], decoded[2], decoded[3], parts[4] == "t",
                      parts[1].encode("utf-8"), parts[2].encode("utf-8"))


def _fenced(records: AnnRecords, query: StudyQuery) -> bool:
    flights, names = (records.preflight, records.postflight), query.catalog.names
    registered = query.catalog.index_for(query.batch_id) is not None
    return (
        (records.preflight.get("stage"), records.postflight.get("stage")) == ("preflight", "postflight")
        and all(f.get("current_user") == names.owner and f.get("temp_privilege") is True
                and f.get("relations_unchanged") is True and f.get("accepted") is True
                and f.get("index_unchanged") is (True if registered else None) for f in flights)
        and records.preflight.get("temp_persistence") is None and records.postflight.get("temp_persistence") == "t"
        and records.temp_dropped is True)


def classify_ann(records: AnnRecords | None, query: StudyQuery) -> StudyRead:
    """Shape, fences, then the registered-index plan check, then the result; no index never completes."""
    if records is None:
        return StudyRead("failed", "ann_output_shape")
    index = query.catalog.index_for(query.batch_id)
    plan_sha, plan_len = _digest(records.plan_raw)
    result_sha, result_len = _digest(records.result_raw)
    selected = index is not None and plan_selects_index(
        records.plan, index_name=index.name, table_name=query.catalog.names.entry_table)
    common: _StudyReadCommon = {
        "result_sha256": result_sha, "result_length": result_len, "plan_sha256": plan_sha,
        "plan_length": plan_len, "index_selected": selected, "records": records,
    }
    if not _fenced(records, query):
        return StudyRead("refused", "study_relation_changed", **common)
    if not selected:
        return StudyRead("unavailable", "index_not_selected", **common)
    try:
        status, rows = candidate_payload(records.result, statuses=ANN_STATUSES, limit=query.limit)
    except StudySchemaRefusal:
        return StudyRead("failed", "ann_result_malformed", **common)
    if status == "ok":
        return StudyRead("completed", None, rows, **common)
    return StudyRead("refused" if status == "study_relation_changed" else "unavailable", status, **common)


def observe_ann(postgres: PostgresHandle, query: StudyQuery, pin: VerifiedPublicationPin, *, task_id: str,
                repetition: int, ann_scan_limit: int | None = None) -> StudyRead:
    """One observed ANN cell; the owned index comes only from the query's catalog, never a caller argument."""
    names = query.catalog.names
    try:
        snapshot = scoped_snapshot(query.publication, pin, query.source_binding_id)
    except ExperimentRefusal as exc:
        return StudyRead("refused", exc.code)
    if not temp_privilege(postgres, names):
        return StudyRead("unavailable", "temp_privilege_absent")
    sql = ann_transaction_sql(
        query, snapshot_id=snapshot, temp_name=names.temp_name(query.batch_id, task_id, repetition),
        ann_scan_limit=query.limit if ann_scan_limit is None else ann_scan_limit)
    try:
        stdout = run_study_sql(postgres, sql, nul=True)
    except StorageSchemaError:
        return StudyRead("failed", "ann_sql_failed")
    return classify_ann(parse_ann_records(stdout), query)


@dataclass(frozen=True)
class CleanupResult:
    """Public cleanup outcome: closed status/reason and each object's own absence."""

    status: str
    reason: str | None
    objects: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, "reason": self.reason, "objects": [dict(item) for item in self.objects]}


def cleanup_study(postgres: PostgresHandle, names: StudyNames, catalog: StudyCatalog | None) -> CleanupResult:
    """Attempted once after creation (and on failure paths); a fence mismatch drops nothing."""
    if catalog is not None and catalog.names != names:
        raise StudySchemaRefusal("study_cleanup_readback")
    reason: str | None = None
    if catalog is not None:
        try:
            run_study_sql(postgres, _as_owner(names, build_cleanup_sql(catalog)))
        except StorageSchemaError:
            reason = "cleanup_failed:relation_identity_changed"
    objects = cleanup_objects(names, catalog)
    absent = parse_absence(_json_object(run_study_sql(postgres, _as_owner(names, absence_sql(names, objects)))),
                           names, objects)
    if reason is None and not all(absent):
        reason = "cleanup_failed:object_present"
    rows = tuple({"kind": kind, "absent": value} for (kind, _name, _oid), value in zip(objects, absent, strict=True))
    return CleanupResult("clean" if reason is None else "failed", reason, rows)


__all__ = [
    "ANN_RECORD_COUNT", "AnnRecords", "CleanupResult", "StudyRead", "ann_transaction_sql", "classify_ann",
    "cleanup_study", "create_batch_index", "create_study_relations", "exact_read", "import_batch", "observe_ann",
    "parse_ann_records", "read_relation_state", "run_study_sql", "scoped_snapshot", "sealed_batch", "temp_privilege",
    "v1_entries", "v2_entries",
]
