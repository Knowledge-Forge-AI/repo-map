"""Containerized D9-B container command custody proofs through the production bounded path.

Native boundaries: a killed host ``docker exec`` client leaves its container process
running; a real CREATE DATABASE refusal; a real pg_restore replay deadline; a real
interruption during replay; settlement observed independently through ``/proc`` and
``pg_stat_activity``; and unproven control records that must not be acted on.
Injected triggers only, labelled per case: a held template1 connection, a slow CHECK
table fixture, an in-process SIGUSR1 handler that raises KeyboardInterrupt once the
replay COPY is observed, and a pg_restore wrapper that rewrites the control record to
name the postmaster or removes it. Every observation is native; none is simulated.
The descendant case runs a real shell leader whose real psql child holds a real
pg_sleep backend; settlement natively observes and retains that child and its session.
An unrelated held session and the server log natively show, before any cleanup, that no
settlement step made the PID 1 postmaster crash-restart the cluster; query cancels are operator steps.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time
from typing import Any
import uuid

import pytest

from repomap_kg.runtime._extension_restore_exec_control import (
    EXEC_CONTROL_PREFIX, EXEC_INVOCATION_ENV, SETTLE_PROCESS_SH, SUPERVISOR_SH, parse_process_settlement,
)
from repomap_kg.runtime._extension_restore_exec import bound_exec_custody
from repomap_kg.runtime._extension_restore_native import run_bounded_ext_command
from repomap_kg.runtime._extension_restore_policy import ExtensionReplayBounds
from repomap_kg.runtime.backup import dump_database, init_database_from_dump
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import build_local_runtime_plan
from repomap_kg.runtime.release import PACKAGED_PSQL
from repomap_test_support.d9_extension_policies import (
    installed_synthetic_extensions, probe_live_container_qualification, synthetic_multilevel_extension_policy,
)
from repomap_test_support.d9_extension_restore import (
    clean_template_reference, container_ppid, database_names, engine_container_id, owned_d9_postgres_cluster, postmaster_crash_lines,
    seed_synthetic_graph,
)
from repomap_test_support.local_db_backup import connect_real_postgres as _connect
from repomap_test_support.postgres_harness import require_postgres_binaries
from repomap_test_support.test_scratch import short_test_directory

GRAPH = "d9b_exec_graph"
SLOW_ROWS = 120  # 0.5 s per row: an uninterrupted replay needs about 60 s.
SLOW_SQL = (
    "CREATE FUNCTION app_ext.slow_ok(v int) RETURNS boolean LANGUAGE plpgsql AS $$ BEGIN "
    "IF current_setting('repomap_test.fast', true) IS DISTINCT FROM 'on' THEN PERFORM pg_sleep(0.5); END IF; "
    "RETURN v IS NOT NULL; END $$; SET repomap_test.fast = 'on'; "
    "CREATE TABLE app_ext.slow_rows (id int PRIMARY KEY CHECK (app_ext.slow_ok(id))); "
    f"INSERT INTO app_ext.slow_rows SELECT generate_series(1, {SLOW_ROWS});"
)
PROC_BY_COMM_SH = 'for p in /proc/[0-9]*; do read -r c 2>/dev/null < "$p/comm" || continue; [ "$c" = "$1" ] && echo "${p#/proc/}"; done; true'
# Injected control-record replacements, run by a pg_restore wrapper that then execs the real
# binary with the same PID: name the postmaster, or remove the record entirely.
RECORD_EDITS = {
    "postmaster": 'read -r s < /proc/1/stat; s="${s##*) }"; set -- $s; printf \'1 %s %s\\n\' "${20}" "$REPOMAP_EXT_INVOCATION" > "$d/proc"',
    "removed": 'rm -f "$d/proc"',
}


def _record_wrapper(edit: str) -> str:
    return (
        "mv /usr/bin/pg_restore /usr/bin/pg_restore.real && cat <<'EOF' > /usr/bin/pg_restore\n#!/bin/sh\n"
        'for a in "$@"; do case "$a" in --use-list=*) ( for d in /tmp/repomap-ext-exec-*-"$REPOMAP_EXT_INVOCATION"; do '
        f"{edit}; done ) ;; esac; done\n"
        'exec /usr/bin/pg_restore.real "$@"\nEOF\nchmod 0755 /usr/bin/pg_restore'
    )


def _exec(container: str, *args: str, root: bool = False) -> subprocess.CompletedProcess[str]:
    user = ["-u", "root"] if root else []
    return subprocess.run(["docker", "exec", *user, container, *args], capture_output=True, text=True, check=False)


def _pids(container: str, comm: str) -> list[str]:
    return _exec(container, "sh", "-c", PROC_BY_COMM_SH, "sh", comm).stdout.split()


def _tmp_dirs(container: str, prefix: str) -> list[str]:
    return sorted(_exec(container, "find", "/tmp", "-maxdepth", "1", "-name", f"{prefix}*").stdout.split())


def _owned_sessions(postgres: Any) -> int:
    with closing(_connect(postgres, autocommit=True)) as conn:
        row = conn.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name LIKE 'repomap-ext-%'").fetchone()
    return int(row[0])


def _ledgers(home: Path) -> list[dict[str, Any]]:
    return [entry for p in sorted((home / "runtime").glob(".restore-intents-*/intents.json")) for entry in json.loads(p.read_text(encoding="utf-8"))]


def _assert_settled_and_compensated(postgres: Any, container: str, home: Path, before: list[str]) -> None:
    assert _pids(container, "pg_restore") == [], "no owned pg_restore process survives settlement"
    assert _owned_sessions(postgres) == 0, "no correlated PostgreSQL session survives settlement"
    assert _tmp_dirs(container, "repomap-ext-exec-") == [] and _tmp_dirs(container, "repomap-ext-toc-") == []
    assert database_names(postgres) == before and not _ledgers(home), "the held target is compensated and the ledger removed"


class _ReplayWatch(threading.Thread):
    """Observes the replay's COPY backend and the container pg_restore process natively."""

    def __init__(self, postgres: Any, container: str, on_copy: Callable[[], None] | None = None) -> None:
        super().__init__(daemon=True)
        self.postgres, self.container, self.on_copy = postgres, container, on_copy
        self.seen: dict[str, Any] = {}
        self.done = threading.Event()

    def run(self) -> None:
        sql = ("SELECT pid, application_name FROM pg_stat_activity WHERE datname = %s "
               "AND application_name LIKE 'repomap-ext-%%' AND query ILIKE 'COPY %%'")
        with closing(_connect(self.postgres, autocommit=True)) as conn:
            deadline = time.monotonic() + 180
            while not self.done.is_set() and time.monotonic() < deadline:
                row = conn.execute(sql, (GRAPH,)).fetchone()
                if row is not None:
                    self.seen.update(at=time.monotonic(), backend=row, processes=_pids(self.container, "pg_restore"))
                    if self.on_copy is not None:
                        self.on_copy()
                    return
                time.sleep(0.05)


def _interrupt(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt("operator interrupt")


def _settle_script(container: str, path: str, token: str, *, restricted_path: bool = False) -> tuple[str, str, str]:
    env, shell = (["-e", "PATH=/nonexistent"], "/bin/sh") if restricted_path else ([], "sh")
    result = subprocess.run(
        ["docker", "exec", *env, container, shell, "-c", SETTLE_PROCESS_SH, "sh", path, token],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return parse_process_settlement(result.stdout)


def _assert_native_settlement_branches(container: str) -> None:
    """Run the real settlement script in the real container for branches the replay cases do not reach.

    Injected triggers: no supervisor ever starts, a record-less directory is pre-created, or
    PATH hides required utilities. Script execution and every filesystem observation are native.
    """
    fence_token, bare_token, hidden_token = (uuid.uuid4().hex for _ in range(3))
    fenced, bare, hidden = (f"{EXEC_CONTROL_PREFIX}native-{t}" for t in (fence_token, bare_token, hidden_token))
    assert _settle_script(container, fenced, fence_token) == ("not-started", "fence-retained", "none")
    assert _exec(container, "stat", "-c", "%a", fenced, f"{fenced}/proc").stdout.split() == ["700", "600"]
    assert _exec(container, "cat", f"{fenced}/proc").stdout == f"fence {fence_token}\n"
    marker = f"/tmp/repomap-native-late-{fence_token}"
    late = subprocess.run(
        ["docker", "exec", "-e", f"{EXEC_INVOCATION_ENV}={fence_token}", container, "sh", "-c", SUPERVISOR_SH, "sh", fenced,
         "sh", "-c", f": > {marker}"],
        capture_output=True, text=True, check=False,
    )
    assert late.returncode == 125 and _exec(container, "test", "-e", marker).returncode == 1, "a fenced late start never runs"
    assert _settle_script(container, fenced, fence_token) == ("not-started", "retained", "none")

    assert _exec(container, "mkdir", "-m", "0700", bare).returncode == 0
    assert _settle_script(container, bare, bare_token) == ("unknown", "retained", "unknown")
    assert _exec(container, "find", bare, "-mindepth", "1").stdout == "", "a record-less directory is never written into"

    assert _settle_script(container, hidden, hidden_token, restricted_path=True) == ("unavailable", "retained", "unknown")
    assert _exec(container, "test", "-e", hidden).returncode == 1, "an unavailable utility stops settlement before any write"
    for leftover in (fenced, bare):
        assert _exec(container, "rm", "-r", leftover, root=True).returncode == 0


def test_d9b_container_command_custody_settles_or_retains_native_outcomes(monkeypatch: pytest.MonkeyPatch) -> None:
    require_postgres_binaries()
    with short_test_directory("d9b-exc-", "home/repomap.rpl.toml") as directory:
        root = Path(directory)
        home = root / "home"
        reference = clean_template_reference(root)
        with owned_d9_postgres_cluster(home, graph_db=GRAPH) as (identity, postgres, runner):
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", str(postgres.password))
            monkeypatch.setenv("POSTGRES_PASSWORD", str(postgres.password))
            container = identity.postgres_container

            # Native premise: killing the host docker exec client does not end the container process.
            client = subprocess.Popen(["docker", "exec", container, "sleep", "37"], start_new_session=True)
            deadline = time.monotonic() + 30
            while not _pids(container, "sleep") and time.monotonic() < deadline:
                time.sleep(0.1)
            os.killpg(client.pid, signal.SIGKILL)
            client.wait(timeout=10)
            time.sleep(1.0)
            survivors = _pids(container, "sleep")
            assert survivors, "a killed host client is not proof that its container process ended"
            for pid in survivors:
                _exec(container, "kill", "-9", pid, root=True)

            with installed_synthetic_extensions("docker", container, runner=runner):
                qual = probe_live_container_qualification(container, user=postgres.user, template_baseline_sha256=reference)
                policy = synthetic_multilevel_extension_policy(owner=postgres.user, artifact_qualification=qual)
                seed_synthetic_graph(postgres, GRAPH)
                with closing(_connect(postgres, GRAPH, autocommit=True)) as g:
                    g.execute(SLOW_SQL)
                dump = dump_database(home, database=GRAPH, timestamp="20261021T060000Z", command_runner=runner, extension_restore_policy=policy)
                assert dump.restore_supported is True, f"blockers: {dump.restore_blockers}"
                with closing(_connect(postgres, autocommit=True)) as adm:
                    adm.execute(f'DROP DATABASE "{GRAPH}" WITH (FORCE)')
                before = database_names(postgres)
                bounded = replace(policy, replay_bounds=ExtensionReplayBounds(timeout_seconds=4.0, max_output_bytes=1024 * 1024))
                assert bounded.policy_binding_record() == policy.policy_binding_record(), "replay bounds stay outside the stable declaration"

                def restore() -> Any:
                    return init_database_from_dump(home, database=GRAPH, backup=dump.plan.backup_path, command_runner=runner, extension_restore_policy=bounded)

                # Native CREATE refusal (injected trigger: a held template1 session). The settled
                # outcome plus observed absence under the held lock clears the intent; no ledger remains.
                with closing(_connect(postgres, "template1", autocommit=True)):
                    with pytest.raises(LocalDbBackupError) as create_exc:
                        restore()
                assert [d.code for d in create_exc.value.diagnostics] == ["local-db-command-failed"], create_exc.value.diagnostics
                assert "accessed by other users" in create_exc.value.diagnostics[0].message
                _assert_settled_and_compensated(postgres, container, home, before)

                # Native replay deadline: the exact pg_restore process and its COPY backend are settled.
                watch = _ReplayWatch(postgres, container)
                watch.start()
                try:
                    with pytest.raises(LocalDbBackupError) as timeout_exc:
                        restore()
                finally:
                    watch.done.set()
                    watch.join(timeout=10)
                settled_at = time.monotonic()
                assert [d.code for d in timeout_exc.value.diagnostics] == ["local-db-command-failed"], timeout_exc.value.diagnostics
                assert "timed out" in timeout_exc.value.diagnostics[0].message
                assert watch.seen.get("processes") and watch.seen.get("backend"), f"replay was observed running natively: {watch.seen}"
                assert settled_at - watch.seen["at"] < SLOW_ROWS * 0.5 / 3, "the replay was ended by its deadline, not by completion"
                _assert_settled_and_compensated(postgres, container, home, before)

                # Native interruption during the observed replay COPY; the original interrupt survives.
                previous = signal.signal(signal.SIGUSR1, _interrupt)
                watch = _ReplayWatch(postgres, container, on_copy=lambda: os.kill(os.getpid(), signal.SIGUSR1))
                watch.start()
                try:
                    with pytest.raises(KeyboardInterrupt) as kb_exc:
                        restore()
                finally:
                    signal.signal(signal.SIGUSR1, previous)
                    watch.done.set()
                    watch.join(timeout=10)
                assert kb_exc.value.args == ("operator interrupt",) and not getattr(kb_exc.value, "__notes__", ())
                assert watch.seen.get("processes") and watch.seen.get("backend")
                _assert_settled_and_compensated(postgres, container, home, before)

                # Native refusal to act on an unproven control record (injected triggers: the record
                # names the postmaster, or is removed). Each unknown outcome is retained.
                for edit, remote in (("postmaster", "mismatch"), ("removed", "unknown")):
                    pid1_before = _exec(container, "cat", "/proc/1/stat").stdout.split(") ", 1)[1].split()[19]
                    assert _exec(container, "sh", "-c", _record_wrapper(RECORD_EDITS[edit]), root=True).returncode == 0
                    try:
                        with pytest.raises(LocalDbBackupError) as unknown_exc:
                            restore()
                    finally:
                        assert _exec(container, "mv", "-f", "/usr/bin/pg_restore.real", "/usr/bin/pg_restore", root=True).returncode == 0
                    codes = [d.code for d in unknown_exc.value.diagnostics]
                    assert codes == [
                        "local-db-command-failed", "restore-exec-outcome-unknown", "restore-toc-cleanup-failed",
                        "restore-exec-outcome-unknown", "failed-target-cleanup-failed",
                    ], (edit, codes)
                    assert "timed out" in unknown_exc.value.diagnostics[0].message, "the initiating deadline stays first"
                    assert _exec(container, "cat", "/proc/1/stat").stdout.split(") ", 1)[1].split()[19] == pid1_before, "the postmaster was not signalled"
                    assert _owned_sessions(postgres) == 1, "an unknown outcome leaves its correlated replay session unterminated"
                    ledger = _ledgers(home)
                    assert [e["state"] for e in ledger] == ["created"] and GRAPH in database_names(postgres), "target and ledger are retained"
                    assert [(r["label"], r["remote"], r["control"]) for r in ledger[0]["exec_unknown"]] == [("pg_restore", remote, "retained")], edit
                    exec_dirs = _tmp_dirs(container, "repomap-ext-exec-")
                    assert len(exec_dirs) == 1 and len(_tmp_dirs(container, "repomap-ext-toc-")) == 1, "unknown resources are retained"
                    assert _exec(container, "test", "-d", exec_dirs[0], root=True).returncode == 0, "an unproven control path is never removed"

                    # Operator intervention for the retained state (test cleanup, outside the product path).
                    for pid in (*_pids(container, "pg_restore"), *_pids(container, "pg_restore.real")):
                        _exec(container, "kill", "-9", pid, root=True)
                    with closing(_connect(postgres, autocommit=True)) as adm:
                        adm.execute(f'DROP DATABASE "{GRAPH}" WITH (FORCE)')
                    for leftover in (*exec_dirs, *_tmp_dirs(container, "repomap-ext-toc-")):
                        _exec(container, "rm", "-r", leftover, root=True)
                    for path in (home / "runtime").glob(".restore-intents-*"):
                        shutil.rmtree(path)
                assert database_names(postgres) == before
                _assert_native_settlement_branches(container)
                assert _tmp_dirs(container, "repomap-ext-exec-") == []
                assert not (crashed := postmaster_crash_lines(container)), f"no settlement made the postmaster reap a crashed child: {crashed}"


CHILD_SQL = "SELECT pg_sleep(300)"


def _child_script(user: str, database: str, *, leader_waits: bool) -> str:
    """The leader starts a slow psql child and returns only once that child's session is visible."""
    seen = f"SELECT count(*) FROM pg_stat_activity WHERE application_name = '$PGAPPNAME' AND query = '{CHILD_SQL}'"
    return (
        f'{PACKAGED_PSQL} -X -q -U {user} -d {database} -c "{CHILD_SQL}" >/dev/null 2>&1 & i=0; '
        f'until [ "$({PACKAGED_PSQL} -X -tA -U {user} -d {database} -c "{seen}")" = 1 ]; do '
        'i=$((i + 1)); [ "$i" -lt 150 ] || exit 9; sleep 0.1; done; echo started; ' + ("wait" if leader_waits else "exit 0")
    )


def _token_processes(container: str, token: str) -> list[str]:
    scan = 'for e in /proc/[0-9]*/environ; do tr "\\0" "\\n" < "$e" 2>/dev/null | grep -Fqx "$1" && echo "${e%/environ}"; done; true'
    return _exec(container, "sh", "-c", scan, "sh", f"{EXEC_INVOCATION_ENV}={token}", root=True).stdout.split()


def _token_sessions(postgres: Any, token: str) -> int:
    with closing(_connect(postgres, autocommit=True)) as conn:
        return int(conn.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name = %s", (f"repomap-ext-{token}",)).fetchone()[0])


def _operator_end(container: str, outcome: Any, postgres: Any = None) -> None:
    """Operator intervention (test cleanup, outside the product path); a query cancel lets a psql child exit 1."""
    if postgres is not None:
        with closing(_connect(postgres, autocommit=True)) as adm:
            adm.execute("SELECT pg_cancel_backend(pid) FROM pg_stat_activity WHERE application_name = %s", (f"repomap-ext-{outcome.token}",))
    deadline = time.monotonic() + 30
    while _token_processes(container, outcome.token) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert _token_processes(container, outcome.token) == [] and (postgres is None or _token_sessions(postgres, outcome.token) == 0)
    assert _exec(container, "rm", "-r", outcome.control_path, root=True).returncode == 0


def _assert_child_retained(postgres: Any, container: str, outcome: Any, *, leader_waits: bool) -> None:
    """Native: the live psql child, its session and the exact control path are retained, never signalled."""
    leader = _exec(container, "cat", f"{outcome.control_path}/proc", root=True).stdout.split()[0]
    family = {p.removeprefix("/proc/") for p in _token_processes(container, outcome.token)}
    if leader_waits:
        [child] = family - {leader}
        assert leader in family and container_ppid(container, child) == leader, family
        assert container_ppid(container, leader) == "0", "the live leader stays under its exec shim"
    else:
        assert family and {container_ppid(container, p) for p in family} == {"1"}, "the orphan is not signalled"
    assert _token_sessions(postgres, outcome.token) == 1, "the child's session is not terminated"
    assert _tmp_dirs(container, "repomap-ext-exec-") == [outcome.control_path], "its exact control path is retained"
    assert _exec(container, "find", outcome.control_path, "-mindepth", "1", root=True).stdout.split() == [f"{outcome.control_path}/proc"]


def _assert_untokened_child_retained(plan: Any, container: str) -> None:
    """Injected trigger: the leader starts a child without the token. Settlement signals neither."""
    command = [plan.container_runtime, "exec", container, "sh", "-uc", f"env -u {EXEC_INVOCATION_ENV} sleep 120 & echo started; wait"]
    with bound_exec_custody(engine_container_id(container)) as custody, pytest.raises(LocalDbBackupError) as failure:
        run_bounded_ext_command(plan, command, subprocess.run, field="untokened child", timeout_seconds=3.0)
    [outcome] = custody.outcomes
    assert [d.code for d in failure.value.diagnostics] == ["local-db-command-failed", "restore-exec-outcome-unknown"]
    assert (outcome.remote, outcome.descendants, outcome.sessions, outcome.control) == ("alive", "unknown", "unknown", "retained"), outcome
    [leader], [child] = _token_processes(container, outcome.token), _pids(container, "sleep")
    assert container_ppid(container, child) == leader.removeprefix("/proc/"), "the live leader and its child were not signalled"
    assert _exec(container, "kill", "-9", child, root=True).returncode == 0  # operator step: the waiting leader reaps it
    _operator_end(container, outcome)


def test_d9b_shell_descendants_and_inherited_sessions_are_settled_natively(monkeypatch: pytest.MonkeyPatch) -> None:
    """Native: a real shell leader, its real psql child and that child's real pg_sleep backend.

    Injected trigger only: the leader script. Past its deadline a waiting leader still has its live
    child; an early-exit leader orphans it to PID 1. Either way settlement only observes and retains
    the child and its session. Observed in the running container before cleanup, with no crash-restart.
    """
    require_postgres_binaries()
    with short_test_directory("d9b-dsc-", "home/repomap.rpl.toml") as directory:
        home = Path(directory) / "home"
        with owned_d9_postgres_cluster(home, graph_db=GRAPH) as (identity, postgres, _runner):
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", str(postgres.password))
            monkeypatch.setenv("POSTGRES_PASSWORD", str(postgres.password))
            container, plan = identity.postgres_container, build_local_runtime_plan(home)
            for leader_waits in (False, True):
                command = [plan.container_runtime, "exec", "-e", "PGPASSWORD", container, "sh", "-uc",
                           _child_script(postgres.user, plan.maintenance_database, leader_waits=leader_waits)]
                with closing(_connect(postgres, autocommit=True)) as bystander:
                    bystander_pid = bystander.execute("SELECT pg_backend_pid()").fetchone()[0]
                    with bound_exec_custody(engine_container_id(container)) as custody, pytest.raises(LocalDbBackupError) as failure:
                        run_bounded_ext_command(plan, command, subprocess.run, field="slow child", timeout_seconds=8.0 if leader_waits else 30.0)
                    [outcome] = custody.outcomes
                    observed = (outcome.host, outcome.remote, outcome.descendants, outcome.sessions, outcome.control)
                    diagnostics = failure.value.diagnostics
                    codes, remote = (["local-db-command-failed", "restore-exec-outcome-unknown"], "alive") if leader_waits else (["restore-exec-outcome-unknown"], "exited")
                    assert [d.code for d in diagnostics] == codes and outcome.control_path in diagnostics[-1].message, diagnostics
                    assert observed == ("retired", remote, "remaining", "unknown", "retained") and ("timed out" in diagnostics[0].message) == leader_waits, outcome
                    _assert_child_retained(postgres, container, outcome, leader_waits=leader_waits)
                    assert bystander.execute("SELECT pg_backend_pid()").fetchone()[0] == bystander_pid, "an unrelated session survives, before any cleanup"
                    assert not (crashed := postmaster_crash_lines(container)), f"no postmaster crash-restart before cleanup: {crashed}"
                    _operator_end(container, outcome, postgres)
                assert not (crashed := postmaster_crash_lines(container)), f"no postmaster crash-restart: {crashed}"
            _assert_untokened_child_retained(plan, container)
            assert _tmp_dirs(container, "repomap-ext-exec-") == [] and not postmaster_crash_lines(container)
