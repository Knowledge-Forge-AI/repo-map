"""Unit contracts for evaluator-only HNSW SQL, plans, and cleanup."""

from __future__ import annotations

from dataclasses import replace
from typing import NoReturn, cast

import pytest

from common_lore_index.storage.authority import GraphRunId
from common_lore_index.storage.publication_readback import RunPublicationRecord
from common_lore_index.storage.semantic_candidates import CandidatePublication
from repomap_test_support.semantic_candidate_fixtures import candidate_query
from repomap_test_support.w5_semantic_support import make_w5_verified_pin
from retrieval_semantic_ann import (
    HnswEvaluationError,
    HnswEvaluationQuery,
    HnswExecutionState,
    HnswIndexCatalogState,
    HnswKnobs,
    cleanup_owned_hnsw_index,
    compare_hnsw_to_exact,
    parse_hnsw_candidates,
    parse_hnsw_explain,
    run_hnsw_evaluation,
    verify_hnsw_index_catalog,
)
from retrieval_semantic_ann_contracts import HnswCleanupReport
from retrieval_semantic_ann_models import HnswCandidate, JsonArray, JsonObject, JsonValue
from retrieval_semantic_ann_lifecycle import (
    HnswCleanupDisposition,
    HnswCostEvidence,
    HnswLifecycleReceipt,
    capture_creation_receipt,
)
from retrieval_semantic_ann_sql import (
    HNSW_DIMENSIONS,
    build_hnsw_ann_statement,
    build_hnsw_index_create_sql,
    build_hnsw_index_drop_sql,
)


def _query(*, selected: bool = True, limit: int = 2) -> HnswEvaluationQuery:
    pin = make_w5_verified_pin(backend="postgresql")
    base = candidate_query()
    publication = CandidatePublication(
        pin.repository_identity,
        RunPublicationRecord(GraphRunId(pin.run_id), pin.receipt),
    )
    profile = replace(base.profile, dimensions=HNSW_DIMENSIONS)
    vector = (1.0,) + (0.0,) * (HNSW_DIMENSIONS - 1)
    return HnswEvaluationQuery(
        replace(
            base,
            publication=publication,
            profile=profile,
            vector=vector,
            selected=selected,
            limit=limit,
            source_binding_id=sorted(pin.admitted_public_bindings)[0],
        ),
        pin,
        "attempt-w5-1",
    )


def _catalog(query: HnswEvaluationQuery, *, present: bool = True) -> HnswIndexCatalogState:
    spec = query.index_spec
    return HnswIndexCatalogState(
        present=present,
        index_oid=101,
        table_oid=202,
        index_attribute_count=1,
        index_key_count=1,
        index_schema="repomap_enrichment",
        index_name=spec.name,
        table_schema="repomap_enrichment",
        table_name="embeddings",
        access_method="hnsw",
        is_valid=True,
        is_ready=True,
        index_owner=query.owner_identity,
        current_user=query.owner_identity,
        opclass_schema="repomap_vector",
        opclass_name="vector_cosine_ops",
        expression="(embedding)::repomap_vector.vector(384)",
        predicate=f"(rebuild_id = '{spec.rebuild_id}') AND (dimensions = 384)",
        reloptions=(),
    )


def _plan(query: HnswEvaluationQuery, *, index: bool = True) -> JsonArray:
    child: JsonObject = {
        "Node Type": "Index Scan" if index else "Seq Scan",
        "Actual Rows": 2,
    }
    if index:
        child.update({"Index Name": query.index_spec.name, "Order By": "(embedding <=> query)"})
    plan: JsonObject = {"Node Type": "Limit", "Actual Rows": 2, "Plans": [child]}
    return [{"Planning Time": 0.1, "Execution Time": 0.2, "Plan": plan}]


def _payload(query: HnswEvaluationQuery, *, status: str = "ok", count: int = 2) -> JsonObject:
    binding_id, snapshot_id = next(iter(query.snapshot_by_binding.items()))
    rows: list[JsonObject] = [
        {
            "node_id": index + 1,
            "canonical_key": f"file:src/{index}.py::fn",
            "source_binding_id": binding_id,
            "snapshot_id": snapshot_id,
            "input_digest": "sha256:" + "a" * 64,
            "kind": "function",
            "display_name": "fn",
            "confidence": "extracted",
            "conflict": False,
            "distance": float(index),
            "evidence": [],
        }
        for index in range(count)
    ]
    rows_value: JsonValue = cast(JsonValue, rows)
    return {
        "status": status,
        "candidates": rows_value,
    }


def test_query_requires_selected_384_profile_and_frozen_knobs() -> None:
    _query().validate()
    with pytest.raises(HnswEvaluationError, match="selection"):
        _query(selected=False).validate()
    selected = _query()
    unpinned_profile = replace(selected.candidate_query, profile=candidate_query().profile)
    with pytest.raises(HnswEvaluationError, match="384"):
        HnswEvaluationQuery(unpinned_profile, selected.publication_pin, selected.attempt_identity).validate()
    with pytest.raises(HnswEvaluationError, match="predeclared"):
        HnswKnobs(ef_search=41).validate()
    with pytest.raises(HnswEvaluationError, match="predeclared"):
        HnswKnobs(ef_search=cast(int, 40.0)).validate()
    with pytest.raises(HnswEvaluationError, match="predeclared"):
        HnswKnobs(ef_search=cast(int, True)).validate()


def test_private_source_refuses_before_any_candidate_callback() -> None:
    query = _query()
    private = replace(
        query,
        candidate_query=replace(query.candidate_query, source_binding_id="bind1:" + "4" * 64),
    )

    def fail(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("candidate callback reached before source refusal")

    result = run_hnsw_evaluation(
        private, read_catalog=fail, explain_json=fail, execute_json=fail, exact_baseline_json=fail
    )
    assert result.state == HnswExecutionState.REFUSED


def test_ann_sql_preserves_fences_and_has_direct_ordered_distance_limit() -> None:
    query = _query(limit=2)
    sql = build_hnsw_ann_statement(
        query.candidate_query, source_scope=query.public_source_scope, ann_scan_limit=5
    )
    assert "distances AS MATERIALIZED" not in sql
    assert "ann_scan AS (" in sql
    assert "ORDER BY (embedding.embedding::\"repomap_vector\".vector(384))" in sql
    assert "FETCH FIRST 5 ROWS WITH TIES" in sql
    assert "ranked AS MATERIALIZED" in sql and "LIMIT 2" in sql
    for fragment in (
        "rebuild.profile_identity", "rebuild.receipt_identity", "privacy_class = 'public'",
        "rebuild.row_count BETWEEN 1 AND 500", "rebuild.row_count =",
        "node.graph_key_version = 1",
        "evidence.metadata_json->>'binding_id' = embedding.source_binding_id",
        "evidence.metadata_json->>'snapshot_id' = embedding.snapshot_id",
    ):
        assert fragment in sql


def test_owned_index_sql_is_fixed_384_cosine_and_restrict_only() -> None:
    query = _query()
    spec = query.index_spec
    create_sql = build_hnsw_index_create_sql(spec)
    drop_sql = build_hnsw_index_drop_sql(spec)
    assert "USING hnsw" in create_sql
    assert "vector(384)" in create_sql and "vector_cosine_ops" in create_sql
    assert "vector_l2_ops" not in create_sql
    assert "dimensions = 384" in create_sql and spec.rebuild_id in create_sql
    assert drop_sql.endswith("RESTRICT;") and "CASCADE" not in drop_sql


@pytest.mark.parametrize("index", [True, False])
def test_plan_parser_only_credits_expected_native_index(index: bool) -> None:
    query = _query()
    summary = parse_hnsw_explain(_plan(query, index=index), expected_index_name=query.index_spec.name)
    assert summary.used_expected_index is index
    assert summary.used_seq_scan is (not index)
    assert summary.distance_order_present is index


def test_plan_parser_requires_distance_order_on_the_expected_index_node() -> None:
    query = _query()
    expected = query.index_spec.name
    payload = _plan(query)
    top = cast(JsonObject, payload[0])
    plan = cast(JsonObject, top["Plan"])
    child = cast(JsonObject, cast(list[JsonValue], plan["Plans"])[0])
    child["Order By"] = None
    plan["Order By"] = "(other_embedding <=> query)"
    summary = parse_hnsw_explain(payload, expected_index_name=expected)
    assert summary.distance_order_present is True
    assert summary.used_expected_index is False


def test_plan_parser_rejects_malformed_children_and_candidate_payload_rejects_vector_leak() -> None:
    with pytest.raises(HnswEvaluationError, match="children"):
        malformed: JsonArray = [{"Plan": {"Plans": {}}}]
        parse_hnsw_explain(malformed, expected_index_name="owned")
    payload = _payload(_query())
    candidates = cast(list[JsonObject], payload["candidates"])
    candidates[0]["vector"] = cast(JsonValue, [1.0])
    with pytest.raises(HnswEvaluationError, match="unapproved"):
        parse_hnsw_candidates(
            payload, snapshot_by_binding=_query().snapshot_by_binding,
            requested_limit=2, evidence_limit=5,
        )


@pytest.mark.parametrize("field", ["input_digest", "snapshot_id"])
def test_candidate_payload_requires_publication_bound_provenance(field: str) -> None:
    query = _query()
    payload = _payload(query)
    cast(list[JsonObject], payload["candidates"])[0][field] = None
    with pytest.raises(HnswEvaluationError, match="candidate"):
        parse_hnsw_candidates(
            payload, snapshot_by_binding=query.snapshot_by_binding,
            requested_limit=2, evidence_limit=5,
        )


@pytest.mark.parametrize("distance", [True, float("nan"), "0.1"])
def test_candidate_payload_rejects_nonfinite_or_wrong_distance_types(distance: object) -> None:
    payload = _payload(_query())
    cast(list[JsonObject], payload["candidates"])[0]["distance"] = cast(JsonValue, distance)
    with pytest.raises(HnswEvaluationError, match="finite number"):
        parse_hnsw_candidates(
            payload, snapshot_by_binding=_query().snapshot_by_binding,
            requested_limit=2, evidence_limit=5,
        )


def test_exact_recall_is_separate_and_short_page_is_truncated() -> None:
    candidates = tuple(
        HnswCandidate(
            index + 1, f"file:{index}", "bind1:fixture", index + 1, 0.1,
            "sha256:" + "a" * 64, "snap1:fixture", None, None, (),
        )
        for index in range(1)
    )
    summary = compare_hnsw_to_exact(
        candidates,
        (("file:0", "bind1:fixture"), ("file:1", "bind1:fixture")),
        limit=2,
    )
    assert summary.recall_at_k == 0.5
    assert summary.truncated is True


def test_catalog_ownership_refuses_wrong_opclass_and_missing_index() -> None:
    query = _query()
    spec = query.index_spec
    assert verify_hnsw_index_catalog(_catalog(query, present=False), spec) == "hnsw_index_absent"
    wrong = replace(_catalog(query), opclass_name="vector_l2_ops")
    assert verify_hnsw_index_catalog(wrong, spec) == "hnsw_index_operator_mismatch"


def test_catalog_ownership_requires_exact_shape_and_identity() -> None:
    query = _query()
    assert verify_hnsw_index_catalog(
        replace(_catalog(query), table_name="other_table"), query.index_spec
    ) == "hnsw_index_identity_mismatch"
    assert verify_hnsw_index_catalog(
        replace(_catalog(query), expression="embedding::repomap_vector.vector(384) || 'foreign'"),
        query.index_spec,
    ) == "hnsw_index_expression_mismatch"
    assert verify_hnsw_index_catalog(
        replace(_catalog(query), predicate="rebuild_id = 'other-rebuild' AND dimensions = 384"),
        query.index_spec,
    ) == "hnsw_index_dimension_predicate_mismatch"


def test_cleanup_never_drops_foreign_index_and_reports_owned_cleanup() -> None:
    query = _query()
    calls: list[str] = []
    foreign = replace(_catalog(query), index_name="foreign_index")
    refused = cleanup_owned_hnsw_index(
        query.index_spec,
        expected_index_oid=101,
        expected_table_oid=202,
        read_catalog=lambda _sql, *, label: foreign,
        execute_ddl=lambda sql, *, label: calls.append(sql),
    )
    assert refused.ownership_refused is True and calls == []

    states = [_catalog(query), HnswIndexCatalogState(False)]
    cleaned = cleanup_owned_hnsw_index(
        query.index_spec,
        expected_index_oid=101,
        expected_table_oid=202,
        read_catalog=lambda _sql, *, label: states.pop(0),
        execute_ddl=lambda sql, *, label: calls.append(sql),
    )
    assert cleaned.verified_absent is True and cleaned.failure_code is None
    assert calls[-1].endswith("RESTRICT;")

    missing_receipt = cleanup_owned_hnsw_index(
        query.index_spec,
        expected_index_oid=None,
        expected_table_oid=None,
        read_catalog=lambda _sql, *, label: _catalog(query),
        execute_ddl=lambda sql, *, label: calls.append(sql),
    )
    assert missing_receipt.ownership_refused is True
    assert missing_receipt.failure_code == "creation_receipt_required"


def test_lifecycle_receipt_retains_costs_external_import_and_primary_failure() -> None:
    query = _query()
    creation = capture_creation_receipt(
        HnswIndexCatalogState(False), _catalog(query), query.index_spec,
        attempt_identity="attempt-w5-1",
    )
    cost = HnswCostEvidence(
        lifecycle_wall_seconds=1.0,
        index_build_wall_seconds=0.4,
        explain_wall_seconds=0.2,
        query_wall_seconds=0.3,
        index_footprint_bytes=4096,
        work_candidates_inspected=2,
        embedding_import_status="external_not_measured",
    )
    cleanup = HnswCleanupDisposition(
        "verified_absent", "hnsw_query_failed", HnswCleanupReport(query.index_spec.name, True, True, False, None)
    )
    receipt = HnswLifecycleReceipt("attempt-w5-1", creation, cost, cleanup).validate()
    assert cast(dict[str, object], receipt.to_dict()["cleanup"])["primary_reason"] == "hnsw_query_failed"


def test_creation_receipt_refuses_preexisting_name_instead_of_adopting_it() -> None:
    query = _query()
    with pytest.raises(ValueError, match="adoption"):
        capture_creation_receipt(
            _catalog(query), _catalog(query), query.index_spec,
            attempt_identity="attempt-w5-occupied",
            definition_digest="sha256:" + "b" * 64,
            predicate_digest="sha256:" + "c" * 64,
        )


def test_creation_receipt_refuses_non_owner_catalog_readback() -> None:
    query = _query()
    wrong_owner = _catalog(query)
    wrong_owner = replace(wrong_owner, current_user="reader")
    with pytest.raises(ValueError, match="not accepted"):
        capture_creation_receipt(
            HnswIndexCatalogState(False), wrong_owner, query.index_spec,
            attempt_identity="attempt-w5-1",
        )


def test_seq_scan_is_not_run_and_stale_payload_is_unavailable() -> None:
    query = _query()
    result = run_hnsw_evaluation(
        query,
        read_catalog=lambda _sql, *, label: _catalog(query),
        explain_json=lambda _sql, *, label: _plan(query, index=False),
        execute_json=lambda _sql, *, label: (_ for _ in ()).throw(AssertionError("not called")),
        exact_baseline_json=lambda _sql, *, source_scope, label: _payload(query),
    )
    assert result.state == HnswExecutionState.NOT_RUN

    stale = run_hnsw_evaluation(
        query,
        read_catalog=lambda _sql, *, label: _catalog(query),
        explain_json=lambda _sql, *, label: _plan(query),
        execute_json=lambda _sql, *, label: _payload(query),
        exact_baseline_json=lambda _sql, *, source_scope, label: _payload(query, status="stale_publication"),
    )
    assert stale.state == HnswExecutionState.UNAVAILABLE

    failed = run_hnsw_evaluation(
        query,
        read_catalog=lambda _sql, *, label: _catalog(query),
        explain_json=lambda _sql, *, label: _plan(query),
        execute_json=lambda _sql, *, label: (_ for _ in ()).throw(RuntimeError("secret")),
        exact_baseline_json=lambda _sql, *, source_scope, label: _payload(query),
    )
    assert failed.state == HnswExecutionState.FAILED
    assert failed.reason == "hnsw_query_failed"
