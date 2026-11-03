"""Equality-first disposable PostgreSQL JSONB named node-evidence experiment (ADR 0137)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import time
from typing import Any

from retrieval_jsonb_metrics import (
    ExplainPlanSummary,
    _derive_measured_disposition,
    summarize_explain_plan,
)
from retrieval_jsonb_sql import (
    DISPOSABLE_SCHEMA,
    GIN_OPS_INDEX,
    GIN_PATH_OPS_INDEX,
    JSONB_EXPERIMENT_POLICY_VERSION,
    PROJECTION_TABLE,
    STATE_TABLE,
    VARIANT_NAMES,
    JsonbFacetFilter,
    NamedEvidenceWorkloadItem,
    NodeLocationsQuery,
    build_cleanup_sql,
    build_jsonb_projection_ddl_sql,
    build_jsonb_workload_sql,
    build_relational_workload_sql,
    decode_node_locations_payload,
    normalize_node_locations_result_for_equality,
    validate_evidence_metadata_facets,
)
from retrieval_jsonb_ownership import (
    JsonbSchemaOwnershipReceipt,
    build_schema_catalog_sql,
    build_schema_creation_sql,
    build_schema_creation_receipt_sql,
    create_schema_ownership_receipt,
    inspect_and_refuse_preexisting_schema,
    require_schema_ownership,
    read_schema_catalog_state,
)
from retrieval_semantic_representation import (
    W5_FOUNDATION_SCHEMA_VERSION,
    _require,
)


def _variant_index_ddls() -> tuple[tuple[str, str | None, str], ...]:
    drop_both = (
        f"DROP INDEX IF EXISTS {DISPOSABLE_SCHEMA}.{GIN_OPS_INDEX} RESTRICT; "
        f"DROP INDEX IF EXISTS {DISPOSABLE_SCHEMA}.{GIN_PATH_OPS_INDEX} RESTRICT; "
        f"ANALYZE {PROJECTION_TABLE};"
    )
    make_ops = (
        f"DROP INDEX IF EXISTS {DISPOSABLE_SCHEMA}.{GIN_PATH_OPS_INDEX} RESTRICT; "
        f"CREATE INDEX IF NOT EXISTS {GIN_OPS_INDEX} ON {PROJECTION_TABLE} USING gin (facet_doc jsonb_ops); "
        f"ANALYZE {PROJECTION_TABLE};"
    )
    make_path = (
        f"DROP INDEX IF EXISTS {DISPOSABLE_SCHEMA}.{GIN_OPS_INDEX} RESTRICT; "
        f"CREATE INDEX IF NOT EXISTS {GIN_PATH_OPS_INDEX} ON {PROJECTION_TABLE} USING gin (facet_doc jsonb_path_ops); "
        f"ANALYZE {PROJECTION_TABLE};"
    )
    return (
        ("jsonb_no_index", None, drop_both),
        ("jsonb_gin_ops", make_ops, make_ops),
        ("jsonb_gin_path_ops", make_path, make_path),
    )


def _exception_summary(exc: BaseException) -> str:
    """Keep executor failures public-safe while retaining their bounded code."""
    code = _safe_exception_code(exc)
    if code is not None:
        return f"{type(exc).__name__}:{code}"
    return type(exc).__name__


def _exception_code(exc: BaseException) -> str:
    return _safe_exception_code(exc) or type(exc).__name__


def _safe_exception_code(exc: BaseException) -> str | None:
    code = getattr(exc, "code", None)
    if type(code) is not str or not 0 < len(code) <= 80 or not code.isascii():
        return None
    return code if all(char.isalnum() or char in "_.-" for char in code) else None


def run_jsonb_evidence_experiment(
    workload: Sequence[NamedEvidenceWorkloadItem],
    *,
    json_executor: Callable[[str], Mapping[str, Any]],
    ddl_executor: Callable[[str], None],
    explain_executor: Callable[[str], Mapping[str, Any] | Sequence[Any]],
    repository_identity: str | None = None,
    root_path: str = "",
    context_identity: bool = False,
    fail_on_malformed_facets: bool = False,
    repetitions: int = 1,
    cache_state: str = "warm_in_session",
) -> dict[str, Any]:
    """Run the equality-first JSONB node-evidence workload experiment with full cost/plan/cleanup accounting."""
    _require(bool(workload), "empty_workload", "workload must contain at least one NamedEvidenceWorkloadItem")
    _require(type(repetitions) is int and repetitions >= 1, "invalid_repetitions", "repetitions must be >= 1")
    for item in workload:
        item.validate()

    execution_declaration = {
        "repetitions": repetitions,
        "cache_state": cache_state,
        "selected_keys": [item.query.canonical_key for item in workload],
        "facet_filters": [
            {
                "workload_id": item.workload_id,
                "facet_filter": None if item.facet_filter is None else item.facet_filter.to_dict(),
                "expected_status": item.expected_status,
            }
            for item in workload
        ],
    }
    baseline_outputs: dict[str, dict[str, Any]] = {}
    variant_outputs: dict[str, dict[str, dict[str, Any]]] = {v: {} for v in VARIANT_NAMES}
    variant_query_exec_ms: dict[str, float] = {v: 0.0 for v in VARIANT_NAMES}
    explain_summaries: dict[str, list[dict[str, Any]]] = {v: [] for v in VARIANT_NAMES}
    index_accounting: dict[str, Any] = {}
    mismatches: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    state_info: Mapping[str, Any] = {}
    source_read_ms = projection_build_ms = projection_refresh_ms = 0.0
    cleanup_verified = False
    primary_error: str | None = None
    schema_receipt: JsonbSchemaOwnershipReceipt | None = None
    current_stage = "projection_setup"

    try:
        inspect_and_refuse_preexisting_schema(json_executor)
        schema_receipt = create_schema_ownership_receipt(json_executor, ddl_executor=ddl_executor)

        def execute_owned_ddl(sql: str) -> None:
            assert schema_receipt is not None
            require_schema_ownership(schema_receipt, json_executor)
            ddl_executor(sql)

        ddl_sql = build_jsonb_projection_ddl_sql(
            repository_identity=repository_identity, root_path=root_path, context_identity=context_identity
        )
        t0 = time.monotonic()
        execute_owned_ddl(ddl_sql)
        projection_build_ms = round((time.monotonic() - t0) * 1000.0, 4)
        t_ref = time.monotonic()
        execute_owned_ddl(ddl_sql)
        projection_refresh_ms = round((time.monotonic() - t_ref) * 1000.0, 4)

        state_info = json_executor(
            f"SELECT json_build_object('projected_row_count', COALESCE((SELECT projected_row_count FROM {STATE_TABLE} LIMIT 1), 0), "
            f"'malformed_metadata_count', COALESCE((SELECT malformed_metadata_count FROM {STATE_TABLE} LIMIT 1), 0))::text;"
        )
        current_stage = "relational_baseline"
        rel_sql_by_id: dict[str, str] = {}
        read_elapsed = 0.0
        for item in workload:
            rel_sql = build_relational_workload_sql(item, repository_identity=repository_identity, root_path=root_path)
            rel_sql_by_id[item.workload_id] = rel_sql
            raw_rel: Mapping[str, Any] = {}
            for _ in range(repetitions):
                t_src = time.monotonic()
                raw_rel = json_executor(rel_sql)
                read_elapsed += time.monotonic() - t_src
            norm_rel = normalize_node_locations_result_for_equality(
                decode_node_locations_payload(raw_rel, query=item.query, context_identity=item.context_identity)
            )
            if norm_rel.get("status") != item.expected_status:
                failures.append(
                    {
                        "stage": "relational_baseline",
                        "reason": "expected_status_mismatch",
                        "detail": f"{item.workload_id}:{norm_rel.get('status')}!={item.expected_status}",
                    }
                )
                mismatches.append(
                    {"variant": "relational_baseline", "workload_id": item.workload_id, "expected_status": item.expected_status, "observed": norm_rel}
                )
            baseline_outputs[item.workload_id] = variant_outputs["relational_baseline"][item.workload_id] = norm_rel
        source_read_ms = variant_query_exec_ms["relational_baseline"] = round(read_elapsed * 1000.0, 4)

        jsonb_sql_by_id = {
            item.workload_id: build_jsonb_workload_sql(item, repository_identity=repository_identity, root_path=root_path)
            for item in workload
        }
        for v_name, ix_ddl, _explain_ddl in _variant_index_ddls():
            current_stage = v_name
            t_ix = time.monotonic()
            if ix_ddl is not None:
                execute_owned_ddl(ix_ddl)
            ix_ms = round((time.monotonic() - t_ix) * 1000.0, 4) if ix_ddl is not None else 0.0
            size_info = json_executor(
                f"SELECT json_build_object('table_bytes', pg_relation_size('{PROJECTION_TABLE}'), "
                f"'indexes_bytes', pg_indexes_size('{PROJECTION_TABLE}'), 'total_bytes', pg_total_relation_size('{PROJECTION_TABLE}'))::text;"
            )
            index_accounting[v_name] = {"index_build_ms": ix_ms, "explain_index_rebuild_ms": 0.0, **dict(size_info)}
            v_elapsed = 0.0
            for item in workload:
                j_sql = jsonb_sql_by_id[item.workload_id]
                raw_j: Mapping[str, Any] = {}
                for _ in range(repetitions):
                    t_q = time.monotonic()
                    raw_j = json_executor(j_sql)
                    v_elapsed += time.monotonic() - t_q
                norm_j = normalize_node_locations_result_for_equality(
                    decode_node_locations_payload(
                        raw_j, query=item.query, context_identity=item.context_identity, fail_on_malformed_facets=fail_on_malformed_facets
                    )
                )
                variant_outputs[v_name][item.workload_id] = norm_j
                if norm_j != baseline_outputs[item.workload_id]:
                    failures.append({"stage": v_name, "reason": "parity_mismatch", "detail": item.workload_id})
                    mismatches.append(
                        {"variant": v_name, "workload_id": item.workload_id, "baseline": baseline_outputs[item.workload_id], "observed": norm_j}
                    )
            variant_query_exec_ms[v_name] = round(v_elapsed * 1000.0, 4)

        if not mismatches and not failures:
            current_stage = "explain_plans"
            for item in workload:
                explain_summaries["relational_baseline"].append(
                    summarize_explain_plan("relational_baseline", item.workload_id, explain_executor(rel_sql_by_id[item.workload_id])).to_dict()
                )
            for v_name, _ix_ddl, explain_ddl in _variant_index_ddls():
                t_reb = time.monotonic()
                execute_owned_ddl(explain_ddl)
                index_accounting[v_name]["explain_index_rebuild_ms"] = round((time.monotonic() - t_reb) * 1000.0, 4)
                for item in workload:
                    explain_summaries[v_name].append(
                        summarize_explain_plan(v_name, item.workload_id, explain_executor(jsonb_sql_by_id[item.workload_id])).to_dict()
                    )
    except Exception as exc:
        summary = _exception_summary(exc)
        primary_error = summary
        failures.append({"stage": current_stage, "reason": _exception_code(exc), "detail": summary})
    finally:
        if schema_receipt is None:
            failures.append({"stage": "cleanup", "reason": "cleanup_skipped_unowned", "detail": "schema_receipt_unavailable"})
        else:
            try:
                execute_owned_ddl(build_cleanup_sql())
                cleanup_state = read_schema_catalog_state(json_executor(build_schema_catalog_sql()))
                cleanup_verified = not cleanup_state.schema_exists
                if not cleanup_verified:
                    failures.append({"stage": "cleanup", "reason": "cleanup_verification_failed", "detail": DISPOSABLE_SCHEMA})
            except Exception as cleanup_exc:
                cleanup_verified = False
                failures.append({"stage": "cleanup", "reason": "cleanup_error", "detail": _exception_summary(cleanup_exc)})

    equality_passed = len(mismatches) == 0 and primary_error is None and not any(
        f.get("reason") in {"expected_status_mismatch", "parity_mismatch"} for f in failures
    )
    projected_rows = int(state_info.get("projected_row_count") or 0)
    disposition, disp_evidence = _derive_measured_disposition(
        equality_passed=equality_passed,
        cleanup_verified=cleanup_verified,
        projected_row_count=projected_rows,
        source_read_ms=source_read_ms,
        projection_build_ms=projection_build_ms,
        projection_refresh_ms=projection_refresh_ms,
        variant_query_exec_ms=variant_query_exec_ms,
        index_accounting=index_accounting,
        explain_summaries=explain_summaries if equality_passed else {},
    )
    status = (
        "passed" if (equality_passed and cleanup_verified)
        else ("failed_execution" if primary_error is not None else ("failed_equality_gate" if not equality_passed else "failed_cleanup"))
    )
    return {
        "schema_version": W5_FOUNDATION_SCHEMA_VERSION,
        "policy_version": JSONB_EXPERIMENT_POLICY_VERSION,
        "status": status,
        "equality_passed": equality_passed,
        "primary_error": primary_error,
        "mismatches": mismatches,
        "failures": failures,
        "source_read_ms": source_read_ms,
        "projection_build_ms": projection_build_ms,
        "projection_refresh_ms": projection_refresh_ms,
        "variant_query_exec_ms": variant_query_exec_ms,
        "projected_row_count": projected_rows,
        "malformed_metadata_count": int(state_info.get("malformed_metadata_count") or 0),
        "index_accounting": index_accounting,
        "explain_summaries": explain_summaries if equality_passed else {},
        "cleanup_verified": cleanup_verified,
        "execution_declaration": execution_declaration,
        "disposition_evidence": disp_evidence,
        "recommended_disposition": disposition,
    }


__all__ = [
    "DISPOSABLE_SCHEMA", "GIN_OPS_INDEX", "GIN_PATH_OPS_INDEX", "JSONB_EXPERIMENT_POLICY_VERSION",
    "PROJECTION_TABLE", "STATE_TABLE", "VARIANT_NAMES", "ExplainPlanSummary", "JsonbFacetFilter",
    "NamedEvidenceWorkloadItem", "NodeLocationsQuery", "build_cleanup_sql",
    "build_jsonb_projection_ddl_sql", "build_jsonb_workload_sql", "build_relational_workload_sql",
    "build_schema_catalog_sql", "build_schema_creation_sql", "build_schema_creation_receipt_sql", "create_schema_ownership_receipt",
    "inspect_and_refuse_preexisting_schema", "require_schema_ownership",
    "decode_node_locations_payload", "normalize_node_locations_result_for_equality",
    "run_jsonb_evidence_experiment", "summarize_explain_plan", "validate_evidence_metadata_facets",
]
