"""Unit tests for the equality-first disposable PostgreSQL JSONB evidence experiment (ADR 0137)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast
import pytest

from repomap_test_support.w5_jsonb_support import (
    make_synthetic_explain_json,
    make_synthetic_node_locations_raw_payload,
)
from retrieval_jsonb_evidence import (
    DISPOSABLE_SCHEMA,
    GIN_OPS_INDEX,
    PROJECTION_TABLE,
    JsonbFacetFilter,
    NamedEvidenceWorkloadItem,
    NodeLocationsQuery,
    build_cleanup_sql,
    build_jsonb_projection_ddl_sql,
    build_jsonb_workload_sql,
    build_relational_workload_sql,
    build_schema_catalog_sql,
    build_schema_creation_receipt_sql,
    decode_node_locations_payload,
    run_jsonb_evidence_experiment,
    summarize_explain_plan,
    validate_evidence_metadata_facets,
)
from retrieval_semantic_representation import RepresentationValidationError
from retrieval_jsonb_ownership import read_schema_catalog_state

BIND_CORE = "bind1:" + ("1" * 64)
SNAP_CORE = "snap1:" + ("a" * 64)


@pytest.mark.parametrize(
    "bad_metadata",
    [
        "{not-valid-json",
        "[]",
        {"binding_id": BIND_CORE},
        {"snapshot_id": SNAP_CORE},
        {"source_relative_path": "pkg/pipeline.py"},
        {"binding_id": BIND_CORE, "snapshot_id": SNAP_CORE, "source_relative_path": None},
        {"binding_id": BIND_CORE, "snapshot_id": SNAP_CORE, "source_relative_path": "../escape.py"},
        {"binding_id": BIND_CORE, "snapshot_id": SNAP_CORE, "source_relative_path": "/abs/path.py"},
        {"binding_id": 123, "snapshot_id": SNAP_CORE},
        {"binding_id": "   ", "snapshot_id": SNAP_CORE},
    ],
)
def test_validate_evidence_metadata_facets_refuses_malformed_or_unpaired_facets(bad_metadata: Any) -> None:
    """Malformed, path-only, or unpaired metadata_json facets are refused rather than inventing defaults."""
    with pytest.raises(RepresentationValidationError) as exc_info:
        validate_evidence_metadata_facets(bad_metadata)
    assert exc_info.value.code == "malformed_evidence_metadata"
    assert validate_evidence_metadata_facets(None) is None
    assert validate_evidence_metadata_facets({}) is None
    valid = validate_evidence_metadata_facets(
        {"binding_id": BIND_CORE, "snapshot_id": SNAP_CORE, "source_relative_path": "pkg/pipeline.py"}
    )
    assert valid == {"binding_id": BIND_CORE, "snapshot_id": SNAP_CORE, "source_relative_path": "pkg/pipeline.py"}


def test_workload_and_facet_filter_validation_rejects_bad_paths_and_expected_status() -> None:
    """JsonbFacetFilter and NamedEvidenceWorkloadItem validate relative paths and expected_status."""
    q = NodeLocationsQuery(canonical_key="sym:core/pkg/pipeline.py::RetrievalPipeline", evidence_role="direct", limit=5)
    with pytest.raises(RepresentationValidationError) as exc_path:
        JsonbFacetFilter(binding_id=BIND_CORE, snapshot_id=SNAP_CORE, source_relative_path="../bad.py").validate()
    assert exc_path.value.code == "invalid_relative_path"

    with pytest.raises(RepresentationValidationError) as exc_status:
        NamedEvidenceWorkloadItem("w_bad", q, expected_status="bogus").validate()
    assert exc_status.value.code == "invalid_expected_status"


def test_schema_catalog_state_rejects_string_oid_without_coercion() -> None:
    with pytest.raises(RepresentationValidationError) as exc_info:
        read_schema_catalog_state({"schema_exists": True, "schema_oid": "17187", "schema_owner": "repo_map_test"})
    assert exc_info.value.code == "schema_catalog_invalid"


def test_sql_builders_compose_actual_node_locations_and_disposable_schema() -> None:
    """Verify relational baseline, population-wide JSONB DDL, containment SQL, fingerprint invalidation, and RESTRICT cleanup."""
    q = NodeLocationsQuery(canonical_key="sym:core/pkg/pipeline.py::RetrievalPipeline", evidence_role="direct", limit=5)
    facet = JsonbFacetFilter(binding_id=BIND_CORE, snapshot_id=SNAP_CORE, source_relative_path="pkg/pipeline.py")
    item_unfiltered = NamedEvidenceWorkloadItem("w_unfiltered", q, context_identity=True)
    item_filtered = NamedEvidenceWorkloadItem("w_filtered", q, context_identity=True, facet_filter=facet)

    rel_unfiltered = build_relational_workload_sql(item_unfiltered, repository_identity="repo1:test", root_path="/repo")
    assert "current_window AS MATERIALIZED" in rel_unfiltered
    assert "historical_window AS MATERIALIZED" in rel_unfiltered
    assert "binding_id" not in rel_unfiltered

    rel_filtered = build_relational_workload_sql(item_filtered, repository_identity="repo1:test", root_path="/repo")
    assert "(e.metadata_json::jsonb ->> 'binding_id')" in rel_filtered
    assert "(e.metadata_json::jsonb ->> 'snapshot_id')" in rel_filtered
    assert "(e.metadata_json::jsonb ->> 'source_relative_path')" in rel_filtered

    ddl_ctx = build_jsonb_projection_ddl_sql(repository_identity="repo1:test", root_path="/repo", context_identity=True)
    ddl_std = build_jsonb_projection_ddl_sql(repository_identity=None, root_path="/repo", context_identity=False)
    assert f"CREATE SCHEMA {DISPOSABLE_SCHEMA};" not in ddl_ctx
    catalog_sql = build_schema_catalog_sql()
    assert "'schema_oid', (SELECT oid::bigint" in catalog_sql
    schema_create = build_schema_creation_receipt_sql()
    assert f"CREATE SCHEMA {DISPOSABLE_SCHEMA};" in schema_create
    assert "'schema_oid', ns.oid::bigint" in schema_create
    assert "CREATE SCHEMA IF NOT EXISTS" not in schema_create
    assert schema_create.startswith("BEGIN;")
    assert "COMMIT;" in schema_create
    assert schema_create.rstrip().endswith("LIMIT 1;")
    assert f"INSERT INTO {PROJECTION_TABLE}" in ddl_ctx
    assert "graph_candidate_id" in ddl_ctx
    assert "max_evidence_run_id" in ddl_ctx
    assert "total_evidence_row_count" in ddl_ctx
    assert "evidence_fingerprint" in ddl_ctx
    assert "repo.root_path = '/repo'" in ddl_std

    jsonb_sql = build_jsonb_workload_sql(item_filtered, repository_identity="repo1:test", root_path="/repo")
    assert "p.facet_doc @>" in jsonb_sql
    assert "'projection_stale'" in jsonb_sql
    assert "st.graph_candidate_id = acc.graph_candidate_id" in jsonb_sql
    assert "st.max_evidence_run_id = live_ev.max_evidence_run_id" in jsonb_sql
    assert "st.total_evidence_row_count = live_ev.total_evidence_row_count" in jsonb_sql
    assert "st.evidence_fingerprint = live_ev.evidence_fingerprint" in jsonb_sql

    cleanup = build_cleanup_sql()
    assert f"DROP SCHEMA IF EXISTS {DISPOSABLE_SCHEMA} RESTRICT;" in cleanup
    assert "CASCADE" not in cleanup


def test_decode_node_locations_payload_handles_stale_projection_overflow_and_malformed_facets() -> None:
    """Verify live-publication stale invalidation, transport overflow, and malformed facet refusal."""
    q = NodeLocationsQuery(canonical_key="sym:core/pkg/pipeline.py::RetrievalPipeline", evidence_role="direct", limit=5)

    stale_raw = make_synthetic_node_locations_raw_payload(projection_stale=True)
    stale_res = decode_node_locations_payload(stale_raw, query=q, context_identity=True)
    assert stale_res["status"] == "unavailable"
    assert stale_res["reason"] == "projection_stale_for_live_publication"

    overflow_raw = make_synthetic_node_locations_raw_payload(transport_overflow=True)
    overflow_res = decode_node_locations_payload(overflow_raw, query=q, context_identity=True)
    assert overflow_res["status"] == "unavailable"
    assert overflow_res["reason"] == "admission_work_limit"

    malformed_raw = make_synthetic_node_locations_raw_payload(malformed_metadata_count=2)
    with pytest.raises(RepresentationValidationError) as exc_info:
        decode_node_locations_payload(malformed_raw, query=q, context_identity=True, fail_on_malformed_facets=True)
    assert exc_info.value.code == "malformed_evidence_metadata"


def test_explain_summary_and_experiment_equality_gate_and_cleanup() -> None:
    """Verify EXPLAIN summary extraction, strict equality-first gate (0 explain calls on failure), and guaranteed cleanup."""
    seq_summary = summarize_explain_plan("jsonb_gin_ops", "w1", make_synthetic_explain_json(used_gin=False))
    assert seq_summary.used_gin_index is False
    assert seq_summary.used_seq_scan is True
    assert seq_summary.shared_hit_blocks == 5
    assert seq_summary.shared_read_blocks == 0

    gin_summary = summarize_explain_plan(
        "jsonb_gin_ops", "w1", make_synthetic_explain_json(used_gin=True, index_name=GIN_OPS_INDEX)
    )
    assert gin_summary.used_gin_index is True
    assert GIN_OPS_INDEX in gin_summary.index_names_used
    assert gin_summary.shared_hit_blocks == 5

    q = NodeLocationsQuery(canonical_key="sym:core/pkg/pipeline.py::RetrievalPipeline", evidence_role="direct", limit=5)
    workload = (NamedEvidenceWorkloadItem("w1", q, context_identity=True),)
    ddl_log: list[str] = []
    explain_calls = 0
    schema_present = False
    schema_oid = 99173
    schema_owner = "fixture_owner"

    def make_json_exec(*, inject_mismatch: bool = False, malformed_count: int = 0) -> Any:
        def _exec(sql: str) -> Mapping[str, Any]:
            nonlocal schema_present
            if "pg_catalog.pg_namespace" in sql:
                return {
                    "schema_exists": schema_present,
                    "schema_oid": schema_oid if schema_present else None,
                    "schema_owner": schema_owner if schema_present else None,
                }
            if "projected_row_count" in sql:
                return {"projected_row_count": 12, "malformed_metadata_count": malformed_count}
            if "pg_relation_size" in sql:
                return {"table_bytes": 8192, "indexes_bytes": 16384, "total_bytes": 24576}
            if inject_mismatch and PROJECTION_TABLE in sql:
                return make_synthetic_node_locations_raw_payload(has_node=False)
            return make_synthetic_node_locations_raw_payload(malformed_metadata_count=malformed_count)
        return _exec

    def ddl_exec(sql: str) -> None:
        nonlocal schema_present
        ddl_log.append(sql)
        if "CREATE SCHEMA" in sql:
            schema_present = True
        if "DROP SCHEMA" in sql:
            schema_present = False

    def explain_exec(_sql: str) -> Sequence[Any]:
        nonlocal explain_calls
        explain_calls += 1
        return make_synthetic_explain_json(used_gin=False)

    ok_report = run_jsonb_evidence_experiment(
        workload,
        json_executor=make_json_exec(inject_mismatch=False),
        ddl_executor=ddl_exec,
        explain_executor=explain_exec,
        repository_identity="repo1:test",
        root_path="/repo",
        context_identity=True,
    )
    assert ok_report["status"] == "passed"
    assert ok_report["equality_passed"] is True
    assert ok_report["cleanup_verified"] is True
    assert ok_report["projected_row_count"] == 12
    assert ok_report["projection_refresh_ms"] >= 0.0
    assert ok_report["execution_declaration"]["repetitions"] == 1
    assert ok_report["disposition_evidence"]["equality_passed"] is True
    assert ok_report["disposition_evidence"]["measurements_status"] == "measured"
    assert explain_calls == 4
    assert ddl_log[0].startswith("BEGIN;\n")
    assert f"CREATE SCHEMA {DISPOSABLE_SCHEMA};" in ddl_log[0]
    assert "CREATE SCHEMA IF NOT EXISTS" not in ddl_log[0]
    assert "DROP SCHEMA" in ddl_log[-1]
    assert set(ok_report["explain_summaries"].keys()) == {
        "relational_baseline", "jsonb_no_index", "jsonb_gin_ops", "jsonb_gin_path_ops"
    }

    explain_calls = 0
    fail_report = run_jsonb_evidence_experiment(
        workload,
        json_executor=make_json_exec(inject_mismatch=True),
        ddl_executor=ddl_exec,
        explain_executor=explain_exec,
        repository_identity="repo1:test",
        root_path="/repo",
        context_identity=True,
    )
    assert fail_report["status"] == "failed_equality_gate"
    assert fail_report["equality_passed"] is False
    assert len(fail_report["mismatches"]) == 3
    assert explain_calls == 0
    assert fail_report["explain_summaries"] == {}
    assert fail_report["disposition_evidence"]["measurements_status"] == "unavailable_equality_gate_failed"
    assert fail_report["disposition_evidence"]["relational_plan_exec_ms"] is None
    assert fail_report["cleanup_verified"] is True

    # Expected status mismatch is flagged in structured failures with 0 explain calls
    explain_calls = 0
    bad_status_workload = (NamedEvidenceWorkloadItem("w_expect_unavail", q, context_identity=True, expected_status="unavailable"),)
    status_fail_report = run_jsonb_evidence_experiment(
        bad_status_workload,
        json_executor=make_json_exec(inject_mismatch=False),
        ddl_executor=ddl_exec,
        explain_executor=explain_exec,
        repository_identity="repo1:test",
        root_path="/repo",
        context_identity=True,
    )
    assert status_fail_report["status"] == "failed_equality_gate"
    assert status_fail_report["failures"][0]["reason"] == "expected_status_mismatch"
    assert explain_calls == 0

    # Execution exception (e.g. fail_on_malformed_facets=True) is caught without bare re-raise and still cleans up
    explain_calls = 0
    exc_report = run_jsonb_evidence_experiment(
        workload,
        json_executor=make_json_exec(malformed_count=1),
        ddl_executor=ddl_exec,
        explain_executor=explain_exec,
        repository_identity="repo1:test",
        root_path="/repo",
        context_identity=True,
        fail_on_malformed_facets=True,
    )
    assert exc_report["status"] == "failed_execution"
    assert exc_report["equality_passed"] is False
    assert exc_report["primary_error"] is not None
    assert exc_report["failures"][0]["reason"] == "malformed_evidence_metadata"
    assert exc_report["cleanup_verified"] is True
    assert explain_calls == 0


def test_preexisting_schema_refusal_happens_before_any_experiment_ddl() -> None:
    q = NodeLocationsQuery(canonical_key="sym:core/pkg/pipeline.py::RetrievalPipeline", evidence_role="direct", limit=5)
    workload = (NamedEvidenceWorkloadItem("w1", q, context_identity=True),)
    json_calls: list[str] = []
    ddl_calls: list[str] = []

    def json_exec(sql: str) -> Mapping[str, Any]:
        json_calls.append(sql)
        return {"schema_exists": True, "schema_oid": 77, "schema_owner": "fixture_owner"}

    def ddl_exec(sql: str) -> None:
        ddl_calls.append(sql)

    report = run_jsonb_evidence_experiment(
        workload,
        json_executor=json_exec,
        ddl_executor=ddl_exec,
        explain_executor=lambda _sql: (),
    )

    assert report["status"] == "failed_execution"
    assert report["primary_error"] == "RepresentationValidationError:schema_preexisting"
    assert len(json_calls) == 1
    assert "CREATE SCHEMA" not in json_calls[0]
    assert ddl_calls == []
    assert report["failures"][-1]["reason"] == "cleanup_skipped_unowned"


def test_owned_postcreation_failure_keeps_primary_error_and_cleans_only_owned_schema() -> None:
    q = NodeLocationsQuery(canonical_key="sym:core/pkg/pipeline.py::RetrievalPipeline", evidence_role="direct", limit=5)
    workload = (NamedEvidenceWorkloadItem("w1", q, context_identity=True),)
    schema_present = False
    json_calls: list[str] = []

    class PrivateCodedError(RuntimeError):
        code = "private executor sentinel"

    def json_exec(sql: str) -> Mapping[str, Any]:
        nonlocal schema_present
        json_calls.append(sql)
        if "pg_catalog.pg_namespace" in sql:
            return {
                "schema_exists": schema_present,
                "schema_oid": 77 if schema_present else None,
                "schema_owner": "fixture_owner" if schema_present else None,
            }
        if "projected_row_count" in sql:
            return {"projected_row_count": 0, "malformed_metadata_count": 0}
        return make_synthetic_node_locations_raw_payload()

    def failing_ddl(sql: str) -> None:
        nonlocal schema_present
        if "CREATE SCHEMA" in sql:
            schema_present = True
            return
        if "DROP SCHEMA" in sql:
            schema_present = False
            return
        raise PrivateCodedError("private executor sentinel")

    report = run_jsonb_evidence_experiment(
        workload,
        json_executor=json_exec,
        ddl_executor=failing_ddl,
        explain_executor=lambda _sql: (),
    )

    assert report["status"] == "failed_execution"
    assert report["primary_error"] == "PrivateCodedError"
    assert report["cleanup_verified"] is True
    assert "private executor sentinel" not in str(report)
    assert any("DROP SCHEMA" in sql for sql in json_calls) is False


def test_explain_deep_realistic_plan_is_retained_immutably_without_double_counting_buffers():
    leaf = {"Node Type": "Seq Scan", "Shared Hit Blocks": 999}
    root = leaf
    for _ in range(12):
        root = {"Node Type": "Nested Loop", "Plans": [root], "Shared Hit Blocks": 7}
    summary = summarize_explain_plan('relational_baseline', 'deep-plan', {'Plan': root})
    assert len(summary.plan_node_types) == 13
    assert summary.used_seq_scan is True
    assert summary.shared_hit_blocks == 7
    leaf['Node Type'] = 'Changed'
    assert summary.to_dict()['raw_explain_json']['Plan']['Plans'][0]['Node Type'] == 'Nested Loop'
    assert summary.plan_node_types[-1] == 'Seq Scan'
    with pytest.raises(TypeError):
        summary.raw_explain_json['Plan']['Node Type'] = 'Changed'


@pytest.mark.parametrize('kind', ['depth', 'items', 'nonfinite', 'bad_key', 'cycle'])
def test_explain_plan_rejects_overbound_or_non_json_data_before_traversal(kind):
    root: dict[str, Any] = {'Node Type': 'Seq Scan'}
    if kind == 'depth':
        for _ in range(40):
            root = {'Node Type': 'Nested Loop', 'Plans': [root]}
    elif kind == 'items':
        root['Plans'] = [{'Node Type': 'Seq Scan'}] * 20001
    elif kind == 'nonfinite':
        root['Total Cost'] = float('nan')
    elif kind == 'bad_key':
        cast(dict[object, object], root)[1] = 'invalid'
    else:
        root['Plans'] = [root]
    with pytest.raises(RepresentationValidationError, match='invalid_explain_json'):
        summarize_explain_plan('relational_baseline', 'bounded-plan', {'Plan': root})
