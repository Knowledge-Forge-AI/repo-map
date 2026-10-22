"""Unit proofs for D9-B conservative descendant retention and exact leader retirement.

The production settlement script runs under the host ``sh`` against a synthetic ``/proc``
projection whose every PID is an exact owned host ``sleep`` process. Any signal the script
sends reaches only those processes. Stops and kills are observed through native
``waitpid``; successful real CONT commands are traced by the host shell. Process-table
polling updates the projection but cannot distinguish resumption from death. Scripted: the projected PPid relations
(including adoption by PID 1), tokens, start times and fixed zombie states, plus changes the
projection publishes when the leader stops. Real zombies, the container, its PID 1 postmaster
and the bystander session belong to the int owners. Fixture signals go only through the
original ``psutil`` handles, which refuse a PID that was reaped and reused.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import threading
import time
from typing import Any

import psutil
import pytest

from repomap_kg.runtime import _extension_restore_exec as exec_mod
from repomap_kg.runtime._backup_provenance import provenance_error
from repomap_kg.runtime._extension_restore_exec import bound_exec_custody
from repomap_kg.runtime._extension_restore_exec_control import SETTLE_PROCESS_SH, parse_process_settlement
from repomap_kg.runtime._extension_restore_native import run_bounded_ext_command
from repomap_kg.runtime.backup_records import LocalDbBackupError
from repomap_kg.runtime.local import build_local_runtime_plan, setup_local_runtime

TOKEN = "e" * 32
CONTAINER_ID = "c" * 64


class _Projection:
    """A synthetic ``/proc`` of exact owned processes, kept current from their native wait statuses."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.events: list[tuple[int, str]] = []
        self.meta: dict[int, tuple[int, str, bool]] = {}
        self.handles: dict[int, psutil.Process] = {}
        self.frozen: set[int] = set()  # resumed natively, but still published as stopped
        self.on_stop: dict[int, Callable[[], None]] = {}
        self.threads: list[threading.Thread] = []

    def spawn(self, *, ppid: int, token: bool = True, state: str = "S") -> int:
        """Start one owned process; a fixed state (``Z``) is never updated from its wait status."""
        pid = os.posix_spawnp("sleep", ["sleep", "60"], dict(os.environ))
        self.handles[pid] = psutil.Process(pid)  # taken before the mirror thread can reap and free the PID
        self.meta[pid] = (ppid, str(1000 + len(self.meta)), token)
        (self.root / str(pid)).mkdir()
        environ = f"REPOMAP_EXT_INVOCATION={TOKEN}\0" if token and state != "Z" else ""
        (self.root / str(pid) / "environ").write_bytes(f"{environ}LANG=C\0".encode() if state != "Z" else b"")
        self._state(pid, state)
        thread = threading.Thread(target=self._mirror, args=(pid, state == "S"), daemon=True)
        thread.start()
        self.threads.append(thread)
        return pid

    def start(self, pid: int) -> str:
        return self.meta[pid][1]

    def publish(self, pid: int, *, ppid: int | None = None, start: str | None = None) -> None:
        """Scripted change of the projected parent or start time; the native process is untouched."""
        old_ppid, old_start, token = self.meta[pid]
        self.meta[pid] = (old_ppid if ppid is None else ppid, old_start if start is None else start, token)

    def _state(self, pid: int, state: str) -> None:
        ppid, start, _ = self.meta[pid]
        stat = self.root / str(pid) / "stat.new"
        stat.write_text(f"{pid} (sleep) {state} {ppid} " + "0 " * 17 + f"{start} 0 0\n", encoding="utf-8")
        stat.replace(stat.with_name("stat"))

    def _mirror(self, pid: int, tracked: bool) -> None:
        while True:
            try:
                _, status = os.waitpid(pid, os.WUNTRACED)
            except ChildProcessError:
                return
            if os.WIFSTOPPED(status):
                self.events.append((pid, "stopped"))
                if (hook := self.on_stop.pop(pid, None)) is not None:
                    hook()
                if tracked:
                    self._state(pid, "T")
                resumed = threading.Thread(target=self._resumed, args=(pid, tracked), daemon=True)
                resumed.start()
                self.threads.append(resumed)
            else:
                killed = os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
                self.events.append((pid, "killed" if killed else "exited"))
                shutil.rmtree(self.root / str(pid), ignore_errors=True)
                return

    def _resumed(self, pid: int, tracked: bool) -> None:
        """Update the projection when a stop ends; this poll is not evidence of CONT."""
        handle = self.handles[pid]
        try:
            while handle.status() == psutil.STATUS_STOPPED:
                time.sleep(0.01)
            resumed = handle.status() not in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD)
        except psutil.NoSuchProcess:
            resumed = False
        if resumed:
            if tracked and pid not in self.frozen:
                try:
                    self._state(pid, "S")
                except FileNotFoundError:  # killed meanwhile; its wait status records that
                    pass

    def stop(self, pid: int) -> None:
        """Injected external stop through the original handle, then wait until the projection shows it."""
        self.handles[pid].suspend()
        deadline = time.monotonic() + 10
        while " T " not in (self.root / str(pid) / "stat").read_text(encoding="utf-8") and time.monotonic() < deadline:
            time.sleep(0.01)

    def close(self) -> None:
        for handle in self.handles.values():
            try:
                handle.kill()  # refuses a PID that the mirror thread reaped and the host reused
            except psutil.NoSuchProcess:
                pass
        for thread in self.threads:
            thread.join(timeout=10)


@pytest.fixture
def projection(tmp_path: Path) -> Iterator[_Projection]:
    root = tmp_path / "proc"
    root.mkdir()
    assert not any(ch.isspace() for ch in str(root))
    owned = _Projection(root)
    try:
        yield owned
    finally:
        owned.close()


def _settle(projection: _Projection, control: Path, leader: int, *, halt: str | None = None) -> tuple[str, str, str]:
    control.mkdir(mode=0o700)
    (control / "proc").write_text(f"{leader} {projection.start(leader)} {TOKEN}\n", encoding="utf-8")
    if halt is not None:
        (control / "halt").write_text(halt, encoding="utf-8")
    script = SETTLE_PROCESS_SH.replace("/proc/", f"{projection.root}/")  # the control record "$c/proc" is not a /proc path
    trace = control.with_name(control.name + ".signals")
    # Preserve the actual signal command and result. A dying stopped process can briefly
    # appear running, so process-table polling must never invent a successful CONT.
    observer = (
        'kill() { command kill "$@"; _repomap_test_signal_rc=$?; '
        f"printf '%s %s\\n' \"$*\" \"$_repomap_test_signal_rc\" >> {shlex.quote(str(trace))}; "
        'return "$_repomap_test_signal_rc"; }\n'
    )
    result = subprocess.run(["sh", "-c", observer + script, "sh", str(control), TOKEN], capture_output=True, text=True, timeout=60, check=False)
    for line in trace.read_text(encoding="utf-8").splitlines() if trace.exists() else []:
        fields = line.split()
        if len(fields) == 3 and fields[0] == "-CONT" and fields[2] == "0":
            projection.events.append((int(fields[1]), "continued"))
    assert result.returncode == 0, result.stderr
    return parse_process_settlement(result.stdout)


def _of(projection: _Projection, pid: int, mark: int = 0) -> list[str]:
    return [e for p, e in projection.events[mark:] if p == pid]


def _await(projection: _Projection, pid: int, expected: list[str], mark: int = 0) -> list[str]:
    """Native events can trail the script's own observation by one poll."""
    deadline = time.monotonic() + 5
    while _of(projection, pid, mark) != expected and time.monotonic() < deadline:
        time.sleep(0.01)
    return _of(projection, pid, mark)


@pytest.mark.parametrize("leader_stopped", [True, False])
def test_unreaped_child_keeps_its_leader_unsignalled(projection: _Projection, tmp_path: Path, leader_stopped: bool) -> None:
    leader = projection.spawn(ppid=0)
    zombie = projection.spawn(ppid=leader, token=False, state="Z")
    if leader_stopped:
        projection.stop(leader)
    mark = len(projection.events)
    control = tmp_path / "ctl"
    report = _settle(projection, control, leader)
    assert projection.events[mark:] == [], f"neither the leader nor its unreaped child was signalled: {projection.events} {report}"
    assert report == ("alive", "retained", "unreaped"), report
    assert sorted(p.name for p in control.iterdir()) == ["proc"], "the exact control path is retained without a held pause"
    assert zombie in projection.meta


@pytest.mark.parametrize("topology", ["live-child", "live-grandchild", "stopped-child", "stopped-parent"])
def test_no_non_leader_invocation_process_is_ever_signalled(projection: _Projection, tmp_path: Path, topology: str) -> None:
    """Scripted topology under a running or stopped token leader; every process is real and owned."""
    leader = projection.spawn(ppid=0)
    child = projection.spawn(ppid=leader)
    family = [leader, child, *([projection.spawn(ppid=child)] if topology == "live-grandchild" else [])]
    if topology != "live-child" and topology != "live-grandchild":
        projection.stop(child if topology == "stopped-child" else leader)
    mark = len(projection.events)
    control = tmp_path / "ctl"
    report = _settle(projection, control, leader)
    assert projection.events[mark:] == [], f"settlement observed but never signalled {family}: {projection.events[mark:]}"
    assert report == ("alive", "retained", "remaining"), report
    assert sorted(p.name for p in control.iterdir()) == ["proc"]
    assert all(handle.is_running() for handle in projection.handles.values()), "every invocation process is still alive"


@pytest.mark.parametrize("externally_stopped", [False, True])
@pytest.mark.parametrize(("parent", "descendants"), [("pid1", "remaining"), ("in-container", "unknown")])
def test_a_recorded_leader_not_under_the_exec_shim_is_never_signalled(
    projection: _Projection, tmp_path: Path, externally_stopped: bool, parent: str, descendants: str
) -> None:
    """Scripted PPid 1 or an untokened in-container parent: either could leave a killed leader for the PID 1 postmaster."""
    leader = projection.spawn(ppid=1 if parent == "pid1" else projection.spawn(ppid=0, token=False))
    if externally_stopped:
        projection.stop(leader)
    mark = len(projection.events)
    control = tmp_path / "ctl"
    report = _settle(projection, control, leader)
    assert projection.events[mark:] == [], f"the leader was neither stopped, resumed nor killed: {projection.events[mark:]}"
    assert report == ("alive", "retained", descendants), report
    assert sorted(p.name for p in control.iterdir()) == ["proc"]


@pytest.mark.parametrize("externally_stopped", [False, True])
def test_a_childless_leader_is_retired_after_a_confirmed_stop(projection: _Projection, tmp_path: Path, externally_stopped: bool) -> None:
    leader = projection.spawn(ppid=0)
    if externally_stopped:
        projection.stop(leader)
    mark = len(projection.events)
    control = tmp_path / "ctl"
    report = _settle(projection, control, leader)
    assert report == ("killed", "removed", "none"), f"{report} {projection.events}"
    assert _of(projection, leader, mark) == (["killed"] if externally_stopped else ["stopped", "killed"]), projection.events
    assert not control.exists(), "the pause record and control path are removed once the kill is observed"


@pytest.mark.parametrize(("kind", "descendants"), [("token", "remaining"), ("untokened", "unknown"), ("zombie", "unreaped")])
def test_a_child_found_at_the_leader_stop_is_left_alone(projection: _Projection, tmp_path: Path, kind: str, descendants: str) -> None:
    """Injected fork: the projection publishes a child as the leader stops, before its stopped state."""
    leader = projection.spawn(ppid=0)
    forked: list[int] = []
    projection.on_stop[leader] = lambda: forked.append(
        projection.spawn(ppid=leader, token=kind == "token", state="Z" if kind == "zombie" else "S")
    )
    control = tmp_path / "ctl"
    report = _settle(projection, control, leader)
    [child] = forked
    assert report == ("alive", "retained", descendants), f"{report} {projection.events}"
    assert _await(projection, leader, ["stopped", "continued"]) == ["stopped", "continued"], "only its own stop is resumed"
    assert _of(projection, child) == [] and projection.handles[child].is_running(), f"the child keeps running: {projection.events}"
    assert sorted(p.name for p in control.iterdir()) == ["proc"], "the pause record is removed only after the resume is seen"


@pytest.mark.parametrize(("change", "remote", "leader_events"), [
    ("adopted", "alive", ["stopped"]), ("reused", "unknown", ["stopped"]), ("unconfirmed", "alive", ["stopped", "continued"]),
])
def test_an_unproven_resume_keeps_the_exact_pause_record(
    projection: _Projection, tmp_path: Path, change: str, remote: str, leader_events: list[str]
) -> None:
    """Injected at the leader's stop: a child, plus PPid 1, a new start time, or a stop that stays published."""
    leader = projection.spawn(ppid=0)
    start = projection.start(leader)
    forked: list[int] = []

    def at_stop() -> None:
        forked.append(projection.spawn(ppid=leader))
        if change == "adopted":
            projection.publish(leader, ppid=1)
        elif change == "reused":
            projection.publish(leader, start="9999")
        else:
            projection.frozen.add(leader)

    projection.on_stop[leader] = at_stop
    control = tmp_path / "ctl"
    report = _settle(projection, control, leader)
    assert report == (remote, "retained", "remaining"), f"{report} {projection.events}"
    assert _await(projection, leader, leader_events) == leader_events, "never resume an adopted or reused identity"
    assert _of(projection, forked[0]) == [], projection.events
    assert sorted(p.name for p in control.iterdir()) == ["halt", "proc"]
    assert (control / "halt").read_text(encoding="utf-8") == f"{leader} {start}\n", "the exact introduced pause stays recorded"


def test_an_existing_pause_record_prevents_every_signal(projection: _Projection, tmp_path: Path) -> None:
    leader = projection.spawn(ppid=0)
    control = tmp_path / "ctl"
    report = _settle(projection, control, leader, halt=f"{leader} {projection.start(leader)}\n")
    assert projection.events == [] and report == ("alive", "retained", "unknown"), f"{report} {projection.events}"
    assert (control / "halt").read_text(encoding="utf-8") == f"{leader} {projection.start(leader)}\n"


def test_an_orphan_outranks_every_other_census_finding(projection: _Projection, tmp_path: Path) -> None:
    """Session safety: an orphan reports ``remaining`` even when an untokened child or a mismatch is listed first."""
    leader = projection.spawn(ppid=0)
    first, second = sorted((projection.spawn(ppid=leader, token=False), projection.spawn(ppid=leader, token=False)), key=str)
    shutil.rmtree(projection.root / str(second))
    projection.meta[second] = (1, projection.start(second), True)  # republish the later-listed process as a token orphan
    (projection.root / str(second)).mkdir()
    (projection.root / str(second) / "environ").write_bytes(f"REPOMAP_EXT_INVOCATION={TOKEN}\0".encode())
    projection._state(second, "S")
    leader_report = _settle(projection, tmp_path / "ctl", leader)
    mismatch_report = _settle(projection, tmp_path / "mis", first)
    assert (leader_report, mismatch_report) == (("alive", "retained", "remaining"), ("mismatch", "retained", "remaining")), (leader_report, mismatch_report)
    assert projection.events == [], "nothing was signalled"


class _Bounded:
    """Injected bounded runner: a timed-out command, then one scripted settlement report."""

    def __init__(self, report: bytes) -> None:
        self.report = report
        self.kinds: list[str] = []

    def __call__(self, command: list[str], **kwargs: Any) -> bytes:
        kind = "process" if SETTLE_PROCESS_SH in command else "sessions" if "pg_terminate_backend" in " ".join(command) else "command"
        self.kinds.append(kind)
        if kind == "command":
            kwargs["retirement"].state = "retired"
            raise provenance_error("local-db-command-failed", "toc", "provenance command timed out")
        return self.report if kind == "process" else b"0\n0\n"


@pytest.mark.parametrize(("report", "descendants"), [
    (b"REMOTE alive\nCONTROL retained\nDESCENDANTS unreaped\n", "unreaped"),
    (b"REMOTE alive\nCONTROL retained\nDESCENDANTS remaining\n", "remaining"),
    (b"REMOTE alive\nCONTROL retained\nDESCENDANTS unknown\n", "unknown"),
    (b"REMOTE killed\nCONTROL removed\nDESCENDANTS killed\n", "unknown"),
    (b"UNAVAILABLE grep\n", "unknown"),
])
def test_unsettled_descendants_leave_correlated_sessions_unterminated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, report: bytes, descendants: str
) -> None:
    """Scripted reports; terminating a session could make a retained client exit abnormally into an adopting PID 1."""
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    setup_local_runtime(home)
    (home / "runtime").chmod(0o700)
    plan = build_local_runtime_plan(home)
    plan.env_file.chmod(0o600)
    bounded = _Bounded(report)
    monkeypatch.setattr(exec_mod, "run_bounded_popen", bounded)
    with bound_exec_custody(CONTAINER_ID) as custody, pytest.raises(LocalDbBackupError) as failure:
        run_bounded_ext_command(plan, [plan.container_runtime, "exec", plan.identity.postgres_container, "sh", "-uc", "true"], subprocess.run, field="toc")
    [outcome] = custody.outcomes
    assert bounded.kinds == ["command", "process"], f"no correlated session is terminated: {bounded.kinds} {outcome.summary()}"
    assert (outcome.descendants, outcome.sessions) == (descendants, "unknown") and custody.unknown == [outcome]
    assert [d.code for d in failure.value.diagnostics] == ["local-db-command-failed", "restore-exec-outcome-unknown"]
    assert f"descendants={descendants}" in failure.value.diagnostics[1].message and outcome.control_path in failure.value.diagnostics[1].message
