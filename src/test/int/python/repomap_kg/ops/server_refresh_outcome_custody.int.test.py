"""Real PostgreSQL proof for post-publication portable custody."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo
import pytest

from common_lore_index.ops import portable_refresh
from common_lore_index.ops._server_retention_lock import RetentionLockError
from common_lore_index.ops.config_local import load_graph_registry_config_home
from common_lore_index.ops.config_records import OpsConfig
from common_lore_index.ops.portable_refresh import execute_portable_refresh
from common_lore_index.ops.refresh import query_graph_summary
from common_lore_index.storage import apply_migrations, default_rdbms_root
import common_lore_index.storage.staged_ingestion as staged_ingestion
from common_lore_index.storage.publication_phase_witness import (
    PublicationPhase, PublicationPhaseWitness,
)
from common_lore_index.storage.staged_rows import PreparedStageRows
from common_lore_index.storage.readback_driver import _psycopg_connection_params_from_psql_args
from repomap_test_support.postgres_harness import require_postgres_binaries, temporary_postgres
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_GRAPH_ID, materialize_mixed_v1_working_copy, write_mixed_v1_postgres_home,
)
from repomap_test_support.server_retained_recovery_fixture import direct_authority, prepare_retained_server


def test_real_failed_rollback_cannot_commit_final_transaction_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        fixture = prepare_retained_server(tmp_path, postgres)
        primary = KeyboardInterrupt("final publication interrupted")
        witness = PublicationPhaseWitness()
        failed = False
        commits_after_fault: list[int] = []
        publish = portable_refresh.run_staged_portable_refresh
        execute_final = staged_ingestion.execute_final_transaction

        class FaultingRollbackConnection:
            def __init__(self, inner):
                self.inner = inner

            def __getattr__(self, name):
                return getattr(self.inner, name)

            def rollback(self):
                if failed:
                    raise OSError("rollback transport failed")
                return self.inner.rollback()

            def commit(self):
                if failed:
                    commits_after_fault.append(1)
                return self.inner.commit()

        def connect(*args, **kwargs):
            return FaultingRollbackConnection(psycopg.connect(*args, **kwargs))

        def publish_with_owned_connection(*args, **kwargs):
            return publish(*args, connect=connect, **kwargs)

        def interrupt_final(*args, **kwargs):
            nonlocal failed
            execute_final(*args, **kwargs)
            failed = True
            raise primary

        monkeypatch.setattr(portable_refresh, "run_staged_portable_refresh", publish_with_owned_connection)
        monkeypatch.setattr(staged_ingestion, "execute_final_transaction", interrupt_final)
        with pytest.raises(KeyboardInterrupt) as caught:
            execute_portable_refresh(
                fixture.config, fixture.graph, postgres.database,
                authority=direct_authority(fixture, "retained-failed-rollback"), publication_witness=witness,
            )
        assert caught.value is primary
        assert commits_after_fault == []
        assert witness.phase is PublicationPhase.FINAL_TRANSACTION
        conninfo = make_conninfo(**_psycopg_connection_params_from_psql_args(postgres.psql_args))
        with psycopg.connect(conninfo) as connection:
            assert connection.execute("SELECT count(*) FROM public.canonical_nodes").fetchone() == (0,)
            assert connection.execute("SELECT count(*) FROM public.runs WHERE status = 'complete'").fetchone() == (0,)
        retained = tuple(portable_refresh.portable_attempts_parent(fixture.config).glob("*/portable-result.json"))
        assert len(retained) == 1
        assert json.loads(retained[0].read_bytes())["retention_class"] == "publication-reconciliation"


def test_real_before_publication_interrupt_proves_rollback_and_failed_retention(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        fixture = prepare_retained_server(tmp_path, postgres)
        primary = KeyboardInterrupt("before-publication interruption")
        witness = PublicationPhaseWitness()

        def stop_before_publication() -> None:
            raise primary

        authority = replace(
            direct_authority(fixture, "retained-before-publication"),
            before_publication=stop_before_publication,
        )
        with pytest.raises(KeyboardInterrupt) as caught:
            execute_portable_refresh(
                fixture.config, fixture.graph, postgres.database,
                authority=authority, publication_witness=witness,
            )
        assert caught.value is primary and witness.phase is PublicationPhase.ROLLED_BACK
        retained = tuple(portable_refresh.portable_attempts_parent(fixture.config).glob("*/portable-result.json"))
        assert len(retained) == 1
        assert json.loads(retained[0].read_bytes())["retention_class"] == "terminal-failed"
        conninfo = make_conninfo(**_psycopg_connection_params_from_psql_args(postgres.psql_args))
        with psycopg.connect(conninfo) as connection:
            assert connection.execute("SELECT status FROM public.runs").fetchall() == [("failed",)]
            assert connection.execute("SELECT state FROM public.ingestion_stages").fetchall() == [("failed",)]
            assert connection.execute("SELECT count(*) FROM public.canonical_nodes").fetchone() == (0,)


def test_first_server_refresh_under_group_writable_umask_creates_private_anchor(
    tmp_path: Path,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        fixture = prepare_retained_server(tmp_path, postgres)
        anchor = portable_refresh.portable_attempts_parent(fixture.config).parent
        assert not anchor.exists()
        previous = os.umask(0o002)
        try:
            outcome = execute_portable_refresh(
                fixture.config, fixture.graph, postgres.database, authority=None,
            )
        finally:
            os.umask(previous)
        assert outcome.summary.run_id > 0
        assert anchor.stat().st_mode & 0o777 == 0o700
        assert (anchor / "attempts").stat().st_mode & 0o777 == 0o700
        retained = tuple((anchor / "attempts").glob("*/portable-result.json"))
        assert len(retained) == 1
        assert json.loads(retained[0].read_bytes())["retention_class"] == "terminal-accepted"


@pytest.mark.parametrize("anchor_mode", [0o755, 0o775])
def test_existing_server_anchor_permission_policy_precedes_worker_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, anchor_mode: int,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        fixture = prepare_retained_server(tmp_path, postgres)
        anchor = portable_refresh.portable_attempts_parent(fixture.config).parent
        anchor.mkdir(parents=True, mode=anchor_mode)
        anchor.chmod(anchor_mode)
        launches: list[int] = []
        original = portable_refresh.run_portable_worker

        def record_worker(*args, **kwargs):
            launches.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(portable_refresh, "run_portable_worker", record_worker)
        if anchor_mode == 0o775:
            with pytest.raises(RetentionLockError):
                execute_portable_refresh(
                    fixture.config, fixture.graph, postgres.database, authority=None,
                )
            assert launches == []
            assert list((anchor / "attempts").glob("*/portable-result.json")) == []
            conninfo = make_conninfo(**_psycopg_connection_params_from_psql_args(postgres.psql_args))
            with psycopg.connect(conninfo) as connection:
                assert connection.execute("SELECT count(*) FROM public.canonical_nodes").fetchone() == (0,)
        else:
            outcome = execute_portable_refresh(
                fixture.config, fixture.graph, postgres.database, authority=None,
            )
            assert outcome.summary.run_id > 0 and launches == [1]
            retained = tuple((anchor / "attempts").glob("*/portable-result.json"))
            assert len(retained) == 1
            assert json.loads(retained[0].read_bytes())["retention_class"] == "terminal-accepted"
        assert anchor.stat().st_mode & 0o777 == anchor_mode


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_real_post_return_terminal_failure_preserves_publication_and_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
) -> None:
    require_postgres_binaries()
    working = materialize_mixed_v1_working_copy(tmp_path / "working")

    with temporary_postgres() as postgres:
        home = write_mixed_v1_postgres_home(
            tmp_path / "home",
            working,
            host=postgres.host,
            port=postgres.port,
            database=postgres.database,
            user=postgres.user,
            password=postgres.password,
        )
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        apply_migrations(
            default_rdbms_root(),
            config.postgres.psql_args_for_database(postgres.database),
            psql_command=postgres.psql_command,
        )
        graph = config.graphs[0]
        original_mark_terminal = portable_refresh.PortableCapture.mark_terminal
        terminal_calls: list[bool] = []
        primary = error_type("post-return terminal cleanup fault")

        def fail_after_accepted(
            capture: portable_refresh.PortableCapture,
            *,
            accepted: bool,
            sync_directory: bool = False,
        ) -> None:
            terminal_calls.append(accepted)
            original_mark_terminal(
                capture, accepted=accepted, sync_directory=sync_directory
            )
            if accepted:
                raise primary

        monkeypatch.setattr(
            portable_refresh.PortableCapture,
            "mark_terminal",
            fail_after_accepted,
        )
        with pytest.raises(error_type) as caught:
            execute_portable_refresh(
                config,
                graph,
                graph.database or config.postgres.database,
                authority=None,
            )

        assert caught.value is primary
        assert terminal_calls == [True]

        summary = query_graph_summary(
            config,
            MIXED_V1_GRAPH_ID,
            psql_command=postgres.psql_command,
        )
        assert summary.result == "success"
        assert summary.latest_run_status == "complete"
        retained = tuple(
            (
                portable_refresh.portable_attempts_parent(config)
            ).glob("*/portable-result.json")
        )
        assert len(retained) == 1
        retention = json.loads(retained[0].read_text(encoding="utf-8"))
        assert retention["retention_class"] == "terminal-accepted"


@pytest.mark.parametrize("provide_witness", [True, False])
def test_real_post_commit_cleanup_faults_preserve_publication_and_uncertainty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provide_witness: bool,
) -> None:
    require_postgres_binaries()
    working = materialize_mixed_v1_working_copy(tmp_path / "working")

    with temporary_postgres() as postgres:
        home = write_mixed_v1_postgres_home(
            tmp_path / "home",
            working,
            host=postgres.host,
            port=postgres.port,
            database=postgres.database,
            user=postgres.user,
            password=postgres.password,
        )
        config = load_graph_registry_config_home(home)
        assert isinstance(config, OpsConfig)
        apply_migrations(
            default_rdbms_root(),
            config.postgres.psql_args_for_database(postgres.database),
            psql_command=postgres.psql_command,
        )
        graph = config.graphs[0]
        prepared_fault = RuntimeError("prepared close failed after commit")
        connection_fault = RuntimeError("connection close failed after commit")
        prepared_calls: list[int] = []
        connection_calls: list[int] = []
        terminal_calls: list[bool] = []
        publication_witness = PublicationPhaseWitness()
        original_prepared_close = PreparedStageRows.close
        original_connection_close = staged_ingestion.close_owned_connection
        original_mark_terminal = portable_refresh.PortableCapture.mark_terminal

        def fail_prepared_close(prepared: PreparedStageRows) -> None:
            prepared_calls.append(1)
            try:
                original_prepared_close(prepared)
            finally:
                raise prepared_fault

        def fail_connection_close(connection: object) -> None:
            connection_calls.append(1)
            try:
                original_connection_close(connection)
            finally:
                raise connection_fault

        def record_terminal(
            capture: portable_refresh.PortableCapture,
            *,
            accepted: bool,
            sync_directory: bool = False,
        ) -> None:
            terminal_calls.append(accepted)
            original_mark_terminal(
                capture, accepted=accepted, sync_directory=sync_directory
            )

        monkeypatch.setattr(PreparedStageRows, "close", fail_prepared_close)
        monkeypatch.setattr(
            staged_ingestion, "close_owned_connection", fail_connection_close
        )
        monkeypatch.setattr(
            portable_refresh.PortableCapture, "mark_terminal", record_terminal
        )
        with pytest.raises(RuntimeError) as caught:
            execute_portable_refresh(
                config,
                graph,
                graph.database or config.postgres.database,
                authority=None,
                publication_witness=publication_witness if provide_witness else None,
            )

        assert caught.value is prepared_fault
        assert prepared_calls
        assert connection_calls == [1]
        assert terminal_calls == []
        if provide_witness:
            assert publication_witness.phase is PublicationPhase.COMMITTED
        assert any("connection close" in note for note in prepared_fault.__notes__)

        summary = query_graph_summary(
            config,
            MIXED_V1_GRAPH_ID,
            psql_command=postgres.psql_command,
        )
        assert summary.result == "success"
        assert summary.latest_run_status == "complete"
        retained = tuple(
            (
                portable_refresh.portable_attempts_parent(config)
            ).glob("*/portable-result.json")
        )
        assert len(retained) == 1
        retention = json.loads(retained[0].read_text(encoding="utf-8"))
        assert retention["retention_class"] == "publication-reconciliation"
