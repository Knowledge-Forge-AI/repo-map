"""Containerized PostgreSQL integration tests for the named JSONB node-evidence workload experiment (ADR 0137)."""

from __future__ import annotations

from pathlib import Path
import json

from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config import OpsConfig
from common_lore_index.ops.portable_refresh import execute_portable_refresh
from common_lore_index.server.ops import investigation_stores
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from repomap_test_support.postgres_harness import temporary_postgres
from repomap_test_support.retrieval_evaluation_canaries import assert_canary_free
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    binding_id_for_alias,
    materialize_mixed_v1_working_copy,
    write_mixed_v1_postgres_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_postgres_corpus,
    read_postgres_accepted_publication,
)
from repomap_test_support.w5_jsonb_support import (
    build_mixed_v1_jsonb_workload,
    make_postgres_jsonb_executors,
)
from retrieval_jsonb_evidence import (
    DISPOSABLE_SCHEMA,
    VARIANT_NAMES,
    build_cleanup_sql,
    build_jsonb_projection_ddl_sql,
    build_jsonb_workload_sql,
    create_schema_ownership_receipt,
    decode_node_locations_payload,
    require_schema_ownership,
    run_jsonb_evidence_experiment,
)


def test_postgres_jsonb_named_evidence_workload_equality_explain_invalidation_and_cleanup(
    tmp_path: Path,
) -> None:
    """Verify population-wide JSONB projection equality, live-publication invalidation, EXPLAIN plans, and cleanup."""
    wc = materialize_mixed_v1_working_copy(tmp_path / "wc", generation=1)

    with temporary_postgres() as pg_db:
        pg_home = write_mixed_v1_postgres_home(
            tmp_path / "pg_home",
            wc,
            host=pg_db.host,
            port=pg_db.port,
            database=pg_db.database,
            user=pg_db.user,
            password=pg_db.password,
        )
        pg_pub_g1 = publish_and_load_postgres_corpus(
            pg_home,
            selected_aliases=("core", "companion"),
            psql_command=pg_db.psql_command,
        )
        pg_cfg = load_graph_registry_config_home(pg_home)
        assert isinstance(pg_cfg, OpsConfig)
        pg_store = investigation_stores(pg_cfg).investigation_store()

        nav_res = pg_store.navigation_search(
            MIXED_V1_GRAPH_ID,
            NavigationSearchQuery(query="RetrievalExecutionPipeline", scope="all", limit=5),
        )
        assert nav_res["status"] == "ok"
        primary_key = str(nav_res["nodes"][0]["canonical_key"])

        json_exec, ddl_exec, explain_exec, repo_id, root_path = make_postgres_jsonb_executors(
            pg_cfg, MIXED_V1_GRAPH_ID, psql_command=pg_db.psql_command
        )
        core_id = binding_id_for_alias("core")
        p_g1 = pg_pub_g1.receipt.portable
        assert p_g1 is not None
        snap_g1 = next(snap for b_id, _rev, snap in p_g1.snapshot_vector if b_id == core_id)

        # 1. Build projection at generation 1, then advance live store to generation 2 -> projection is invalidated!
        schema_receipt = create_schema_ownership_receipt(json_exec, ddl_executor=ddl_exec)

        def owned_ddl(sql: str) -> None:
            require_schema_ownership(schema_receipt, json_exec)
            ddl_exec(sql)

        owned_ddl(
            build_jsonb_projection_ddl_sql(
                repository_identity=repo_id, root_path=root_path, context_identity=True
            )
        )
        materialize_mixed_v1_working_copy(wc, generation=2)
        pg_graph = pg_cfg.graphs[0]
        execute_portable_refresh(
            pg_cfg, pg_graph, pg_graph.database or pg_cfg.postgres.database, authority=None
        )
        _ref_g2, receipt_g2 = read_postgres_accepted_publication(
            pg_cfg, MIXED_V1_GRAPH_ID, psql_command=pg_db.psql_command
        )
        p_g2 = receipt_g2.portable
        assert p_g2 is not None
        snap_g2 = next(snap for b_id, _rev, snap in p_g2.snapshot_vector if b_id == core_id)
        assert snap_g2 != snap_g1

        workload_g2 = build_mixed_v1_jsonb_workload(
            primary_key=primary_key,
            core_binding_id=core_id,
            core_snapshot_id=snap_g2,
        )
        stale_raw = json_exec(
            build_jsonb_workload_sql(workload_g2[0], repository_identity=repo_id, root_path=root_path)
        )
        stale_decoded = decode_node_locations_payload(
            stale_raw, query=workload_g2[0].query, context_identity=workload_g2[0].context_identity
        )
        assert stale_decoded["status"] == "unavailable"
        assert stale_decoded["reason"] == "projection_stale_for_live_publication"

        # 1b. Rebuild projection at generation 2, then mutate one canonical_evidence row in-place
        # without changing COUNT(*) or MAX(run_id) -> evidence_fingerprint invalidates projection!
        owned_ddl(
            build_jsonb_projection_ddl_sql(
                repository_identity=repo_id, root_path=root_path, context_identity=True
            )
        )
        original_evidence = json_exec(
            "SELECT json_build_object('id', id, 'end_line', end_line) "
            "FROM public.canonical_evidence WHERE start_line IS NOT NULL AND end_line IS NOT NULL ORDER BY id LIMIT 1;"
        )
        evidence_id = original_evidence['id']
        original_end = original_evidence['end_line']
        assert type(evidence_id) is int and evidence_id > 0
        assert original_end is None or type(original_end) is int
        restore_end_sql = 'NULL' if original_end is None else str(original_end)
        ddl_exec(
            "UPDATE public.canonical_evidence SET end_line = COALESCE(end_line, 0) + 1000 "
            f"WHERE id = {evidence_id};"
        )
        try:
            mutated_raw = json_exec(
                build_jsonb_workload_sql(workload_g2[0], repository_identity=repo_id, root_path=root_path)
            )
            mutated_decoded = decode_node_locations_payload(
                mutated_raw, query=workload_g2[0].query, context_identity=workload_g2[0].context_identity
            )
            assert mutated_decoded["status"] == "unavailable"
            assert mutated_decoded["reason"] == "projection_stale_for_live_publication"
        finally:
            ddl_exec(
                f"UPDATE public.canonical_evidence SET end_line = {restore_end_sql} WHERE id = {evidence_id};"
            )
            owned_ddl(build_cleanup_sql())

        # 2. A colliding namespace with a foreign table must be refused without adoption or cleanup.
        sentinel_table = f"{DISPOSABLE_SCHEMA}.foreign_sentinel"
        ddl_exec(f"CREATE SCHEMA {DISPOSABLE_SCHEMA}; CREATE TABLE {sentinel_table} (id integer PRIMARY KEY);")
        try:
            refusal = run_jsonb_evidence_experiment(
                workload_g2,
                json_executor=json_exec,
                ddl_executor=ddl_exec,
                explain_executor=explain_exec,
                repository_identity=repo_id,
                root_path=root_path,
                context_identity=True,
            )
            assert refusal["status"] == "failed_execution"
            assert refusal["primary_error"] == "RepresentationValidationError:schema_preexisting"
            collision = json_exec(
                "SELECT json_build_object("
                f"'schema_exists', EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = '{DISPOSABLE_SCHEMA}'), "
                f"'sentinel_exists', to_regclass('{sentinel_table}') IS NOT NULL)::text;"
            )
            assert collision == {"schema_exists": True, "sentinel_exists": True}
        finally:
            # This fixture owns exactly the sentinel it created; the experiment never owns this namespace.
            ddl_exec(f"DROP TABLE {sentinel_table}; DROP SCHEMA {DISPOSABLE_SCHEMA};")

        # 3. Run full equality-first experiment at generation 2 (with both current and historical windows populated)
        report = run_jsonb_evidence_experiment(
            workload_g2,
            json_executor=json_exec,
            ddl_executor=ddl_exec,
            explain_executor=explain_exec,
            repository_identity=repo_id,
            root_path=root_path,
            context_identity=True,
            fail_on_malformed_facets=True,
        )

        assert report["status"] == "passed", {"primary_error": report.get("primary_error"), "failures": report.get("failures"), "mismatches": report.get("mismatches")}
        assert report["equality_passed"] is True
        assert report["mismatches"] == []
        assert report["projected_row_count"] > 20
        assert report["malformed_metadata_count"] == 0
        assert report["cleanup_verified"] is True
        assert report["projection_refresh_ms"] >= 0.0
        assert report["execution_declaration"]["repetitions"] == 1
        assert report["disposition_evidence"]["equality_passed"] is True
        assert report["disposition_evidence"]["measurements_status"] == "measured"
        assert report["recommended_disposition"] in {"retain_relational_baseline", "evaluate_jsonb_if_net_positive"}

        # Verify index byte accounting and EXPLAIN plan capture across all 4 variants
        assert report["index_accounting"]["jsonb_no_index"]["indexes_bytes"] == 0
        assert report["index_accounting"]["jsonb_gin_ops"]["indexes_bytes"] > 0
        assert report["index_accounting"]["jsonb_gin_path_ops"]["indexes_bytes"] > 0

        for v_name in VARIANT_NAMES:
            plans = report["explain_summaries"][v_name]
            assert len(plans) == len(workload_g2)
            for p_summary in plans:
                assert len(p_summary["plan_node_types"]) >= 1
                assert isinstance(p_summary["used_gin_index"], bool)
                assert isinstance(p_summary["used_seq_scan"], bool)
                assert p_summary["execution_time_ms"] >= 0.0

        assert_canary_free(report)
        print("CLOE_W5_JSONB_REPORT " + json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False), flush=True)
