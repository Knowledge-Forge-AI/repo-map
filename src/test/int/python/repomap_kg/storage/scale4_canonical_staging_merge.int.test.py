from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest

from repomap_kg.runtime.database_roles import (
    REFRESH_PUBLICATION_ROLE,
    RoleSecrets,
    render_database_role_sql,
)
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.canonical_staging_merge import build_canonical_merge_statements
from repomap_kg.storage.readback_driver import _psycopg_connection_params_from_psql_args
from repomap_kg.storage.staging_copy import STAGING_COPY_TABLES, copy_stage_rows
from repomap_test_support.canonical_merge_reference import (
    build_reference_edge_evidence_merge_statement, check_temp_tables_analyzed as _check_temp_analyzed,
    copy_canonical_fixture as _copy_canonical_fixture, copy_multi_run_canonical_fixtures as _copy_multi_run,
    copy_diagnostic_fixture as _copy_diag, create_repository_run_stage as _create_repository_run_stage,
    execute_merge as _merge, insert_raw_fixture as _insert_raw_fixture, inspect_plan_nodes as _inspect_plan,
    measure_fixture_cardinalities as _measure_cardinalities, merge_context as _context,
    query_canonical_edge_evidence as _query_edge_ev, extract_plan_triggers as _extract_plan_triggers,
)
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)


def test_canonical_set_merge_is_idempotent_and_preserves_identity() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        repo_id, run_id = _create_repository_run_stage(postgres, "stage-canonical-success")
        _insert_raw_fixture(postgres, repo_id, run_id)
        conninfo = " ".join(f"{k}={v}" for k, v in _psycopg_connection_params_from_psql_args(postgres.psql_args).items())
        with psycopg.connect(conninfo) as connection:
            _copy_canonical_fixture(connection, "stage-canonical-success")
            connection.commit()
            _merge(connection, repo_id, run_id, "stage-canonical-success")
            connection.commit()
            _merge(connection, repo_id, run_id, "stage-canonical-success")
            connection.commit()
            with connection.cursor() as cursor:
                cursor.execute("""
SELECT (SELECT count(*) FROM canonical_nodes), (SELECT count(*) FROM canonical_edges),
       (SELECT count(*) FROM canonical_evidence), (SELECT count(*) FROM canonical_node_evidence),
       (SELECT count(*) FROM canonical_edge_evidence), (SELECT raw_observation_id IS NOT NULL FROM canonical_evidence),
       (SELECT display_name FROM canonical_nodes WHERE canonical_key = 'node:source')
""")
                assert cursor.fetchone() == (2, 1, 1, 1, 1, True, "source")


def test_canonical_set_merge_rejects_conflicts_and_caller_rollback() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        repo_id, run_id = _create_repository_run_stage(postgres, "stage-canonical-conflict")
        conninfo = " ".join(f"{k}={v}" for k, v in _psycopg_connection_params_from_psql_args(postgres.psql_args).items())
        with psycopg.connect(conninfo) as connection:
            copy_stage_rows(connection, STAGING_COPY_TABLES["canonical_nodes"], [
                {"stage_id": "stage-canonical-conflict", "family_ordinal": 0, "graph_key_version": 1, "canonical_key": "node:conflict", "kind": "function", "display_name": "first", "metadata_json": {}, "confidence": "extracted", "conflict": False},
                {"stage_id": "stage-canonical-conflict", "family_ordinal": 1, "graph_key_version": 1, "canonical_key": "node:conflict", "kind": "function", "display_name": "second", "metadata_json": {}, "confidence": "extracted", "conflict": False},
            ], expected_stage_id="stage-canonical-conflict")
            connection.commit()
            with pytest.raises(psycopg.errors.RaiseException, match="SCALE4 stage validation conflict"):
                _merge(connection, repo_id, run_id, "stage-canonical-conflict")
            connection.rollback()
            assert postgres.psql_scalar("SELECT count(*) FROM canonical_nodes") == "0"

            postgres.psql_scalar(
                f"INSERT INTO ingestion_stages(stage_id, repository_id, operation_id, attempt, execution_mode, source_generation, config_generation, extractor_generation, canonicalizer_generation, state, validation_status, expires_at) "
                f"VALUES ('stage-canonical-rollback', {repo_id}, 'operation-stage-canonical-rollback', 1, 'direct', 'sg1:source', 'cg1:config', 'eg1:extractor', 'kg1:canonicalizer', 'validated', 'passed', now() + interval '1 hour');"
            )
            copy_stage_rows(connection, STAGING_COPY_TABLES["canonical_nodes"], [
                {"stage_id": "stage-canonical-rollback", "family_ordinal": 0, "graph_key_version": 1, "canonical_key": "node:rollback", "kind": "function", "display_name": "rollback", "metadata_json": {}, "confidence": "extracted", "conflict": False}
            ], expected_stage_id="stage-canonical-rollback")
            connection.commit()
            with pytest.raises(psycopg.errors.DivisionByZero):
                with connection.cursor() as cursor:
                    for statement in build_canonical_merge_statements(_context(repo_id, run_id, "stage-canonical-rollback"))[:4]:
                        cursor.execute(statement)
                    cursor.execute("SELECT 1 / 0")
            connection.rollback()
            assert postgres.psql_scalar("SELECT count(*) FROM canonical_nodes") == "0"


def test_canonical_set_merge_rejects_missing_edge_references() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        repository_id, run_id = _create_repository_run_stage(postgres, "stage-canonical-missing")
        connection_params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in connection_params.items())
        with psycopg.connect(conninfo) as connection:
            copy_stage_rows(
                connection,
                STAGING_COPY_TABLES["canonical_edges"],
                [{"stage_id": "stage-canonical-missing", "family_ordinal": 0, "graph_key_version": 1, "source_canonical_key": "node:missing-source", "edge_kind": "calls", "target_canonical_key": "node:missing-target", "identity_metadata_json": {}, "identity_metadata_hash": "c" * 64, "metadata_json": {}, "confidence": "extracted", "conflict": False}],
                expected_stage_id="stage-canonical-missing",
            )
            connection.commit()
            with pytest.raises(psycopg.errors.RaiseException, match="SCALE4 canonical edge reference is missing"):
                _merge(connection, repository_id, run_id, "stage-canonical-missing")
            connection.rollback()


def test_canonical_set_merge_materialized_parity_and_query_plan() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        connection_params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in connection_params.items())

        repo_mat, run_mat = _create_repository_run_stage(postgres, "stage-mat", "-mat")
        _insert_raw_fixture(postgres, repo_mat, run_mat)
        repo_unmat, run_unmat = _create_repository_run_stage(postgres, "stage-unmat", "-unmat")
        _insert_raw_fixture(postgres, repo_unmat, run_unmat)

        with psycopg.connect(conninfo) as connection:
            _copy_canonical_fixture(connection, "stage-mat")
            _copy_canonical_fixture(connection, "stage-unmat")
            connection.commit()

            stmts_mat = build_canonical_merge_statements(_context(repo_mat, run_mat, "stage-mat"))
            stmts_unmat = tuple(stmt.replace("WITH staged_links AS MATERIALIZED (", "WITH staged_links AS (") for stmt in build_canonical_merge_statements(_context(repo_unmat, run_unmat, "stage-unmat")))
            node_ev_mat_stmt = [s for s in stmts_mat if "canonical_node_evidence" in s and "INSERT INTO" in s][0]
            node_ev_unmat_stmt = [s for s in stmts_unmat if "canonical_node_evidence" in s and "INSERT INTO" in s][0]
            edge_ev_mat_stmt = [s for s in stmts_mat if "canonical_edge_evidence" in s and "INSERT INTO" in s][0]
            edge_ev_unmat_stmt = [s for s in stmts_unmat if "canonical_edge_evidence" in s and "INSERT INTO" in s][0]

            with connection.cursor() as cursor:
                for s in stmts_mat:
                    if s == node_ev_mat_stmt:
                        break
                    cursor.execute(s)
                for s in stmts_unmat:
                    if s == node_ev_unmat_stmt:
                        break
                    cursor.execute(s)

                for stmt in (node_ev_mat_stmt, node_ev_unmat_stmt, edge_ev_mat_stmt, edge_ev_unmat_stmt):
                    cursor.execute(f"EXPLAIN (ANALYZE, FORMAT JSON) {stmt}")
                    plan = cursor.fetchone()
                    assert plan is not None and isinstance(plan[0], list) and len(plan[0]) > 0

                for stmt in (node_ev_mat_stmt, edge_ev_mat_stmt, node_ev_unmat_stmt, edge_ev_unmat_stmt):
                    cursor.execute(stmt)
                connection.commit()

            with connection.cursor() as cursor:
                for tbl, id_col, exp_kind in (("canonical_node_evidence", "canonical_node_id", "definition"), ("canonical_edge_evidence", "canonical_edge_id", "call-site")):
                    res = []
                    target_tbl = tbl.replace("_evidence", "s")
                    for repo in (repo_mat, repo_unmat):
                        cursor.execute(f"SELECT link_kind, count(*) FROM {tbl} WHERE {id_col} IN (SELECT id FROM {target_tbl} WHERE repository_id = %s) GROUP BY link_kind ORDER BY link_kind", (int(repo),))
                        res.append(cursor.fetchall())
                    assert res[0] == res[1] == [(exp_kind, 1)]


def test_canonical_merge_under_refresh_publication_role() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        secrets = RoleSecrets("read-secret", "refresh-secret", "control-secret")
        admin_params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(psycopg.conninfo.make_conninfo(**admin_params)) as admin_conn:
            admin_conn.execute(
                render_database_role_sql(
                    database=postgres.database,
                    owner_role=postgres.user,
                    database_kind="graph",
                    secrets=secrets,
                )
            )
            admin_conn.commit()

        repository_id, run_id = _create_repository_run_stage(postgres, "stage-refresh-role")
        _insert_raw_fixture(postgres, repository_id, run_id)

        refresh_conninfo = psycopg.conninfo.make_conninfo(
            **{
                **_psycopg_connection_params_from_psql_args(postgres.psql_args),
                "user": REFRESH_PUBLICATION_ROLE,
                "password": secrets.refresh_publication,
            }
        )

        with psycopg.connect(refresh_conninfo) as connection:
            _copy_canonical_fixture(connection, "stage-refresh-role")
            connection.commit()

            with connection.cursor() as cursor:
                cursor.execute("BEGIN")
                for stmt in build_canonical_merge_statements(_context(repository_id, run_id, "stage-refresh-role")):
                    cursor.execute(stmt)
                cursor.execute("COMMIT")

            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) FROM canonical_nodes WHERE repository_id = %s", (int(repository_id),))
                node_row = cursor.fetchone()
                assert node_row is not None and node_row[0] == 2
                cursor.execute(
                    "SELECT count(*) FROM canonical_edge_evidence WHERE canonical_edge_id IN "
                    "(SELECT id FROM canonical_edges WHERE repository_id = %s)",
                    (int(repository_id),),
                )
                edge_ev_row = cursor.fetchone()
                assert edge_ev_row is not None and edge_ev_row[0] == 1


def test_canonical_edge_evidence_merge_temp_collision_fails_closed() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        repository_id, run_id = _create_repository_run_stage(postgres, "stage-collision")
        _insert_raw_fixture(postgres, repository_id, run_id)
        connection_params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        conninfo = " ".join(f"{k}={v}" for k, v in connection_params.items())
        with psycopg.connect(conninfo) as connection:
            _copy_canonical_fixture(connection, "stage-collision")
            connection.commit()
            with connection.cursor() as cursor:
                cursor.execute("CREATE TEMP TABLE temp_canonical_edge_map (id int)")
                with pytest.raises(psycopg.errors.DuplicateTable):
                    _merge(connection, repository_id, run_id, "stage-collision")
            connection.rollback()


def test_canonical_edge_evidence_variant_f_parity_with_reference_helper() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        conninfo = " ".join(f"{k}={v}" for k, v in _psycopg_connection_params_from_psql_args(postgres.psql_args).items())
        repo_f, run_f1 = _create_repository_run_stage(postgres, "stage-f1", "-f")
        _, run_f2 = _create_repository_run_stage(postgres, "stage-f2", repository_id=repo_f)
        repo_ref, run_r1 = _create_repository_run_stage(postgres, "stage-r1", "-ref")
        _, run_r2 = _create_repository_run_stage(postgres, "stage-r2", repository_id=repo_ref)
        for r, runs in ((repo_f, (run_f1, run_f2)), (repo_ref, (run_r1, run_r2))):
            _insert_raw_fixture(postgres, r, runs[0], (0, 1))
            _insert_raw_fixture(postgres, r, runs[1], (2, 3))
        with psycopg.connect(conninfo) as connection:
            for stg, idx in (("stage-f1", 1), ("stage-f2", 2), ("stage-r1", 1), ("stage-r2", 2)):
                _copy_multi_run(connection, stg, idx)
            connection.commit()
            for r, run, stg in ((repo_f, run_f1, "stage-f1"), (repo_f, run_f2, "stage-f2"),
                                (repo_ref, run_r1, "stage-r1"), (repo_ref, run_r2, "stage-r2")):
                with connection.cursor() as cursor:
                    for stmt in build_canonical_merge_statements(_context(r, run, stg))[:-1]:
                        cursor.execute(stmt)
                connection.commit()
            for run, stg in ((run_f1, "stage-f1"), (run_f2, "stage-f2")):
                edge_ev_stmt = build_canonical_merge_statements(_context(repo_f, run, stg))[-1]
                with connection.cursor() as cursor:
                    cursor.execute(edge_ev_stmt)
                    cursor.execute(edge_ev_stmt)
                connection.commit()
            for run, stg in ((run_r1, "stage-r1"), (run_r2, "stage-r2")):
                ref_stmt = build_reference_edge_evidence_merge_statement(f"'{stg}'", repo_ref, run)
                with connection.cursor() as cursor:
                    cursor.execute(ref_stmt)
                    cursor.execute(ref_stmt)
                connection.commit()
            rows_f, rows_ref = _query_edge_ev(connection, repo_f), _query_edge_ev(connection, repo_ref)
            assert rows_f == rows_ref and len(rows_f) == 5
            assert _query_edge_ev(connection, repo_f, run_f1) == [
                ("node:n1", "calls", "node:n2", "ev:1", "call-site"),
                ("node:n1", "calls", "node:n2", "ev:1", "type-ref"),
                ("node:n2", "calls", "node:n3", "ev:2", "call-site"),
            ]
            assert _query_edge_ev(connection, repo_f, run_f2) == [
                ("node:n1", "calls", "node:n2", "ev:3", "call-site"),
                ("node:n2", "calls", "node:n3", "ev:4", "type-ref"),
            ]


def test_canonical_identity_keys_reject_null_and_empty_values() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        repo1, run1 = _create_repository_run_stage(postgres, "stage-c1")
        _, run2 = _create_repository_run_stage(postgres, "stage-c2", repository_id=repo1)
        repo2, run3 = _create_repository_run_stage(postgres, "stage-c3", "-r2")
        for r, run in ((repo1, run1), (repo1, run2), (repo2, run3)):
            _insert_raw_fixture(postgres, r, run)
        conninfo = " ".join(f"{k}={v}" for k, v in _psycopg_connection_params_from_psql_args(postgres.psql_args).items())
        with psycopg.connect(conninfo) as connection:
            _copy_canonical_fixture(connection, "stage-c1")
            connection.commit()
            with connection.cursor() as cursor:
                for s in build_canonical_merge_statements(_context(repo1, run1, "stage-c1"))[:6]:
                    cursor.execute(s)
            connection.commit()
            with connection.cursor() as cursor, pytest.raises(psycopg.errors.NotNullViolation):
                cursor.execute(
                    "INSERT INTO canonical_edges(repository_id, graph_key_version, source_canonical_key, "
                    "edge_kind, target_canonical_key, identity_metadata_json, identity_metadata_hash, "
                    "metadata_json, confidence, conflict, first_seen_run_id, last_seen_run_id) "
                    "VALUES (%s, 1, NULL, 'calls', 'target', '{}', %s, '{}', 'extracted', false, %s, %s)",
                    (int(repo1), "x" * 64, int(run1), int(run1)),
                )
            connection.rollback()
            for bad_key in ({"source_canonical_key": ""}, {"evidence_key": ""}):
                with pytest.raises(psycopg.errors.CheckViolation):
                    copy_stage_rows(connection, STAGING_COPY_TABLES["canonical_edge_evidence"], [
                        {"stage_id": "stage-c1", "family_ordinal": 0, "graph_key_version": 1,
                         "source_canonical_key": "node:source", "edge_kind": "calls", "target_canonical_key": "node:target",
                         "identity_metadata_hash": "a" * 64, "evidence_key": "evidence:source", "link_kind": "call-site", **bad_key},
                    ], expected_stage_id="stage-c1")
                connection.rollback()
            for row in ({"source_canonical_key": "node:missing"}, {"evidence_key": "evidence:missing"}):
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM stage_canonical_edge_evidence WHERE stage_id = 'stage-c1'")
                connection.commit()
                copy_stage_rows(connection, STAGING_COPY_TABLES["canonical_edge_evidence"], [
                    {"stage_id": "stage-c1", "family_ordinal": 0, "graph_key_version": 1, "source_canonical_key": "node:source",
                     "edge_kind": "calls", "target_canonical_key": "node:target", "identity_metadata_hash": "a" * 64,
                     "evidence_key": "evidence:source", "link_kind": "call-site", **row},
                ], expected_stage_id="stage-c1")
                connection.commit()
                with pytest.raises(psycopg.errors.RaiseException, match="SCALE4 canonical edge-evidence reference is missing"):
                    _merge(connection, repo1, run1, "stage-c1")
                connection.rollback()
            for repo, run, stg in ((repo2, run3, "stage-c3"), (repo1, run2, "stage-c2")):
                copy_stage_rows(connection, STAGING_COPY_TABLES["canonical_edge_evidence"], [
                    {"stage_id": stg, "family_ordinal": 0, "graph_key_version": 1, "source_canonical_key": "node:source",
                     "edge_kind": "calls", "target_canonical_key": "node:target", "identity_metadata_hash": "a" * 64,
                     "evidence_key": "evidence:source", "link_kind": "call-site"},
                ], expected_stage_id=stg)
                connection.commit()
                with pytest.raises(psycopg.errors.RaiseException, match="SCALE4 canonical edge-evidence reference is missing"):
                    _merge(connection, repo, run, stg)
                connection.rollback()


def test_canonical_edge_evidence_explain_diagnostics_outbox(tmp_path: Path) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(default_rdbms_root(), postgres.psql_args, psql_command=postgres.psql_command)
        secrets = RoleSecrets("read-secret", "refresh-secret", "control-secret")
        admin_params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(psycopg.conninfo.make_conninfo(**admin_params)) as admin_conn:
            admin_conn.execute(
                render_database_role_sql(database=postgres.database, owner_role=postgres.user, database_kind="graph", secrets=secrets)
            )
            admin_conn.commit()
        repo, run = _create_repository_run_stage(postgres, "stage-explain")
        _insert_raw_fixture(postgres, repo, run, tuple(range(50)), diagnostic=True)
        refresh_conninfo = psycopg.conninfo.make_conninfo(
            **{**admin_params, "user": REFRESH_PUBLICATION_ROLE, "password": secrets.refresh_publication}
        )
        with psycopg.connect(refresh_conninfo) as connection:
            _copy_diag(connection, "stage-explain", count=50)
            connection.commit()
            cardinalities = _measure_cardinalities(connection, "stage-explain")
            statements = build_canonical_merge_statements(_context(repo, run, "stage-explain"))
            with connection.cursor() as cursor:
                cursor.execute("BEGIN")
                for s in statements[:-1]:
                    cursor.execute(s)
                pre_insert, insert_and_drop = statements[-1].split("WITH staged_links AS", 1)
                insert_sql, drop_sql = insert_and_drop.split("DROP TABLE IF EXISTS", 1)
                insert_stmt = "WITH staged_links AS" + insert_sql.rstrip("; \n")
                cursor.execute(pre_insert)
                cursor.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {insert_stmt}")
                row = cursor.fetchone()
                assert row is not None
                plan_json = row[0]
                cursor.execute(insert_stmt)
                temp_analyzed = _check_temp_analyzed(connection)
                cursor.execute("DROP TABLE IF EXISTS" + drop_sql)
                cursor.execute("COMMIT")
            node_types, rel_names, temp_written = _inspect_plan(plan_json[0]["Plan"])
            assert temp_written == 0
            repeated_probes_absent = "canonical_edges" not in rel_names and "canonical_evidence" not in rel_names
            assert repeated_probes_absent is True
            assert "temp_canonical_edge_map" in rel_names and "temp_canonical_evidence_map" in rel_names and temp_analyzed
            explain_triggers = _extract_plan_triggers(plan_json[0])
            payload = {
                "schema_version": 1, "strategy": "Variant F (session-local temporary target maps with ANALYZE)",
                "role": REFRESH_PUBLICATION_ROLE, "fixture_cardinalities": cardinalities,
                "analyze_temp_tables_succeeded": temp_analyzed, "repeated_permanent_target_probes_absent_in_plan_nodes": repeated_probes_absent,
                "explain_triggers": explain_triggers, "join_families": [t for t in node_types if "Join" in t],
                "temp_written_blocks": temp_written, "relations_scanned": rel_names,
                "timing_diagnostic_non_gating": {
                    "planning_time_ms": plan_json[0].get("Planning Time"), "execution_time_ms": plan_json[0].get("Execution Time"),
                },
                "query_plan": plan_json,
            }
            print(f"DIAGNOSTICS_JSON_START\n{json.dumps(payload)}\nDIAGNOSTICS_JSON_END")
            (tmp_path / "scale4_explain_diagnostics.json").write_text(json.dumps(payload, indent=2))
