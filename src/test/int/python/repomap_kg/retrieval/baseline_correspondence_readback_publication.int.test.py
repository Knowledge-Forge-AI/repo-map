"""Publisher-backed current-publication identity and repository-isolation checks."""

from __future__ import annotations

from pathlib import Path
import json
import sqlite3
from typing import Any

import psycopg
import pytest

from common_lore_index.ops.config_local import (
    LocalSqliteConfig,
    load_graph_registry_config_home,
    local_graph_binding,
    sqlite_graph_database_path,
)
from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.server.context_read_sqlite import SqliteContextReadAdapter
from common_lore_index.storage import apply_migrations, default_rdbms_root
from common_lore_index.storage.context_postgres_identity import (
    read_postgres_context_identity_with_executor,
)
from common_lore_index.storage.readback_driver import execute_json_readback
from common_lore_index.storage.staged_ingestion import run_staged_portable_refresh
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.portable_publication_fixtures import (
    authority,
    binding,
    seven_family_bundle,
)
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID,
    materialize_mixed_v1_working_copy,
    binding_id_for_alias,
    write_mixed_v1_postgres_home,
    write_mixed_v1_sqlite_home,
)
from repomap_test_support.retrieval_evaluation_publication import (
    publish_and_load_sqlite_corpus,
    publish_and_load_postgres_corpus,
    read_sqlite_accepted_publication,
)
from retrieval_evaluation_correspondence_observation_records import FencedObservationResult
from retrieval_evaluation_current_observations import query_fenced_current_observations
from retrieval_evaluation_observation_contracts import CurrentObservationReadError


def _clone_sqlite_complete_run(db_path: Path, source_run_id: int, new_run_id: int) -> None:
    """Create one complete, receipt-bearing row without moving accepted_publication."""
    columns = (
        "status, started_at, finished_at, publisher, execution_route, "
        "portable_protocol_version, snapshot_manifest_id, snapshot_vector_json, "
        "extraction_receipt_id, publication_bundle_id, graph_candidate_id, "
        "resolver_identity, portable_canonicalizer_identity, semantic_contract_identity, "
        "quality_rule_identity, worker_capability_identity, portable_stage_id, "
        "portable_execution_mode, source_generation, config_generation, extractor_generation, "
        "canonicalizer_generation, family_receipts_json, privacy"
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            f"INSERT INTO runs (id, previous_run_id, {columns}, publication_job_id, publication_attempt) "
            f"SELECT ?, ?, {columns}, publication_job_id || '-late', publication_attempt + 1 "
            "FROM runs WHERE id = ?",
            (new_run_id, source_run_id, source_run_id),
        )
        connection.commit()


def _clone_postgres_complete_run(
    connection: Any,
    *,
    source_run_id: int,
    repository_id: int,
    suffix: str,
    attempt_delta: int,
) -> None:
    """Clone one publisher-owned complete row into a deliberately scoped repository."""
    connection.execute(
        "INSERT INTO runs (repository_id, status, execution_route, portable_protocol_version, "
        "snapshot_manifest_id, snapshot_vector_json, extraction_receipt_id, publication_bundle_id, "
        "graph_candidate_id, resolver_identity, portable_canonicalizer_identity, "
        "semantic_contract_identity, quality_rule_identity, worker_capability_identity, "
        "portable_stage_id, portable_execution_mode, portable_singleton_fencing_epoch, "
        "portable_graph_lease_fencing_epoch, source_generation, config_generation, "
        "extractor_generation, canonicalizer_generation, publication_job_id, publication_attempt, "
        "family_receipts_json) "
        "SELECT %s, 'complete', execution_route, portable_protocol_version, snapshot_manifest_id, "
        "snapshot_vector_json, extraction_receipt_id, publication_bundle_id, graph_candidate_id, "
        "resolver_identity, portable_canonicalizer_identity, semantic_contract_identity, "
        "quality_rule_identity, worker_capability_identity, portable_stage_id || %s, "
        "'coordinator', portable_singleton_fencing_epoch, portable_graph_lease_fencing_epoch, "
        "source_generation, config_generation, extractor_generation, canonicalizer_generation, "
        "publication_job_id || %s, publication_attempt + %s, family_receipts_json "
        "FROM runs WHERE id = %s",
        (repository_id, suffix, suffix, attempt_delta, source_run_id),
    )


def _install_postgres_foreign_complete_run(
    postgres: Any,
    *,
    repository_identity: str,
    source_run_id: int,
) -> None:
    """Add only a newer foreign complete run; target authority remains current."""
    with psycopg.connect(
        host=postgres.host,
        port=postgres.port,
        dbname=postgres.database,
        user=postgres.user,
        password=postgres.password,
    ) as connection:
        target_repo = connection.execute(
            "SELECT id FROM repositories WHERE repository_identity = %s",
            (repository_identity,),
        ).fetchone()
        assert target_repo is not None
        authority_row = connection.execute(
            "SELECT last_run_id FROM graph_publication_authority WHERE repository_id = %s",
            (int(target_repo[0]),),
        ).fetchone()
        assert authority_row == (source_run_id,)
        foreign = connection.execute(
            "INSERT INTO repositories(name, root_path, repository_identity) "
            "VALUES ('foreign-readback', 'graph:foreign-readback', 'repo1:foreign-readback') "
            "RETURNING id"
        ).fetchone()
        assert foreign is not None
        _clone_postgres_complete_run(
            connection,
            source_run_id=source_run_id,
            repository_id=int(foreign[0]),
            suffix="-foreign",
            attempt_delta=2,
        )
        connection.commit()


def _install_postgres_unaccepted_target_run(
    postgres: Any,
    *,
    repository_identity: str,
    source_run_id: int,
) -> None:
    """Add a newer complete target row without advancing graph authority."""
    with psycopg.connect(
        host=postgres.host,
        port=postgres.port,
        dbname=postgres.database,
        user=postgres.user,
        password=postgres.password,
    ) as connection:
        target_repo = connection.execute(
            "SELECT id FROM repositories WHERE repository_identity = %s",
            (repository_identity,),
        ).fetchone()
        assert target_repo is not None
        _clone_postgres_complete_run(
            connection,
            source_run_id=source_run_id,
            repository_id=int(target_repo[0]),
            suffix="-late",
            attempt_delta=1,
        )
        connection.commit()


def test_sqlite_current_identity_follows_marker_past_newer_complete_run(tmp_path: Path) -> None:
    """SQLite's explicit accepted marker is not replaced by a later complete row."""
    working = materialize_mixed_v1_working_copy(tmp_path / "working")
    home = write_mixed_v1_sqlite_home(tmp_path / "sqlite-home", working)
    published = publish_and_load_sqlite_corpus(home)
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    graph = next(item for item in config.graphs if item.id == MIXED_V1_GRAPH_ID)
    db_path = sqlite_graph_database_path(config, graph)
    _clone_sqlite_complete_run(db_path, int(published.accepted_reference.run_id), 2)

    accepted, receipt = read_sqlite_accepted_publication(config)
    assert accepted.run_id == published.accepted_reference.run_id
    assert receipt == published.receipt
    binding = local_graph_binding(graph)
    with SqliteContextReadAdapter(
        graph_id=MIXED_V1_GRAPH_ID,
        db_path=db_path,
        binding=binding,
        configured_bindings={item.binding_id: {"revision": item.revision} for item in graph.source_bindings},
    ) as adapter:
        identity = adapter.read_initial_identity(WorkLedger(backend="sqlite"))
    assert identity["status"] == "ok"
    assert identity["accepted_publication"]["accepted_run_id"] == accepted.run_id


def test_postgres_foreign_isolated_and_unaccepted_target_is_absent() -> None:
    """Foreign latest stays isolated; an unaccepted target yields absence."""
    require_postgres_binaries()
    bundle = seven_family_bundle(
        job_id="job-readback-target",
        graph_id="matched-readback",
        repository_name="matched-readback",
    )
    owner = authority(bundle)
    portable = binding(bundle, owner)
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(), postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        published = run_staged_portable_refresh(
            postgres.psql_args,
            bundle,
            repository_name="matched-readback",
            root_path="graph:matched-readback",
            repository_identity="repo1:matched-readback",
            authority=owner,
            portable_binding=portable,
        )
        _install_postgres_foreign_complete_run(
            postgres,
            repository_identity="repo1:matched-readback",
            source_run_id=published.run_id,
        )
        identity = read_postgres_context_identity_with_executor(
            "repo1:matched-readback",
            executor=lambda sql: execute_json_readback(
                sql,
                psql_args=postgres.psql_args,
                psql_command=postgres.psql_command,
                label="proposal matched publication",
                expected_shape="object",
                password=postgres.password,
            ),
        )
        assert identity["status"] == "ok"
        assert identity["accepted_publication"]["run_id"] == published.run_id
        assert identity["accepted_publication"]["repository_id"] > 0

        _install_postgres_unaccepted_target_run(
            postgres,
            repository_identity="repo1:matched-readback",
            source_run_id=published.run_id,
        )
        absent = read_postgres_context_identity_with_executor(
            "repo1:matched-readback",
            executor=lambda sql: execute_json_readback(
                sql,
                psql_args=postgres.psql_args,
                psql_command=postgres.psql_command,
                label="proposal unaccepted target publication",
                expected_shape="object",
                password=postgres.password,
            ),
        )
        assert absent == {
            "status": "unavailable",
            "reason": "publication_absent",
            "accepted_publication": None,
        }


def _late_matching_rows(
    rows: list[tuple[int, Any]], core: str,
) -> tuple[list[tuple[int, Any]], tuple[int, Any]]:
    parsed = [
        (ordinal, json.loads(payload) if isinstance(payload, str) else payload)
        for ordinal, payload in rows
    ]
    early = [
        item for item in parsed
        if item[1]["metadata"]["binding_id"] == core
        and str(item[1]["metadata"]["source_relative_path"]).startswith("pkg/")
    ]
    assert len(early) >= 2
    late = next(item for item in reversed(parsed) if item[0] > early[1][0])
    return early[:2], late


def test_postgres_malformed_matching_metadata_cannot_hide_behind_scope_or_page(tmp_path: Path) -> None:
    with temporary_postgres() as postgres:
        working = materialize_mixed_v1_working_copy(tmp_path / "working")
        home = write_mixed_v1_postgres_home(
            tmp_path / "postgres-home", working, host=postgres.host,
            port=postgres.port, database=postgres.database,
            user=postgres.user, password=postgres.password,
        )
        published = publish_and_load_postgres_corpus(home, psql_command=postgres.psql_command)
        with psycopg.connect(
            host=postgres.host, port=postgres.port, dbname=postgres.database,
            user=postgres.user, password=postgres.password,
        ) as connection:
            rows = connection.execute(
                "SELECT ordinal, payload_json FROM public.raw_observations "
                "WHERE run_id = %s ORDER BY ordinal",
                (published.accepted_reference.run_id,),
            ).fetchall()
            core = binding_id_for_alias("core")
            early, late = _late_matching_rows(rows, core)
            run_id = published.accepted_reference.run_id
            token = "W5_MALFORMED_BOUNDARY_TOKEN"

            def update(ordinal: int, payload: dict[str, Any]) -> None:
                connection.execute(
                    "UPDATE public.raw_observations SET payload_json = %s::jsonb "
                    "WHERE run_id = %s AND ordinal = %s",
                    (json.dumps(payload), run_id, ordinal),
                )

            def read() -> FencedObservationResult:
                return query_fenced_current_observations(
                    home, graph_id=MIXED_V1_GRAPH_ID, query=token, limit=1,
                    selected_binding_ids=(core,), source_path_prefix="pkg",
                    psql_command=postgres.psql_command,
                )

            for ordinal, original in early:
                update(ordinal, {**original, "text": token})
            connection.commit()
            observed = read()
            assert len(observed.rows) == 1 and observed.has_more
            assert observed.rows[0]["metadata"]["binding_id"] == core
            metadata = {
                **early[0][1]["metadata"], "source_relative_path": "outside/answer.py",
            }
            mutations: tuple[tuple[dict[str, Any], str], ...] = (
                ({}, "malformed_observation_metadata"),
                ({**metadata, "binding_id": "foreign-binding"}, "unknown_observation_binding"),
                ({**metadata, "snapshot_id": "wrong-snapshot"}, "observation_snapshot_mismatch"),
                ({**metadata, "source_relative_path": "../answer.py"}, "malformed_observation_metadata"),
            )
            for malformed, code in mutations:
                update(late[0], {"text": token, "metadata": malformed})
                connection.commit()
                with pytest.raises(CurrentObservationReadError, match=code):
                    read()
                update(late[0], late[1])
                connection.commit()
            for ordinal, original in early:
                update(ordinal, original)
            connection.commit()


def test_sqlite_malformed_matching_metadata_cannot_hide_behind_scope_or_page(
    tmp_path: Path,
) -> None:
    working = materialize_mixed_v1_working_copy(tmp_path / "working")
    home = write_mixed_v1_sqlite_home(tmp_path / "sqlite-home", working)
    published = publish_and_load_sqlite_corpus(home)
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    graph = next(item for item in config.graphs if item.id == MIXED_V1_GRAPH_ID)
    db_path = sqlite_graph_database_path(config, graph)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT ordinal, payload_json FROM raw_observations "
            "WHERE run_id = ? ORDER BY ordinal",
            (published.accepted_reference.run_id,),
        ).fetchall()
        core = binding_id_for_alias("core")
        early, late = _late_matching_rows(rows, core)
        run_id = published.accepted_reference.run_id
        token = "W5_MALFORMED_BOUNDARY_TOKEN"

        def update(ordinal: int, payload: dict[str, Any]) -> None:
            connection.execute(
                "UPDATE raw_observations SET payload_json = ? "
                "WHERE run_id = ? AND ordinal = ?",
                (json.dumps(payload), run_id, ordinal),
            )

        for ordinal, original in early:
            update(ordinal, {**original, "text": token})
        connection.commit()
        def read() -> FencedObservationResult:
            return query_fenced_current_observations(
                home, graph_id=MIXED_V1_GRAPH_ID, query=token, limit=1,
                selected_binding_ids=(core,), source_path_prefix="pkg",
            )

        observed = read()
        assert len(observed.rows) == 1 and observed.has_more
        assert observed.rows[0]["metadata"]["binding_id"] == core
        metadata = {
            **early[0][1]["metadata"], "source_relative_path": "outside/answer.py",
        }
        mutations: tuple[tuple[dict[str, Any], str], ...] = (
            ({}, "malformed_observation_metadata"),
            ({**metadata, "binding_id": "foreign-binding"}, "unknown_observation_binding"),
        )
        for malformed, code in mutations:
            update(late[0], {"text": token, "metadata": malformed})
            connection.commit()
            with pytest.raises(CurrentObservationReadError, match=code):
                read()
            update(late[0], late[1])
            connection.commit()
        for ordinal, original in early:
            update(ordinal, original)
        connection.commit()
