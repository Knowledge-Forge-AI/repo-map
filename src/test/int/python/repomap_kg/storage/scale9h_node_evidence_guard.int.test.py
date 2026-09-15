from __future__ import annotations

import time
from threading import Event, Thread

import psycopg
import pytest

from psycopg.conninfo import make_conninfo
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.canonical_staging_merge import build_canonical_merge_statements
from repomap_kg.storage.readback_driver import _psycopg_connection_params_from_psql_args
from repomap_kg.storage.staging_copy import STAGING_COPY_TABLES, copy_stage_rows
from repomap_kg.storage.staging_merge import MergeContext
from repomap_kg.storage.staging_ownership import AttemptNumber, OperationId, StageOwner
from repomap_test_support.postgres_harness import (
    PostgresContainerDatabase,
    require_postgres_binaries,
    temporary_postgres,
)


_NODE_PLAN_QUERY = (
    "SELECT 1 FROM (SELECT staged.graph_key_version, staged.canonical_key "
    "FROM stage_canonical_node_evidence staged WHERE staged.stage_id = %s) AS staged "
    "FULL JOIN (SELECT node.graph_key_version, node.canonical_key FROM canonical_nodes node "
    "WHERE node.repository_id = %s) AS node ON node.graph_key_version = staged.graph_key_version "
    "AND node.canonical_key = staged.canonical_key WHERE COALESCE(staged.canonical_key, '') <> '' "
    "AND node.canonical_key IS NULL LIMIT 1"
)

_EVIDENCE_PLAN_QUERY = (
    "SELECT 1 FROM (SELECT staged.graph_key_version, staged.evidence_key "
    "FROM stage_canonical_node_evidence staged WHERE staged.stage_id = %s) AS staged "
    "FULL JOIN (SELECT evidence.graph_key_version, evidence.evidence_key FROM canonical_evidence evidence "
    "WHERE evidence.repository_id = %s AND evidence.run_id = %s) AS evidence "
    "ON evidence.graph_key_version = staged.graph_key_version AND evidence.evidence_key = staged.evidence_key "
    "WHERE COALESCE(staged.evidence_key, '') <> '' AND evidence.evidence_key IS NULL LIMIT 1"
)


def _connect(
    postgres: PostgresContainerDatabase,
) -> psycopg.Connection[tuple[object, ...]]:
    params = _psycopg_connection_params_from_psql_args(postgres.psql_args)
    return psycopg.Connection.connect(make_conninfo("", **params))


def _create_repository_run_stage(
    postgres: PostgresContainerDatabase, stage_id: str
) -> tuple[int, int]:
    repository_id = int(postgres.psql_scalar(
        "INSERT INTO repositories(name, root_path) VALUES ('fixture', 'fixture-root'); "
        "SELECT id FROM repositories WHERE root_path = 'fixture-root';"
    ))
    run_id = int(postgres.psql_scalar(
        f"INSERT INTO runs(repository_id, git_commit) VALUES ({repository_id}, 'fixture-commit'); "
        f"SELECT id FROM runs WHERE repository_id = {repository_id};"
    ))
    postgres.psql_scalar(
        f"INSERT INTO ingestion_stages("
        f"stage_id, repository_id, operation_id, attempt, execution_mode, "
        f"source_generation, config_generation, extractor_generation, "
        f"canonicalizer_generation, state, validation_status, expires_at) "
        f"VALUES ('{stage_id}', {repository_id}, 'operation-{stage_id}', 1, 'direct', "
        f"'sg1:source', 'cg1:config', 'eg1:extractor', 'kg1:canonicalizer', "
        f"'validated', 'passed', now() + interval '1 hour');"
    )
    return repository_id, run_id


def _context(repository_id: int, run_id: int, stage_id: str) -> MergeContext:
    return MergeContext(
        stage_id=stage_id,
        owner=StageOwner(
            repository_id=repository_id,
            operation_id=OperationId(f"operation-{stage_id}"),
            attempt=AttemptNumber(1),
            execution_mode="direct",
            source_generation="sg1:source",
            config_generation="cg1:config",
            extractor_generation="eg1:extractor",
            canonicalizer_generation="kg1:canonicalizer",
        ),
        run_id=run_id,
    )


def _copy_links(connection, stage_id: str, rows: list[dict[str, object]]) -> None:
    copy_stage_rows(
        connection,
        STAGING_COPY_TABLES["canonical_node_evidence"],
        rows,
        expected_stage_id=stage_id,
    )


def _seed_references(
    connection, repository_id: int, run_id: int, *, node: bool, evidence: bool
) -> None:
    with connection.cursor() as cursor:
        if node:
            cursor.execute(
                """
INSERT INTO canonical_nodes(
    repository_id, graph_key_version, canonical_key, kind, display_name,
    metadata_json, confidence, first_seen_run_id, last_seen_run_id
)
VALUES (%s, 1, 'node:fixture', 'function', 'fixture', '{}'::jsonb,
        'extracted', %s, %s)
                """,
                (repository_id, run_id, run_id),
            )
        if evidence:
            cursor.execute(
                """
INSERT INTO canonical_evidence(
    repository_id, run_id, graph_key_version, evidence_key,
    raw_observation_ordinal, raw_schema_version, raw_kind, raw_source_id,
    path, extractor, extractor_version, confidence, metadata_json
)
VALUES (%s, %s, 1, 'evidence:fixture', 0, 1, 'fixture', 'fixture:source',
        'fixture/root', 'fixture', 'fixture-1', 'extracted', '{}'::jsonb)
                """,
                (repository_id, run_id),
            )


def _guard(repository_id: int, run_id: int, stage_id: str) -> str:
    return build_canonical_merge_statements(
        _context(repository_id, run_id, stage_id)
    )[7]


def _final_counts(connection, run_id: int) -> tuple[int, int, int, int]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT (SELECT count(*) FROM canonical_nodes), "
            "(SELECT count(*) FROM canonical_evidence), "
            "(SELECT count(*) FROM canonical_node_evidence), "
            "(SELECT count(*) FROM runs WHERE id = %s AND publication_job_id IS NOT NULL)",
            (run_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        return (int(row[0]), int(row[1]), int(row[2]), int(row[3]))


def _plan_nodes(plan: dict[str, object]) -> list[dict[str, object]]:
    nodes = [plan]
    plans = plan.get("Plans", [])
    if isinstance(plans, list):
        for child in plans:
            if isinstance(child, dict):
                nodes.extend(_plan_nodes(child))
    return nodes


def _wait_for_lock(locker, backend_pid: int) -> None:
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        with locker.cursor() as cursor:
            cursor.execute(
                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                (backend_pid,),
            )
            row = cursor.fetchone()
        if row == ("Lock",):
            return
        time.sleep(0.01)
    raise AssertionError("node-evidence guard did not wait on the fixture lock")


def test_node_evidence_guard_accepts_duplicate_links_once() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        repository_id, run_id = _create_repository_run_stage(
            postgres, "stage-node-evidence-duplicates"
        )
        with _connect(postgres) as connection:
            _copy_links(
                connection,
                "stage-node-evidence-duplicates",
                [
                    {
                        "stage_id": "stage-node-evidence-duplicates",
                        "family_ordinal": ordinal,
                        "graph_key_version": 1,
                        "canonical_key": "node:fixture",
                        "evidence_key": "evidence:fixture",
                        "link_kind": "definition",
                    }
                    for ordinal in (0, 1)
                ],
            )
            connection.commit()
            _seed_references(connection, repository_id, run_id, node=True, evidence=True)
            with connection.cursor() as cursor:
                statements = build_canonical_merge_statements(
                    _context(repository_id, run_id, "stage-node-evidence-duplicates")
                )
                cursor.execute(statements[7])
                cursor.execute(statements[8])
            connection.commit()
            assert _final_counts(connection, run_id) == (1, 1, 1, 0)


@pytest.mark.parametrize(("node", "evidence"), ((False, True), (True, False)))
def test_node_evidence_guard_refuses_missing_references_and_rolls_back(
    node: bool, evidence: bool
) -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        stage_id = f"stage-node-evidence-missing-{int(node)}-{int(evidence)}"
        repository_id, run_id = _create_repository_run_stage(postgres, stage_id)
        with _connect(postgres) as connection:
            _copy_links(
                connection,
                stage_id,
                [
                    {
                        "stage_id": stage_id,
                        "family_ordinal": 0,
                        "graph_key_version": 1,
                        "canonical_key": "node:fixture",
                        "evidence_key": "evidence:fixture",
                        "link_kind": "definition",
                    }
                ],
            )
            connection.commit()
            _seed_references(connection, repository_id, run_id, node=node, evidence=evidence)
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="SCALE4 canonical node-evidence reference is missing",
            ) as raised:
                with connection.cursor() as cursor:
                    cursor.execute(_guard(repository_id, run_id, stage_id))
            diagnostic = str(raised.value)
            assert stage_id not in diagnostic
            assert "node:fixture" not in diagnostic
            assert "evidence:fixture" not in diagnostic
            connection.rollback()
            assert _final_counts(connection, run_id) == (0, 0, 0, 0)


def test_node_evidence_guard_is_caller_owned_after_success() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        stage_id = "stage-node-evidence-rollback"
        repository_id, run_id = _create_repository_run_stage(postgres, stage_id)
        with _connect(postgres) as connection:
            _copy_links(
                connection,
                stage_id,
                [
                    {
                        "stage_id": stage_id,
                        "family_ordinal": 0,
                        "graph_key_version": 1,
                        "canonical_key": "node:fixture",
                        "evidence_key": "evidence:fixture",
                        "link_kind": "definition",
                    }
                ],
            )
            connection.commit()
            _seed_references(connection, repository_id, run_id, node=True, evidence=True)
            with pytest.raises(psycopg.errors.DivisionByZero):
                with connection.cursor() as cursor:
                    cursor.execute(_guard(repository_id, run_id, stage_id))
                    cursor.execute("SELECT 1 / 0")
            connection.rollback()
            assert _final_counts(connection, run_id) == (0, 0, 0, 0)


def test_node_evidence_guard_plan_uses_full_joins_without_nested_probes() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        stage_id = "stage-node-evidence-plan"
        repository_id, run_id = _create_repository_run_stage(postgres, stage_id)
        with _connect(postgres) as connection:
            _copy_links(
                connection,
                stage_id,
                [
                    {
                        "stage_id": stage_id,
                        "family_ordinal": ordinal,
                        "graph_key_version": 1,
                        "canonical_key": "node:fixture",
                        "evidence_key": "evidence:fixture",
                        "link_kind": "definition",
                    }
                    for ordinal in range(32)
                ],
            )
            _seed_references(connection, repository_id, run_id, node=True, evidence=True)
            connection.commit()
            with connection.cursor() as cursor:
                for query, parameters in (
                    (_NODE_PLAN_QUERY, (stage_id, repository_id)),
                    (_EVIDENCE_PLAN_QUERY, (stage_id, repository_id, run_id)),
                ):
                    cursor.execute(f"EXPLAIN (FORMAT JSON) {query}", parameters)
                    row = cursor.fetchone()
                    assert row is not None
                    raw = row[0]
                    assert isinstance(raw, list) and len(raw) > 0
                    plan = raw[0]["Plan"]
                    assert isinstance(plan, dict)
                    nodes = _plan_nodes(plan)
                    assert any(node.get("Join Type") == "Full" for node in nodes)
                    assert all(node.get("Node Type") != "Nested Loop" for node in nodes)


def test_node_evidence_guard_cancellation_rolls_back_without_receipt() -> None:
    require_postgres_binaries()

    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        stage_id = "stage-node-evidence-cancel"
        repository_id, run_id = _create_repository_run_stage(postgres, stage_id)
        with _connect(postgres) as connection, _connect(postgres) as locker:
            _copy_links(
                connection,
                stage_id,
                [
                    {
                        "stage_id": stage_id,
                        "family_ordinal": 0,
                        "graph_key_version": 1,
                        "canonical_key": "node:fixture",
                        "evidence_key": "evidence:fixture",
                        "link_kind": "definition",
                    }
                ],
            )
            connection.commit()
            _seed_references(connection, repository_id, run_id, node=True, evidence=True)
            with locker.cursor() as cursor:
                cursor.execute(
                    "LOCK TABLE stage_canonical_node_evidence IN ACCESS EXCLUSIVE MODE"
                )
            started = Event()
            errors: list[BaseException] = []

            def execute_guard() -> None:
                started.set()
                try:
                    with connection.cursor() as cursor:
                        cursor.execute(_guard(repository_id, run_id, stage_id))
                except BaseException as error:
                    errors.append(error)

            worker = Thread(target=execute_guard)
            worker.start()
            assert started.wait(timeout=1.0)
            try:
                _wait_for_lock(locker, connection.info.backend_pid)
                cancelled_at = time.monotonic()
                connection.cancel_safe(timeout=1.0)
                worker.join(timeout=5.0)
                assert time.monotonic() - cancelled_at < 5.0
                assert not worker.is_alive()
                assert len(errors) == 1
                assert isinstance(errors[0], psycopg.errors.QueryCanceled)
            finally:
                locker.rollback()
            connection.rollback()
            assert _final_counts(connection, run_id) == (0, 0, 0, 0)
