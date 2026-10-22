"""Containerized D9-B reaping and process-creation quiescence proofs through the production bounded path.

Native: the existing core image with its postmaster as PID 1 and no init process; a real
invocation-owned shell leader, its real psql child and that child's real session; actual
``/proc`` PID, start time, PPid, state and signal disposition; an unrelated held session
holding an advisory lock; and the server log. Each is observed after settlement and before
any fixture cleanup.
Injected triggers only: the leader script. It traps CHLD, so the proof never relies on an
auto-reaping disposition, and stops itself with SIGSTOP once its child's session is visible.
Its child then either exits 3 natively (an ON_ERROR_STOP script error), staying an unreaped
zombie of the stopped leader, or keeps sleeping in a live session.
Operator steps, after every observation: a query cancel, SIGCONT of the injected stop (the
leader then reaps its child and exits) and removal of the exact retained control path.
The adopted-leader case injects a control record naming a real token-bearing ``sleep`` whose
real exec shell exited, so the PID 1 postmaster is its parent; the production settlement
script runs natively in the container against that record. The orphan exits naturally.
"""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import subprocess
import threading
import time
from typing import Any
import uuid

import pytest

from repomap_kg.runtime._extension_restore_exec import bound_exec_custody
from repomap_kg.runtime._extension_restore_exec_control import (
    EXEC_CONTROL_PREFIX, EXEC_INVOCATION_ENV, SETTLE_PROCESS_SH, parse_process_settlement,
)
from repomap_kg.runtime._extension_restore_native import run_bounded_ext_command
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import build_local_runtime_plan
from repomap_kg.runtime.release import PACKAGED_PSQL
from repomap_test_support.d9_extension_restore import engine_container_id, owned_d9_postgres_cluster, postmaster_crash_lines
from repomap_test_support.local_db_backup import connect_real_postgres as _connect
from repomap_test_support.postgres_harness import require_postgres_binaries
from repomap_test_support.test_scratch import short_test_directory

GRAPH = "d9b_reap_graph"
LOCK_KEY = 4_242_017
SIGCHLD_MASK = 1 << 16  # SIGCHLD is signal 17 on Linux
# One line per process: pid, state, PPid, start time and whether it carries any invocation token.
FAMILY_SH = (
    'for d in /proc/[0-9]*; do read -r s 2>/dev/null < "$d/stat" || continue; p="${d#/proc/}"; s="${s##*) }"; set -- $s; '
    't=-; tr "\\0" "\\n" < "$d/environ" 2>/dev/null | grep -q "^REPOMAP_EXT_INVOCATION=" && t=T; '
    'echo "$p $1 $2 ${20} $t"; done; true'
)
CHILD_SQL = {"exited": "SELECT pg_sleep(3);\nSELECT 1/0;", "sleeping": "SELECT pg_sleep(300);"}


@dataclass(frozen=True)
class _Proc:
    pid: str
    state: str
    ppid: str
    start: str
    token: bool


def _exec(container: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", "exec", "-u", "root", container, *args], capture_output=True, text=True, check=False)


def _family(container: str) -> dict[str, _Proc]:
    rows = (line.split() for line in _exec(container, "sh", "-c", FAMILY_SH).stdout.splitlines())
    return {r[0]: _Proc(r[0], r[1], r[2], r[3], r[4] == "T") for r in rows if len(r) == 5}


def _leader_script(user: str, database: str, child: str) -> str:
    """Injected trigger: start a real psql child, wait for its session, then stop the leader itself."""
    seen = "SELECT count(*) FROM pg_stat_activity WHERE application_name = '$PGAPPNAME' AND query LIKE 'SELECT pg_sleep%'"
    return (
        "trap : CHLD\n"
        f"{PACKAGED_PSQL} -X -q -v ON_ERROR_STOP=1 -U {user} -d {database} -f - >/dev/null 2>&1 <<'SQL' &\n{CHILD_SQL[child]}\nSQL\n"
        f'i=0; until [ "$({PACKAGED_PSQL} -X -tA -U {user} -d {database} -c "{seen}")" = 1 ]; do '
        'i=$((i + 1)); [ "$i" -lt 150 ] || exit 9; sleep 0.1; done\n'
        "kill -STOP $$\nuntil wait; do :; done\n"
    )


class _LeaderWatch(threading.Thread):
    """Records the stopped leader and its child natively, before the deadline triggers settlement."""

    def __init__(self, container: str, child_state: str) -> None:
        super().__init__(daemon=True)
        self.container, self.child_state = container, child_state
        self.leader: _Proc | None = None
        self.child: _Proc | None = None
        self.signals = ""

    def run(self) -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            family = _family(self.container)
            for leader in (p for p in family.values() if p.token and p.state == "T"):
                children = [p for p in family.values() if p.ppid == leader.pid]
                if len(children) == 1 and children[0].state == self.child_state:
                    self.leader, self.child = leader, children[0]
                    self.signals = _exec(self.container, "grep", "-E", "^Sig(Ign|Cgt)", f"/proc/{leader.pid}/status").stdout
                    return
            time.sleep(0.2)


def _mask(signals: str, name: str) -> int:
    return next(int(line.split()[1], 16) for line in signals.splitlines() if line.startswith(f"{name}:"))


def _bystander(postgres: Any, conn: Any, backend: int) -> tuple[bool, str]:
    """The unrelated session is alive with its own backend and still holds its advisory lock."""
    try:
        same = conn.execute("SELECT pg_backend_pid()").fetchone()[0] == backend
        with closing(_connect(postgres, autocommit=True)) as other:
            held = other.execute(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = %s AND pid = %s AND granted", (LOCK_KEY, backend)
            ).fetchone()[0]
        return same and held == 1, f"same_backend={same} lock_rows={held}"
    except Exception as error:  # a crash-restart ends the connection; report it as the observation
        return False, f"{type(error).__name__}: {error}"


def _sessions(postgres: Any, token: str) -> int:
    with closing(_connect(postgres, autocommit=True)) as conn:
        return int(conn.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name = %s", (f"repomap-ext-{token}",)).fetchone()[0])


def _operator_cleanup(postgres: Any, container: str, leader: _Proc, child: _Proc, token: str) -> None:
    """Operator intervention (test cleanup, outside the product path), after every observation."""
    with closing(_connect(postgres, autocommit=True)) as adm:  # a cancel lets a live psql child exit 1
        adm.execute("SELECT pg_cancel_backend(pid) FROM pg_stat_activity WHERE application_name = %s", (f"repomap-ext-{token}",))
    deadline = time.monotonic() + 30
    while (state := _family(container).get(child.pid)) is not None and state.state != "Z" and time.monotonic() < deadline:
        time.sleep(0.1)
    zombie = _family(container).get(child.pid)
    assert zombie is not None and (zombie.state, zombie.ppid) == ("Z", leader.pid), f"unreaped while the stopped leader cannot reap: {zombie}"
    assert _exec(container, "kill", "-CONT", leader.pid).returncode == 0  # resume the injected stop; the leader reaps and exits
    while {leader.pid, child.pid} & set(_family(container)) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not {leader.pid, child.pid} & set(_family(container)), "the resumed leader reaped its child and exited"


@pytest.mark.parametrize(("child", "child_state", "descendants"), [("exited", "Z", "unreaped"), ("sleeping", "S", "remaining")])
def test_d9b_child_of_a_stopped_leader_is_never_left_for_the_pid1_postmaster(
    monkeypatch: pytest.MonkeyPatch, child: str, child_state: str, descendants: str
) -> None:
    """Settlement never signals a leader whose child it cannot see reaped, nor a child its parent cannot reap."""
    require_postgres_binaries()
    with short_test_directory("d9b-rp-", "home/repomap.rpl.toml") as directory:
        home = Path(directory) / "home"
        with owned_d9_postgres_cluster(home, graph_db=GRAPH) as (identity, postgres, _runner):
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", str(postgres.password))
            monkeypatch.setenv("POSTGRES_PASSWORD", str(postgres.password))
            container, plan = identity.postgres_container, build_local_runtime_plan(home)
            assert _exec(container, "cat", "/proc/1/comm").stdout.strip() == "postgres", "the postmaster is PID 1; no init process"
            command = [plan.container_runtime, "exec", "-e", "PGPASSWORD", container, "sh", "-uc",
                       _leader_script(postgres.user, plan.maintenance_database, child)]
            with closing(_connect(postgres, autocommit=True)) as bystander:
                backend = bystander.execute("SELECT pg_backend_pid()").fetchone()[0]
                bystander.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
                watch = _LeaderWatch(container, child_state)
                watch.start()
                with bound_exec_custody(engine_container_id(container)) as custody, pytest.raises(LocalDbBackupError) as failure:
                    run_bounded_ext_command(plan, command, subprocess.run, field="paused leader", timeout_seconds=10.0)
                watch.join(timeout=30)
                [outcome] = custody.outcomes
                observed = (outcome.host, outcome.remote, outcome.descendants, outcome.sessions, outcome.control)
                after, crashed = _family(container), postmaster_crash_lines(container)
                alive, detail = _bystander(postgres, bystander, backend)
                leader, kid = watch.leader, watch.child
                assert leader is not None and kid is not None, f"setup: a stopped leader and its {child} child were observed natively"
                context = f"before: leader={leader} child={kid}; after: {after.get(leader.pid)} {after.get(kid.pid)}; outcome={observed}"
                assert alive and not crashed, f"bystander {detail}; crash lines {crashed}; {context}"
                assert not _mask(watch.signals, "SigIgn") & SIGCHLD_MASK and _mask(watch.signals, "SigCgt") & SIGCHLD_MASK, watch.signals

                codes = [d.code for d in failure.value.diagnostics]
                assert codes == ["local-db-command-failed", "restore-exec-outcome-unknown"], failure.value.diagnostics
                assert "timed out" in failure.value.diagnostics[0].message and outcome.control_path in failure.value.diagnostics[1].message
                assert observed == ("retired", "alive", descendants, "unknown", "retained"), context
                assert after.get(leader.pid) == leader, f"the stopped leader was neither signalled nor resumed: {context}"
                assert after.get(kid.pid) == kid, f"the child keeps its state under its own parent: {context}"
                assert _sessions(postgres, outcome.token) == (1 if child == "sleeping" else 0), "no correlated session was terminated"
                assert _exec(container, "find", "/tmp", "-maxdepth", "1", "-name", "repomap-ext-exec-*").stdout.split() == [outcome.control_path]
                assert _exec(container, "find", outcome.control_path, "-mindepth", "1").stdout.split() == [f"{outcome.control_path}/proc"]

                _operator_cleanup(postgres, container, leader, kid, outcome.token)
                assert _exec(container, "rm", "-r", outcome.control_path).returncode == 0
                assert _bystander(postgres, bystander, backend)[0] and not postmaster_crash_lines(container), "operator steps also kept the cluster"


ORPHAN_SECONDS = 12
ORPHAN_SH = 'sleep "$1" >/dev/null 2>&1 & echo "$!"'
RECORD_SH = 'mkdir -m 0700 "$1" && printf "%s %s %s\\n" "$2" "$3" "$4" > "$1/proc"'


def _adopted_orphan(container: str, token: str) -> _Proc:
    """Injected trigger: a real exec shell starts a token-bearing ``sleep`` and exits, so PID 1 adopts it."""
    started = subprocess.run(["docker", "exec", "-e", f"{EXEC_INVOCATION_ENV}={token}", container, "sh", "-c", ORPHAN_SH, "sh", str(ORPHAN_SECONDS)],
                             capture_output=True, text=True, check=True)
    pid, deadline = started.stdout.strip(), time.monotonic() + 10
    while (orphan := _family(container).get(pid)) is None or orphan.ppid != "1":
        assert time.monotonic() < deadline, f"setup: {pid} was adopted by PID 1: {orphan}"
        time.sleep(0.1)
    assert orphan.token, orphan
    return orphan


@pytest.mark.parametrize("externally_stopped", [False, True])
def test_d9b_recorded_leader_adopted_by_pid1_is_never_signalled(monkeypatch: pytest.MonkeyPatch, externally_stopped: bool) -> None:
    """A SIGKILLed or SIGSTOPped-then-killed PID 1 child would make the postmaster crash-restart every session."""
    require_postgres_binaries()
    with short_test_directory("d9b-ra-", "home/repomap.rpl.toml") as directory:
        with owned_d9_postgres_cluster(Path(directory) / "home", graph_db=GRAPH) as (identity, postgres, _runner):
            monkeypatch.setenv("REPOMAP_PG_PASSWORD", str(postgres.password))
            container, token = identity.postgres_container, uuid.uuid4().hex
            path = f"{EXEC_CONTROL_PREFIX}native-{token}"
            with closing(_connect(postgres, autocommit=True)) as bystander:
                backend = bystander.execute("SELECT pg_backend_pid()").fetchone()[0]
                bystander.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
                orphan = _adopted_orphan(container, token)
                if externally_stopped:  # injected stop that settlement did not introduce
                    assert _exec(container, "kill", "-STOP", orphan.pid).returncode == 0
                    while (orphan := _family(container)[orphan.pid]).state != "T":
                        time.sleep(0.05)
                record = subprocess.run(["docker", "exec", container, "sh", "-c", RECORD_SH, "sh", path, orphan.pid, orphan.start, token], check=False)
                assert record.returncode == 0, "setup: the injected control record names the adopted orphan"
                settled = subprocess.run(["docker", "exec", container, "sh", "-c", SETTLE_PROCESS_SH, "sh", path, token],
                                         capture_output=True, text=True, check=False)
                after, crashed = _family(container).get(orphan.pid), postmaster_crash_lines(container)
                alive, detail = _bystander(postgres, bystander, backend)
                report = parse_process_settlement(settled.stdout)
                assert alive and not crashed, f"bystander {detail}; crash lines {crashed}; {report}; before {orphan}; after {after}"
                assert report == ("alive", "retained", "remaining") and after == orphan, f"never stopped, resumed or killed: {report} {after}"
                assert _exec(container, "find", path, "-mindepth", "1").stdout.split() == [f"{path}/proc"], "no pause; the exact record is retained"

                if externally_stopped:  # operator steps: resume the injected stop, then let the orphan exit 0
                    assert _exec(container, "kill", "-CONT", orphan.pid).returncode == 0
                deadline = time.monotonic() + ORPHAN_SECONDS + 20
                while orphan.pid in _family(container) and time.monotonic() < deadline:
                    time.sleep(0.2)
                assert orphan.pid not in _family(container) and _exec(container, "rm", "-r", path).returncode == 0
                assert _bystander(postgres, bystander, backend)[0] and not postmaster_crash_lines(container), "operator steps also kept the cluster"
