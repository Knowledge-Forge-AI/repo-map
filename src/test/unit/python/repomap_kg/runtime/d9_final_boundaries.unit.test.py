"""Final D9-A regressions for raw TOC names and bounded command custody."""

from __future__ import annotations

from pathlib import Path
import sys
import threading
from unittest.mock import MagicMock

import psutil
import psycopg
import pytest

from repomap_kg.runtime._backup_observation import _normalize_server_provenance
from repomap_kg.runtime._backup_provenance import parse_toc_entries, run_bounded_popen
from repomap_kg.runtime.backup_manifests import summarize_pg_restore_toc
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime import maintenance, release_cluster
from repomap_test_support.local_db_backup import default_baseline_server_provenance


@pytest.mark.parametrize(
    "name",
    [
        "plpgsql\u2028;hidden", "plpgsql\u0085;hidden", "plpgsql\v;hidden",
        "plpgsql\f;hidden", "plpgsql x", "plpgsql  x", 'plpgsql"x',
        " plpgsql", "plpgsql ",
    ],
)
def test_raw_extension_tag_cannot_turn_into_the_baseline(name: str) -> None:
    # PG16 emits the raw tag followed by the separator for an empty owner.
    text = f"1; 3079 16385 EXTENSION - {name} \n"
    observation = parse_toc_entries(text.encode("utf-8"), database="repomap")
    assert observation.extensions == (name,)
    summary = summarize_pg_restore_toc(text, dump_file="dump.pgcustom", dump_format="pgcustom")
    assert summary.extensions == (name,)


def test_stored_server_provenance_requires_explicit_client_observations() -> None:
    record = default_baseline_server_provenance()
    del record["client_identities"]
    with pytest.raises(LocalDbBackupError) as caught:
        _normalize_server_provenance(record, database="repomap")
    assert caught.value.diagnostics[0].code == "backup-observation-incomplete"


@pytest.mark.parametrize("schema", [" app", "app ", "\tapp"])
def test_core_schema_and_table_whitespace_is_preserved(schema: str) -> None:
    text = f"1; 2615 16385 SCHEMA - {schema} owner\n2; 0 16386 TABLE DATA {schema} notes  owner\n"
    observed = parse_toc_entries(text.encode(), database="repomap")
    assert observed.schemas == (schema,)
    assert observed.table_data == (f"{schema} notes ",)


def test_command_deadline_covers_descendant_output_and_retires_readers(tmp_path: Path) -> None:
    marker = tmp_path / "child-pid"
    program = (
        "import subprocess,sys; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)']); "
        "open(sys.argv[1],'w').write(str(child.pid))"
    )
    before = {thread.ident for thread in threading.enumerate()}
    with pytest.raises(LocalDbBackupError) as caught:
        run_bounded_popen(
            [sys.executable, "-c", program, str(marker)], max_output_bytes=1024,
            timeout_seconds=1.0, error_code="backup-toc-inconsistent", field="repomap",
        )
    assert caught.value.diagnostics[0].code == "backup-toc-inconsistent"
    assert marker.is_file(), "the command must have reached its inherited-pipe boundary"
    assert not ({thread.ident for thread in threading.enumerate()} - before)
    try:
        child = psutil.Process(int(marker.read_text()))
        assert not child.is_running() or child.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        pass


def test_exclusive_maintenance_sets_deadlines_before_waiting() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    with maintenance.maintenance_window(lambda: connection):
        statements = [call.args for call in cursor.execute.call_args_list]
        assert len(statements) == 2
        assert "set_config('lock_timeout'" in statements[0][0]
        assert "set_config('statement_timeout'" in statements[0][0]
        assert statements[0][1] == ("30s", "30s")
        assert statements[1] == ("SELECT pg_advisory_lock(%s)", (maintenance.MAINTENANCE_LOCK_KEY,))
    connection.close.assert_called_once()


def test_maintenance_acquisition_failure_is_bounded_and_releases_connection() -> None:
    connection = MagicMock()
    failure = psycopg.OperationalError("private acquisition detail")
    connection.cursor.return_value.__enter__.return_value.execute.side_effect = failure
    with pytest.raises(maintenance.MaintenanceUnavailableError) as caught:
        with maintenance.maintenance_window(lambda: connection):
            pytest.fail("failed acquisition entered maintenance")
    assert caught.value.__cause__ is failure
    assert "private" not in str(caught.value)
    connection.close.assert_called_once()


def test_maintenance_body_error_keeps_its_identity() -> None:
    connection = MagicMock()
    failure = psycopg.OperationalError("body failure")
    with pytest.raises(psycopg.OperationalError) as caught:
        with maintenance.maintenance_window(lambda: connection):
            raise failure
    assert caught.value is failure
    connection.close.assert_called_once()


def test_release_dump_and_connection_use_the_execution_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    operator = object.__new__(release_cluster.ReleaseGraphOperator)
    config = MagicMock()
    config.postgres.host, config.postgres.port, config.postgres.user = "configured", 5432, "owner"
    monkeypatch.setattr(operator, "config", config, raising=False)
    monkeypatch.setattr(operator, "password", "test-only", raising=False)
    endpoint = MagicMock(host="execution", port=55433)
    monkeypatch.setattr(release_cluster, "execution_postgres", lambda _config: endpoint)
    connect = MagicMock()
    monkeypatch.setattr(release_cluster.psycopg, "connect", connect)
    command = operator.pg_dump_command("graph")
    assert command[command.index("-h") + 1] == "execution"
    assert command[command.index("-p") + 1] == "55433"
    operator._connect("graph", autocommit=True)
    assert connect.call_args.kwargs["host"] == "execution"
    assert connect.call_args.kwargs["port"] == 55433
    assert connect.call_args.kwargs["user"] == "owner"


def test_unavailable_command_is_a_bounded_refusal(tmp_path: Path) -> None:
    with pytest.raises(LocalDbBackupError) as caught:
        run_bounded_popen(
            [str(tmp_path / "missing-command")], max_output_bytes=1024,
            timeout_seconds=2.0, error_code="backup-toc-inconsistent", field="repomap",
        )
    assert caught.value.diagnostics[0].code == "backup-toc-inconsistent"
    assert str(tmp_path) not in str(caught.value)
