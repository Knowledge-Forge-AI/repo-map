"""Final D9-A regressions for raw TOC names and bounded command custody."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import psutil
import psycopg
import pytest

from common_lore_index.cli import main
from common_lore_index.runtime._backup_observation import _normalize_server_provenance
from common_lore_index.runtime._backup_process import BoundedProcessError, ProcessRetirement, run_bounded_process
from common_lore_index.runtime import _extension_restore_exec as exec_mod
from common_lore_index.runtime import _extension_restore_native as native_mod
from common_lore_index.runtime._backup_provenance import parse_toc_entries, provenance_error, run_bounded_popen
from common_lore_index.runtime._extension_restore_exec import bound_exec_custody
from common_lore_index.runtime._extension_restore_exec_control import SETTLE_PROCESS_SH
from common_lore_index.runtime._extension_restore_lifecycle import reconcile_restored_roles
from common_lore_index.runtime._extension_restore_native import observe_custodied_client_identities
from common_lore_index.runtime.backup_commands import planned_psql_stdin_command
from common_lore_index.runtime.backup_manifests import summarize_pg_restore_toc
from common_lore_index.runtime.backup_records import LocalDbBackupError
from common_lore_index.runtime.database_role_contract import read_role_secrets
from common_lore_index.runtime.database_roles import render_database_role_sql
from common_lore_index.runtime.local import build_local_runtime_plan, setup_local_runtime
from common_lore_index.runtime.release import PACKAGED_PG_DUMP, PACKAGED_PG_RESTORE, PACKAGED_PSQL
from common_lore_index.runtime import maintenance, release_cluster
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
    sh_cmd = shutil.which("sh") or "/bin/sh"
    sleep_cmd = shutil.which("sleep")
    assert Path(sh_cmd).is_file() and sleep_cmd is not None
    marker = tmp_path / "child-pid"
    program = '"$1" 2 & printf "%s" "$!" > "$2"'
    before = {thread.ident for thread in threading.enumerate()}
    with pytest.raises(LocalDbBackupError) as caught:
        run_bounded_popen(
            [sh_cmd, "-c", program, "sh", sleep_cmd, str(marker)], max_output_bytes=1024,
            timeout_seconds=1.0, error_code="backup-toc-inconsistent", field="repomap",
        )
    assert caught.value.diagnostics[0].code == "backup-toc-inconsistent"
    assert marker.is_file(), "the command must have reached its inherited-pipe boundary"
    assert not ({thread.ident for thread in threading.enumerate()} - before)
    child_pid = int(marker.read_text())
    deadline = time.monotonic() + 0.5
    while True:
        try:
            child = psutil.Process(child_pid)
            if not child.is_running() or child.status() == psutil.STATUS_ZOMBIE:
                break
        except psutil.NoSuchProcess:
            break
        assert time.monotonic() < deadline, "timed-out descendant remained active after process-group kill"
        time.sleep(0.01)


def test_cli_dump_validates_target_before_outer_maintenance_window(tmp_path: Path) -> None:
    home = tmp_path / "repo-map-home"
    setup_local_runtime(home)
    for bad_db, expected_msg in (
        ("../repomap", "database name must be a safe PostgreSQL identifier"),
        ("postgres", "database is not an authorized RepoMap lifecycle target"),
        ("unowned_db", "database is not an authorized RepoMap lifecycle target"),
    ):
        stderr = io.StringIO()
        with (
            patch(
                "common_lore_index.cli.maintenance_window_for_database_drop",
                side_effect=AssertionError("outer maintenance window entered before target validation"),
            ),
            redirect_stdout(io.StringIO()),
            redirect_stderr(stderr),
        ):
            code = main(["local", "db", "dump", "--repo-map-home", str(home), "--database", bad_db])
        assert code == 1
        assert expected_msg in stderr.getvalue()


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


def test_typed_retirement_is_positive_only_after_the_owned_group_is_reaped(monkeypatch: pytest.MonkeyPatch) -> None:
    sh_cmd = shutil.which("sh") or "/bin/sh"
    retired = ProcessRetirement()
    assert run_bounded_process([sh_cmd, "-c", "printf ok"], max_output_bytes=64, timeout_seconds=10.0, retirement=retired) == b"ok"
    assert retired.state == "retired"
    assert run_bounded_process([sh_cmd, "-c", "printf ok"], max_output_bytes=64, timeout_seconds=10.0) == b"ok", "callers without an observation are unchanged"
    real_killpg = os.killpg

    def interrupted_killpg(pid: int, sig: int) -> None:
        real_killpg(pid, sig)
        raise KeyboardInterrupt("retirement interrupted")

    interrupted = ProcessRetirement()
    monkeypatch.setattr(os, "killpg", interrupted_killpg)
    with pytest.raises(KeyboardInterrupt):
        run_bounded_process([sh_cmd, "-c", "printf ok"], max_output_bytes=64, timeout_seconds=10.0, retirement=interrupted)
    assert interrupted.state == "started", "client success plus an interrupted retirement is not a retirement observation"


def test_piped_stdin_bytes_stay_off_disk_and_are_bounded_by_the_command(tmp_path: Path) -> None:
    sh_cmd = shutil.which("sh") or "/bin/sh"
    payload = b"x" * 200_000  # larger than any default pipe buffer
    retired = ProcessRetirement()
    out = run_bounded_process([sh_cmd, "-c", "wc -c"], max_output_bytes=64, timeout_seconds=10.0, stdin_bytes=payload, retirement=retired)
    assert out.strip() == b"200000" and retired.state == "retired"
    assert run_bounded_process([sh_cmd, "-c", "exit 0"], max_output_bytes=64, timeout_seconds=10.0, stdin_bytes=payload) == b"", "an early reader exit is decided by its status"
    with pytest.raises(BoundedProcessError):
        run_bounded_process([sh_cmd, "-c", "cat >/dev/null; exit 3"], max_output_bytes=64, timeout_seconds=10.0, stdin_bytes=payload)
    stdin_file = tmp_path / "in"
    stdin_file.write_bytes(b"a")
    with pytest.raises(ValueError):
        run_bounded_process([sh_cmd, "-c", "cat"], max_output_bytes=64, timeout_seconds=10.0, stdin_path=stdin_file, stdin_bytes=b"b")


def test_unavailable_command_is_a_bounded_refusal(tmp_path: Path) -> None:
    with pytest.raises(LocalDbBackupError) as caught:
        run_bounded_popen(
            [str(tmp_path / "missing-command")], max_output_bytes=1024,
            timeout_seconds=2.0, error_code="backup-toc-inconsistent", field="repomap",
        )
    assert caught.value.diagnostics[0].code == "backup-toc-inconsistent"
    assert str(tmp_path) not in str(caught.value)


def _custody_plan(tmp_path: Path) -> Any:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    setup_local_runtime(home)
    (home / "runtime").chmod(0o700)
    plan = build_local_runtime_plan(home)
    plan.env_file.chmod(0o600)
    return plan


class _ScriptedBounded:
    """Scripted bounded runner (parser/orchestration only): typed retirement plus settlement reports."""

    def __init__(self, respond: Any, settlement: bytes = b"REMOTE exited\nCONTROL removed\nDESCENDANTS none\n") -> None:
        self.respond, self.settlement = respond, settlement
        self.commands: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> bytes:
        if SETTLE_PROCESS_SH in command:
            return self.settlement
        if "pg_terminate_backend" in " ".join(command):
            return b"0\n0\n"
        self.commands.append((command, kwargs))
        kwargs["retirement"].state = "retired"
        return self.respond(command)


def test_client_version_probes_run_under_container_custody_with_existing_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _custody_plan(tmp_path)

    def respond(command: list[str]) -> bytes:
        if command[-2] == PACKAGED_PSQL:
            raise provenance_error("backup-observation-incomplete", "psql", "provenance command exited with non-zero status")
        return f"{Path(command[-2]).name} (PostgreSQL) 16.15\n".encode()

    bounded = _ScriptedBounded(respond)
    monkeypatch.setattr(exec_mod, "run_bounded_popen", bounded)
    with bound_exec_custody("c" * 64) as custody:
        assert observe_custodied_client_identities(plan, subprocess.run) == {
            "pg_dump_version": "pg_dump (PostgreSQL) 16.15",
            "pg_restore_version": "pg_restore (PostgreSQL) 16.15",
            "psql_version": "unavailable",
        }, "a settled probe failure keeps the existing unavailable observation"
    expected_cmds = [[b, "--version"] for b in (PACKAGED_PG_DUMP, PACKAGED_PG_RESTORE, PACKAGED_PSQL)]
    assert [command[-2:] for command, _ in bounded.commands] == expected_cmds
    assert all("c" * 64 in command and plan.identity.postgres_container not in command for command, _ in bounded.commands)
    assert all((kw["max_output_bytes"], kw["timeout_seconds"], kw["error_code"]) == (4096, 5.0, "backup-observation-incomplete") for _, kw in bounded.commands)
    assert len(custody.outcomes) == 3 and custody.unknown == []
    bounded.settlement = b"REMOTE mismatch\nCONTROL retained\nDESCENDANTS unknown\n"
    with bound_exec_custody("c" * 64), pytest.raises(LocalDbBackupError) as unsettled:
        observe_custodied_client_identities(plan, subprocess.run)
    assert "restore-exec-outcome-unknown" in [d.code for d in unsettled.value.diagnostics], "an unsettled probe is never reported as unavailable"
    legacy: list[Any] = []

    def shared_observation(**kw: Any) -> dict[str, str]:
        legacy.append(kw)
        return {"psql_version": "shared"}

    monkeypatch.setattr(native_mod, "observe_client_identities", shared_observation)
    runner = MagicMock()
    assert observe_custodied_client_identities(plan, runner) == {"psql_version": "shared"} and legacy == [{"plan": plan, "command_runner": runner}]


def test_role_reconciliation_reuses_core_sql_under_custody_with_piped_input(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = _custody_plan(tmp_path)
    database = plan.graph_databases[0]
    expected_sql = render_database_role_sql(
        database=database, owner_role=plan.user, database_kind="graph", secrets=read_role_secrets(plan.env_file),
    ).encode("utf-8")
    bounded = _ScriptedBounded(lambda command: b"BEGIN\nCOMMIT\n")
    monkeypatch.setattr(exec_mod, "run_bounded_popen", bounded)
    with bound_exec_custody("c" * 64) as custody:
        reconcile_restored_roles(plan, database, "graph", subprocess.run)
    [(command, kwargs)] = bounded.commands
    assert "c" * 64 in command and plan.identity.postgres_container not in command
    inner = list(planned_psql_stdin_command(plan, database)[6:])
    assert inner[0] == PACKAGED_PSQL and command[-len(inner):] == inner, "the unchanged core psql stdin form"
    assert kwargs["stdin_bytes"] == expected_sql and kwargs.get("stdin_path") is None, "secret-bearing SQL is piped, not written to disk"
    assert (kwargs["field"], kwargs["error_code"]) == ("database role reconciliation", "local-db-command-failed")
    assert [o.label for o in custody.outcomes] == ["database role reconciliation"] and custody.unknown == []
    assert not [p.name for p in plan.runtime_dir.iterdir() if p.name.startswith(".ext-stdin-")]
    shared = MagicMock(return_value=subprocess.CompletedProcess([], 0, b"", b""))
    reconcile_restored_roles(plan, database, "graph", shared)
    assert shared.call_args.kwargs["input"] == expected_sql, "a caller-supplied runner keeps the shared core path"
