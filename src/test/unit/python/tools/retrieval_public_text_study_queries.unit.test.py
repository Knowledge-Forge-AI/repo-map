"""Study import validation, exact/ANN statement equivalence, five-record parsing and plan-node checks.

Also covers the support owner's seal-bound batch (a parser-backed synthetic seal
with query-only truncation) and its ANN classification: a batch without a
registered owned index never completes, whatever its plan names.
"""

from __future__ import annotations

from dataclasses import replace
import json
import re
from typing import Any, cast

import pytest

from common_lore_index.storage.authority import GraphRunId
from common_lore_index.storage.publication_readback import RunPublicationRecord
from common_lore_index.storage.semantic_candidate_sql import accepted_candidate_publication_sql, build_candidate_query_sql
from common_lore_index.storage.semantic_candidates import CandidatePublication, CandidateQuery, EmbeddingProfile
from repomap_test_support.semantic_candidate_fixtures import candidate_query
from repomap_test_support.w5_public_text_artifacts import SyntheticStudy, synthetic_raw_component
from repomap_test_support.w5_public_text_postgres import AnnRecords, classify_ann, parse_ann_records, sealed_batch
from repomap_test_support.w5_semantic_support import make_w5_verified_pin
from retrieval_public_text_request import ARM_PTX, ARM_V1, encode_dual_arm_request
from retrieval_public_text_response import StudyGenerationSeal, seal_dual_arm_result
from retrieval_public_text_study_catalog import StudyCatalog, parse_index_catalog, parse_relation_state
from retrieval_public_text_study_queries import (
    StudyBatch, StudyEntry, StudyQuery, build_ann_statement, build_exact_statement, build_import_sql,
    candidate_payload, exact_sql, plan_selects_index, validate_batch,
)
from retrieval_public_text_study_schema import (
    BATCH_COLUMNS, ENTRY_COLUMNS, OWNER, StudyEmbeddingProfile, StudyNames, StudySchemaRefusal, index_comment,
)
from retrieval_semantic_ann_sql import build_hnsw_ann_statement
from retrieval_semantic_generator_kernel import SemanticMode

NAMES = StudyNames("sha256:" + "1" * 64)
STUDY = StudyEmbeddingProfile("synthetic", "1", "fixture", "1")
V1 = EmbeddingProfile("synthetic", "1", "fixture", "1", 384)
DIGEST = "sha256:" + "d" * 64
FORBIDDEN = re.compile(r"\b(?:TABLE|INDEX|SCHEMA|ROLE|EXTENSION)\s+IF\s+(?:NOT\s+)?EXISTS|CASCADE|\bGRANT\b|\bREVOKE\b|\bANALYZE\b|enable_|random_page_cost|^\s*SET\b",
                       re.I | re.M)


def _catalog() -> StudyCatalog:
    keys = {"batch": [("p", ["batch_id"]), ("u", ["batch_id", "arm", "dimensions"]),
                      ("u", ["study_identity", "generation", "arm"])],
            "entry": [("p", ["batch_id", "canonical_key", "source_binding_id"])]}

    def relation(key: str, oid: int) -> dict[str, Any]:
        columns = BATCH_COLUMNS if key == "batch" else ENTRY_COLUMNS
        kinds = ["c"] * 14 + ["p", "u", "u"] if key == "batch" else ["c"] * 4 + ["f", "p"]
        indexes = [{"oid": oid * 10 + n, "name": f"ptx_{key}_c{n}", "contype": t, "columns": c,
                    "access_method": "btree", "has_predicate": False, "has_expressions": False, "valid": True,
                    "ready": True, "item": f"index|{oid * 10 + n}|ptx_{key}_c{n}|{oid}|btree|true|true|true||{OWNER}|p"}
                   for n, (t, c) in enumerate(keys[key], 1)]
        return {"oid": oid, "schema": "repomap_enrichment", "name": getattr(NAMES, key + "_table"), "owner": OWNER,
                "relkind": "r", "relpersistence": "p", "comment": NAMES.comment(key), "definition_sha256": "a" * 64,
                "columns": [list(c) for c in columns], "constraint_kinds": kinds, "constraint_indexes": indexes,
                "children": [i["item"] for i in indexes] + [f"rls|{oid}|false|false"]}
    return StudyCatalog(parse_relation_state({"batch": relation("batch", 11), "entry": relation("entry", 12)}, NAMES))


def _with_index(catalog: StudyCatalog, batch_id: str) -> StudyCatalog:
    name, comment = NAMES.index_name(batch_id), index_comment(NAMES, batch_id)
    payload = {"present": True, "index_oid": 301, "table_oid": 12, "index_schema": "repomap_enrichment",
               "index_name": name, "table_name": NAMES.entry_table, "attribute_count": 1, "key_count": 1,
               "access_method": "hnsw", "opclass_schema": "repomap_vector", "opclass_name": "vector_cosine_ops",
               "is_valid": True, "is_ready": True, "owner": OWNER, "comment": comment,
               "expression": "((embedding)::repomap_vector.vector(384))",
               "predicate": f"((batch_id = '{batch_id}'::text) AND (dimensions = 384))", "reloptions": [],
               "item": f"index|301|{name}|12|hnsw|true|true|true|{comment}|{OWNER}|p"}
    return catalog.with_index(parse_index_catalog(payload, catalog, batch_id))


def _axis(index: int) -> tuple[float, ...]:
    return tuple(1.0 if position == index else 0.0 for position in range(384))


class _Fixture:
    def __init__(self) -> None:
        self.pin = make_w5_verified_pin(backend="postgresql")
        self.publication = CandidatePublication(self.pin.repository_identity,
                                                RunPublicationRecord(GraphRunId(self.pin.run_id), self.pin.receipt))
        self.binding = sorted(self.pin.admitted_public_bindings)[0]
        self.snapshot = self.pin.snapshot_by_binding()[self.binding][1]
        self.catalog = _catalog()

    def entry(self, key: str = "sym:a", **changes: Any) -> StudyEntry:
        base = StudyEntry(key, self.binding, self.snapshot, DIGEST, DIGEST, False, _axis(0))
        return replace(base, **changes)

    def batch(self, arm: str = ARM_PTX, entries: tuple[StudyEntry, ...] | None = None, **changes: Any) -> StudyBatch:
        if entries is None:
            entries = (self.entry(),) if arm == ARM_PTX else (self.entry(descriptor_identity=None),)
        profile = STUDY if arm == ARM_PTX else V1
        base = StudyBatch(NAMES.batch_id(1, arm), 1, arm, profile, DIGEST, DIGEST, "complete", entries)
        return replace(base, **changes)

    def query(self, arm: str = ARM_PTX, **changes: Any) -> StudyQuery:
        base = StudyQuery(self.catalog, NAMES.batch_id(1, arm), arm, STUDY if arm == ARM_PTX else V1,
                          self.publication, self.binding, _axis(1))
        return replace(base, **changes)


def _code(call: Any, *args: Any) -> str:
    with pytest.raises(StudySchemaRefusal) as error:
        call(*args)
    return error.value.code


def test_import_sql_is_one_fenced_transaction_with_exact_count_rollback() -> None:
    f = _Fixture()
    sql = build_import_sql(f.catalog, f.batch(ARM_V1, entries=(f.entry(descriptor_identity=None),
                                                               f.entry("sym:b", descriptor_identity=None))),
                           f.publication, f.pin)
    assert sql.startswith("BEGIN ISOLATION LEVEL REPEATABLE READ;") and sql.rstrip().endswith("COMMIT;")
    assert FORBIDDEN.search(sql) is None
    assert accepted_candidate_publication_sql(f.publication) in sql and f.catalog.fence_sql() in sql
    assert ") <> 2 THEN" in sql and sql.count("NULL::text") == 2 and "RAISE EXCEPTION" in sql
    assert "evidence.metadata_json->>'snapshot_id' = input.snapshot_id" in sql


@pytest.mark.parametrize(("arm", "change", "code"), [
    (ARM_PTX, {"batch_id": NAMES.batch_id(2, ARM_PTX)}, "study_import_invalid"),
    (ARM_PTX, {"generation": 2, "batch_id": NAMES.batch_id(2, ARM_PTX)}, "study_import_invalid"),
    (ARM_PTX, {"input_identity": "sha256:bad"}, "study_import_invalid"),
    (ARM_PTX, {"entries": ()}, "study_import_invalid"),
    (ARM_V1, {"capability": "token_partial"}, "study_import_invalid"),
    (ARM_PTX, {"capability": "refused"}, "study_import_invalid"),
    (ARM_PTX, {"profile": V1}, "study_profile_invalid"),
    (ARM_V1, {"profile": STUDY}, "study_profile_invalid"),
])
def test_batch_field_refusals_precede_sql(arm: str, change: dict[str, Any], code: str) -> None:
    f = _Fixture()
    assert _code(build_import_sql, f.catalog, f.batch(arm, **change), f.publication, f.pin) == code


def test_entry_refusals_cover_duplicates_scope_vectors_descriptors_and_caps() -> None:
    f = _Fixture()
    cases = [
        (ARM_PTX, (f.entry(), f.entry()), "study_import_invalid"),
        (ARM_PTX, (f.entry("bad\x00key"),), "study_import_invalid"),
        (ARM_PTX, (f.entry(source_binding_id="bind1:" + "9" * 64),), "study_entry_mismatch"),
        (ARM_PTX, (f.entry(snapshot_id="snap1:" + "0" * 64),), "study_entry_mismatch"),
        (ARM_PTX, (f.entry(descriptor_identity=None),), "study_import_invalid"),
        (ARM_V1, (f.entry(),), "study_import_invalid"),
        (ARM_V1, (f.entry(descriptor_identity=None, truncated=True),), "study_import_invalid"),
        (ARM_PTX, (f.entry(vector=tuple(0.5 for _ in range(384))),), "study_import_invalid"),
        (ARM_PTX, (f.entry(vector=_axis(0)[:383]),), "study_import_invalid"),
        (ARM_PTX, (f.entry(truncated=1),), "study_import_invalid"),
        (ARM_PTX, (f.entry(input_digest="sha256:" + "D" * 64),), "study_import_invalid"),
        (ARM_PTX, tuple(f.entry(f"sym:{i}") for i in range(501)), "study_import_invalid"),
    ]
    for arm, entries, code in cases:
        assert _code(validate_batch, f.catalog, f.batch(arm, entries=entries), f.publication, f.pin) == code


def test_document_truncation_requires_token_partial_and_query_only_truncation_is_allowed() -> None:
    f = _Fixture()
    truncated = (f.entry(truncated=True),)
    validate_batch(f.catalog, f.batch(entries=truncated, capability="token_partial"), f.publication, f.pin)
    assert _code(validate_batch, f.catalog, f.batch(entries=truncated), f.publication, f.pin) == "study_import_invalid"
    validate_batch(f.catalog, f.batch(capability="token_partial"), f.publication, f.pin)
    assert _code(validate_batch, _catalog().record, f.batch(), f.publication, f.pin) == "study_import_invalid"


def test_parser_backed_query_only_truncation_binds_the_sealed_arm_capability(tmp_path: Any) -> None:
    """A real parsed response whose only truncated record is the v2 query yields a token_partial v2 batch."""
    study = SyntheticStudy(tmp_path)
    value = study.build()
    query = next(i for i, row in enumerate(value.layout) if row.arm == ARM_PTX and row.mode is SemanticMode.QUERY)
    response = synthetic_raw_component(tmp_path / "model", encode_dual_arm_request(value),
                                       truncated=frozenset({query})).parse()
    seal = seal_dual_arm_result(value, response, refresh=study.build, scope=study.scope)
    assert (seal.arms[ARM_PTX].capability, seal.arms[ARM_PTX].truncated_query_task_ids) == ("token_partial", ("cal-01",))
    assert seal.arms[ARM_PTX].truncated_document_identities == () and seal.arms[ARM_V1].capability == "complete"
    batch = sealed_batch(NAMES, seal, ARM_PTX, STUDY, pin=study.pin, preparation=value.preparation)
    assert batch.capability == "token_partial" and not any(entry.truncated for entry in batch.entries)
    assert (batch.seal_identity, batch.input_identity) == (seal.seal_identity, seal.input_identity)
    assert sealed_batch(NAMES, seal, ARM_V1, V1, pin=study.pin, v1_input=value.v1).capability == "complete"
    with pytest.raises(StudySchemaRefusal):
        sealed_batch(NAMES, seal, ARM_PTX, STUDY, pin=study.pin)
    with pytest.raises(StudySchemaRefusal):
        sealed_batch(NAMES, cast(StudyGenerationSeal, seal.arms[ARM_PTX]), ARM_PTX, STUDY,
                     pin=study.pin, preparation=value.preparation)


def test_foreign_publication_is_refused_before_sql() -> None:
    f = _Fixture()
    foreign = candidate_query().publication
    assert _code(build_import_sql, f.catalog, f.batch(), foreign, f.pin) == "study_publication_mismatch"


def _statuses(sql: str) -> set[str]:
    return set(re.findall(r"THEN '([a-z_]+)'", sql)) | set(re.findall(r"ELSE '([a-z_]+)' END", sql))


def test_exact_statement_preserves_production_order_ties_evidence_and_statuses() -> None:
    f = _Fixture()
    query = f.query(ARM_V1)
    study = build_exact_statement(query)
    production = build_candidate_query_sql(CandidateQuery(
        f.publication, V1, "rebuild-fixture", _axis(1), selected=True, source_binding_id=f.binding))
    for fragment in ('ORDER BY distance, canonical_key COLLATE "C", source_binding_id COLLATE "C"',
                     "LIMIT 20", 'ORDER BY evidence.evidence_key COLLATE "C" LIMIT 5', "OPERATOR(repomap_vector.<=>)",
                     "link.link_kind NOT IN ('inferred', 'inferred_from_edge')", accepted_candidate_publication_sql(f.publication),
                     "node.graph_key_version = 1 AND node.last_seen_run_id = accepted.id"):
        assert fragment in study and fragment in production
    assert _statuses(study) == _statuses(production) | {"study_relation_changed"}
    assert f"batch.study_identity = '{NAMES.study_identity}'" in study and f"batch.arm = '{ARM_V1}'" in study
    assert "repomap_enrichment.rebuilds" not in study and f.catalog.fence_sql() in study
    assert FORBIDDEN.search(study) is None
    wrapped = exact_sql(query)
    assert wrapped.startswith('SET ROLE "repomap_w5_hnsw_owner";\nBEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;')


def test_ann_statement_mirrors_maintained_hnsw_statement_with_index_shaped_order() -> None:
    f = _Fixture()
    query = f.query(ARM_PTX, limit=3)
    study = build_ann_statement(query, snapshot_id=f.snapshot, ann_scan_limit=3)
    production = build_hnsw_ann_statement(CandidateQuery(
        f.publication, V1, "rebuild-fixture", _axis(1), selected=True, limit=3, source_binding_id=f.binding),
        source_scope=((f.binding, f.snapshot),), ann_scan_limit=3)
    assert _statuses(study) == _statuses(production) | {"study_relation_changed"}
    order = "(entry.embedding::repomap_vector.vector(384)) OPERATOR(repomap_vector.<=>)"
    assert f"ORDER BY {order}" in study and "FETCH FIRST 3 ROWS WITH TIES" in study
    assert "FETCH FIRST 3 ROWS WITH TIES" in production and ")::text AS result" in study
    assert f"entry.batch_id = '{query.batch_id}' AND entry.dimensions = 384" in study
    assert "evidence.graph_key_version = 1" in study and FORBIDDEN.search(study) is None
    for limit in (2, 501, True):
        assert _code(lambda value=limit: build_ann_statement(query, snapshot_id=f.snapshot, ann_scan_limit=value)) \
            == "study_import_invalid"


@pytest.mark.parametrize("change", [
    {"batch_id": StudyNames("sha256:" + "2" * 64).batch_id(1, ARM_PTX)}, {"batch_id": NAMES.batch_id(1, ARM_V1)},
    {"limit": 0},
    {"limit": 101}, {"evidence_limit": 21}, {"source_binding_id": "bind\x00"}, {"vector": _axis(0)[:10]},
    {"profile": V1},
])
def test_query_validation_refuses_foreign_or_unbounded_reads(change: dict[str, Any]) -> None:
    f = _Fixture()
    with pytest.raises(StudySchemaRefusal):
        f.query(ARM_PTX, **change).validate()


def _node(**fields: Any) -> dict[str, Any]:
    return {"Node Type": "Index Scan", "Index Name": NAMES.index_name(NAMES.batch_id(1, ARM_PTX)),
            "Relation Name": NAMES.entry_table, "Actual Loops": 1, **fields}


def test_plan_check_requires_executed_owned_index_scan_on_entry_relation() -> None:
    index, table = NAMES.index_name(NAMES.batch_id(1, ARM_PTX)), NAMES.entry_table
    nested = [{"Plan": {"Node Type": "Limit", "Plans": [{"Node Type": "Nested Loop", "Plans": [_node()]}]}}]
    assert plan_selects_index(nested, index_name=index, table_name=table)
    for plan in ([{"Plan": _node(**{"Index Name": "other_idx"})}], [{"Plan": _node(**{"Actual Loops": 0})}],
                 [{"Plan": _node(**{"Node Type": "Bitmap Index Scan"})}], [{"Plan": {"Node Type": "Seq Scan"}}],
                 [{"Plan": _node(**{"Relation Name": "embeddings"})}], [{"Plan": _node()}, {"Plan": _node()}],
                 [{"Plan": {"Node Type": "Sort", "Plans": {"bad": 1}}}], {"Plan": _node()}, []):
        assert not plan_selects_index(plan, index_name=index, table_name=table)


def test_candidate_payload_refuses_unknown_status_overflow_and_rows_on_refusal() -> None:
    assert candidate_payload({"status": "ok", "candidates": [{}]}, statuses=frozenset({"ok"}), limit=1)[0] == "ok"
    payloads: tuple[object, ...] = (
        {"status": "maybe", "candidates": []}, {"status": "ok", "candidates": [{}, {}]},
        {"status": "ok", "candidates": ["row"]}, {"status": "stale_publication", "candidates": [{}]},
        {"status": "ok"}, [])
    for payload in payloads:
        assert _code(lambda p=payload: candidate_payload(p, statuses=frozenset({"ok", "stale_publication"}), limit=1)) \
            == "study_import_invalid"


def _flight(stage: str, **changes: Any) -> dict[str, Any]:
    return {"stage": stage, "current_user": OWNER, "temp_privilege": True, "relations_unchanged": True,
            "index_unchanged": None, "accepted": True, "temp_persistence": None if stage == "preflight" else "t",
            **changes}


def _stdout(plan: object, result: object, *, pre: Any = None, post: Any = None, dropped: str = "t") -> str:
    records = [json.dumps(pre or _flight("preflight")), json.dumps(plan, indent=2), json.dumps(result),
               json.dumps(post or _flight("postflight")), dropped]
    return "".join(record + "\0" for record in records)


def test_five_nul_records_are_required_and_parsed_strictly() -> None:
    parsed = parse_ann_records(_stdout([{"Plan": _node()}], {"status": "ok", "candidates": []}))
    assert isinstance(parsed, AnnRecords) and parsed.temp_dropped and b"\n" in parsed.plan_raw
    good = _stdout([{"Plan": _node()}], {"status": "ok", "candidates": []})
    for bad in (good[:-1], good + "t\0", "\0".join(good.split("\0")[:4]) + "\0", good.replace("\0t\0", "\0x\0"),
                good.replace('"status"', '"status": 1, "status"', 1), good.replace('"ok"', "NaN", 1), b"bytes"):
        assert parse_ann_records(bad) is None


def test_classification_order_shape_fence_plan_then_result() -> None:
    f = _Fixture()
    query = replace(f.query(ARM_PTX, limit=1), catalog=_with_index(f.catalog, NAMES.batch_id(1, ARM_PTX)))
    registered = {"index_unchanged": True}
    plan, ok = [{"Plan": _node()}], {"status": "ok", "candidates": [{"canonical_key": "sym:a"}]}
    pre, post = _flight("preflight", **registered), _flight("postflight", **registered)
    assert classify_ann(None, query).reason == "ann_output_shape"
    completed = classify_ann(parse_ann_records(_stdout(plan, ok, pre=pre, post=post)), query)
    assert (completed.state, completed.index_selected, len(completed.rows)) == ("completed", True, 1)
    assert completed.plan_sha256 is not None and completed.plan_sha256.startswith("sha256:")
    assert "Plan" not in repr(completed)
    for stdout in (_stdout(plan, ok, pre=pre, post=post, dropped="f"),
                   _stdout(plan, ok, pre=pre, post={**post, "relations_unchanged": False}),
                   _stdout(plan, ok, pre={**pre, "accepted": False}, post=post),
                   _stdout(plan, ok, pre=pre, post={**post, "temp_persistence": "p"}),
                   _stdout(plan, ok, pre=pre, post={**post, "index_unchanged": False}),
                   _stdout(plan, ok)):
        assert (classify_ann(parse_ann_records(stdout), query).reason) == "study_relation_changed"
    seq = classify_ann(parse_ann_records(_stdout([{"Plan": {"Node Type": "Seq Scan"}}], ok, pre=pre, post=post)), query)
    assert (seq.state, seq.reason, seq.rows, seq.index_selected) == ("unavailable", "index_not_selected", (), False)
    stale = classify_ann(parse_ann_records(_stdout(plan, {"status": "profile_mismatch", "candidates": []}, pre=pre,
                                                   post=post)), query)
    assert (stale.state, stale.reason) == ("unavailable", "profile_mismatch")
    over = classify_ann(parse_ann_records(_stdout(plan, {"status": "ok", "candidates": [{}, {}]}, pre=pre, post=post)),
                        query)
    assert (over.state, over.reason) == ("failed", "ann_result_malformed")


def test_a_batch_without_a_registered_index_never_completes_even_if_the_plan_names_its_index() -> None:
    """F4: the derived index name in a plan is not a registered identity."""
    f = _Fixture()
    query = f.query(ARM_PTX, limit=1)
    assert query.catalog.index_for(query.batch_id) is None
    plan, ok = [{"Plan": _node()}], {"status": "ok", "candidates": [{"canonical_key": "sym:a"}]}
    unregistered = classify_ann(parse_ann_records(_stdout(plan, ok)), query)
    assert (unregistered.state, unregistered.reason, unregistered.index_selected, unregistered.rows) == (
        "unavailable", "index_not_selected", False, ())
    claimed = _stdout(plan, ok, pre=_flight("preflight", index_unchanged=True),
                      post=_flight("postflight", index_unchanged=True))
    assert classify_ann(parse_ann_records(claimed), query).reason == "study_relation_changed"
    other = replace(query, catalog=_with_index(f.catalog, NAMES.batch_id(1, ARM_V1)))
    assert classify_ann(parse_ann_records(_stdout(plan, ok)), other).reason == "index_not_selected"
