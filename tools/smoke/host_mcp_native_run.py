"""One execution of the host MCP native proof against a run-owned backend.

``execute_run`` owns ordering and cleanup; the backend owns the PostgreSQL
resource (an owned Docker container natively, harness databases in the Linux
integration seam). Parent setup authority (the fixture admin credential, held
in a 0600 pgpass file inside the owner-private work root and referenced only by
path) is separate from MCP read authority (the setup-generated read/status
secret, read in memory by the product from ``runtime/.env``). The child
receives neither; its environment is built from scratch.

A secret-free ``OWNER.json`` is on disk before the backend starts. Catchable
SIGINT, SIGTERM and SIGHUP pass through ``InterruptionGate``: the first one
during active work cancels it, and none can unwind cleanup or finalization.
SIGKILL, a crash, machine loss or a full disk are not covered; ``OWNER.json``
is the recovery record then.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import shlex
import shutil
import signal
import sys
import tempfile
import threading
import traceback
from typing import Any, Protocol

from .host_mcp_native_evidence import EvidenceWriter
from .host_mcp_native_launch import ChildLayout, ChildTracker, ConsoleEntrypoint, child_environment

EXIT_CODES = {"completed_pending_manager_review": 0, "checks_failed": 1, "failed": 1, "not_run": 2,
              "cleanup_incomplete": 3, "interrupted": 130}
QUALIFICATION_CLASSES = ("native-macos-checkout-console", "linux-harness-exercise")
PARENT_STRIPPED_PREFIXES = ("PG",)
PARENT_STRIPPED_KEYS = ("REPOMAP_STORAGE_PG_CONNECTOR", "REPOMAP_STORAGE_READBACK_DRIVER", "REPOMAP_PG_HOST",
                        "REPOMAP_PG_PORT", "REPOMAP_PG_USER", "REPOMAP_PG_DATABASE", "REPOMAP_PSQL_COMMAND",
                        "REPOMAP_MCP_CONFIG", "REPOMAP_OPS_CONFIG", "REPOMAP_HOME")


PHASES = ("pending", "active", "cleanup", "finalize")
HANDLED_SIGNALS = tuple(getattr(signal, name) for name in ("SIGINT", "SIGTERM", "SIGHUP") if hasattr(signal, name))


class RunInterrupted(BaseException):
    """Raised once, by the first catchable signal during active work, so scoped cleanup still runs."""


class Backend(Protocol):
    kind: str

    def describe(self) -> dict[str, Any]: ...
    def manual_cleanup(self) -> str: ...
    def start(self) -> Any: ...
    def create_database(self, name: str) -> Any: ...
    def route_evidence(self) -> dict[str, Any]: ...
    def stop_for_outage(self) -> dict[str, Any]: ...
    def outage_active(self) -> bool: ...
    def cleanup(self) -> list[dict[str, Any]]: ...


Scenario = Callable[..., str]  # (context, backend, console, layout, env, tracker, summary) -> outcome


@dataclass(frozen=True)
class RunContext:
    run_id: str
    work: Path
    evidence: EvidenceWriter
    parent_bin: Path
    platform: str = sys.platform


def new_work_root(run_id: str) -> Path:
    """Owner-private (0700) work root holding the home, pgpass, psql wrapper and child dirs."""
    return Path(tempfile.mkdtemp(prefix=f"repomap-{run_id}-")).resolve()


def outcome_exit(outcome: str) -> int:
    return EXIT_CODES.get(outcome, 1)


@contextmanager
def parent_environment(parent_bin: Path, work: Path) -> Iterator[dict[str, Any]]:
    """Strip PostgreSQL/RepoMap selectors from the parent itself; restore exactly afterwards."""
    saved, saved_tempdir = dict(os.environ), tempfile.tempdir
    removed = sorted(key for key in os.environ if key.startswith(PARENT_STRIPPED_PREFIXES)
                     or key in PARENT_STRIPPED_KEYS or (key.startswith("REPOMAP_") and "PASSWORD" in key))
    try:
        for key in removed:
            del os.environ[key]
        os.environ["REPOMAP_STORAGE_READBACK_DRIVER"] = "psycopg"
        os.environ["PATH"] = f"{parent_bin}{os.pathsep}{saved.get('PATH', '/usr/bin:/bin')}"
        (work / "parent-tmp").mkdir(mode=0o700, exist_ok=True)
        tempfile.tempdir = str(work / "parent-tmp")  # the maintained psql wrapper lands in the owned root
        yield {"removed_keys": removed, "set": {"REPOMAP_STORAGE_READBACK_DRIVER": "psycopg"},
               "path_prepended": str(parent_bin), "tempdir": tempfile.tempdir,
               "python3_on_path": shutil.which("python3")}
    finally:
        os.environ.clear()
        os.environ.update(saved)
        tempfile.tempdir = saved_tempdir


def write_pgpass(work: Path, admin: Any) -> Path:
    def escape(value: Any) -> str:
        return str(value).replace("\\", "\\\\").replace(":", "\\:")

    path = work / "parent-pgpass"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{escape(admin.host)}:{admin.port}:*:{escape(admin.user)}:{escape(admin.password)}\n")
    os.environ["PGPASSFILE"] = str(path)
    return path


class InterruptionGate:
    """Phase-aware handling of catchable SIGINT, SIGTERM and (where the platform has it) SIGHUP.

    Phases only advance: ``pending`` -> ``active`` -> ``cleanup`` -> ``finalize``. Every signal is
    recorded with the phase it arrived in. Only the first signal of the whole run may raise
    ``RunInterrupted``, and only while work is ``active`` (a ``pending`` signal is raised on
    activation), so once cleanup has begun no signal can unwind cleanup or evidence finalization.
    """

    def __init__(self) -> None:
        self.phase = PHASES[0]
        self.received: list[dict[str, str]] = []
        self.interrupted_by: str | None = None
        self.handling: dict[str, str] = {}

    def handle(self, signum: int, _frame: Any) -> None:
        name, phase = signal.Signals(signum).name, self.phase
        self.received.append({"signal": name, "phase": phase})
        if phase == "active":
            self._interrupt(name)

    def enter(self, phase: str) -> None:
        if PHASES.index(phase) <= PHASES.index(self.phase):
            return
        self.phase = phase
        pending = [entry["signal"] for entry in self.received if entry["phase"] == "pending"]
        if phase == "active" and pending:
            self._interrupt(pending[0])

    @contextmanager
    def active(self) -> Iterator[None]:
        try:
            self.enter("active")
            yield
        finally:
            self.enter("cleanup")

    def timing(self) -> str:
        """Honest category: a signal first seen in teardown did not cancel the executed work."""
        phases = {entry["phase"] for entry in self.received}
        if self.interrupted_by is not None:
            return "interrupted_active_work"
        if not phases:
            return "none"
        return "teardown_only_deferred" if phases <= {"cleanup", "finalize"} else "received_before_work_started"

    def _interrupt(self, name: str) -> None:
        if self.interrupted_by is None:
            self.interrupted_by = name
            raise RunInterrupted(name)


@contextmanager
def interruption_gate() -> Iterator[InterruptionGate]:
    """Install the gate over the caller's handlers; restore exactly the ones replaced on every exit.

    A signal the caller ignores (for example SIGHUP under ``nohup``) stays ignored, and a handler not
    installed from Python cannot be restored, so it is left alone. Off the main thread nothing is
    installed and the caller's handling applies.
    """
    gate, previous = InterruptionGate(), dict[int, Any]()
    try:
        if threading.current_thread() is threading.main_thread():
            for sig in HANDLED_SIGNALS:
                current, name = signal.getsignal(sig), signal.Signals(sig).name
                if current is None or current == signal.SIG_IGN:
                    gate.handling[name] = "left to the caller: " + ("ignored" if current is not None
                                                                    else "handler not installed from Python")
                    continue
                previous[sig] = current
                signal.signal(sig, gate.handle)
                gate.handling[name] = "gated"
        yield gate
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def ownership_record(context: RunContext, backend: Backend) -> dict[str, Any]:
    """Minimal secret-free recovery record, on disk before the backend starts."""
    described = backend.describe()
    return {"schema": "repomap-host-mcp-native-owner-v1", "run_id": context.run_id, "runner_pid": os.getpid(),
            "work_root": str(context.work), "evidence_dir": str(context.evidence.run_dir),
            "backend": {key: described[key] for key in ("kind", "container_name", "label") if key in described},
            "manual_cleanup": [backend.manual_cleanup(), f"rm -rf -- {shlex.quote(str(context.work))}"],
            "use": "only if receipt.json is absent beside this file; act on exactly these names and nothing else"}


def execute_run(context: RunContext, backend: Backend, console: ConsoleEntrypoint, *, qualification_class: str,
                scenario: Scenario, test_extra_path: Sequence[str] = ()) -> int:
    """Create the fixture, run every MCP session, clean up, and finalize evidence exactly once."""
    if qualification_class not in QUALIFICATION_CLASSES:
        raise ValueError(f"unknown qualification class: {qualification_class}")

    evidence, tracker = context.evidence, ChildTracker()
    summary: dict[str, Any] = {"qualification_class": qualification_class}
    with interruption_gate() as gate:
        summary.update(signals=gate.received, signal_handling=gate.handling)
        outcome = "failed"
        try:
            evidence.add_secret(getattr(backend, "password", None))  # the early record refuses it by value
            owner = evidence.write_early_json("OWNER.json", ownership_record(context, backend))
            evidence.write_json("run.json", {"backend": backend.describe(), "console": console.jsonable(),
                                             "qualification_class": qualification_class})
            _notify(f"run {context.run_id}: ownership record {owner}; if no receipt appears, remove only this "
                    f"run's container with: {backend.manual_cleanup()}")
            # The gate is entered inside the parent environment so its restore runs with signals deferred.
            with parent_environment(context.parent_bin, context.work) as parent, gate.active():
                evidence.write_json("parent-environment.json", {**parent, "role": "parent setup authority only; "
                                                                "never forwarded to the MCP child"})
                layout = ChildLayout(context.work / "child").create()
                env = child_environment(layout, context.platform, test_extra_path=test_extra_path)
                outcome = scenario(context, backend, console.path, layout, env, tracker, summary)
        except BaseException as error:  # recorded through the redacting writer; setup failure is not success
            gate.enter("cleanup")
            if isinstance(error, RunInterrupted):
                outcome, summary["interrupted_by"] = "interrupted", str(error)
            else:
                outcome = "interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "failed"
                summary["error"] = f"{type(error).__name__}: {error}"
                evidence.write_text("error.txt", traceback.format_exc())
        finally:
            gate.enter("cleanup")
            cleanup = [_attempt("reap-child", tracker.reap), *_backend_cleanup(backend),
                       _attempt("remove-work-root", lambda: _remove_work(context.work))]
            gate.enter("finalize")
            evidence.write_json("cleanup.json", {"steps": cleanup, "launched_child_pids": tracker.launched,
                                                 "signals_received": gate.received,
                                                 "backend_commands": getattr(backend, "commands", None)})
            if not all(step.get("ok") for step in cleanup):
                summary["outcome_before_cleanup"], outcome = outcome, "cleanup_incomplete"
            summary["signal_timing"] = gate.timing()
            receipt = evidence.finalize(outcome=outcome, exit_code=outcome_exit(outcome),
                                        qualification_class=qualification_class, summary=summary)
        late = "" if gate.timing() != "teardown_only_deferred" else (
            f"; {', '.join(entry['signal'] for entry in gate.received)} arrived during teardown and was deferred; "
            "it did not cancel the executed work")
        _notify(f"run {context.run_id}: {receipt['outcome']} (exit {receipt['exit_code']}); evidence "
                f"{evidence.run_dir / 'evidence.zip'} sha256 {receipt['zip']['sha256']}{late}")
    return int(receipt["exit_code"])


def _notify(message: str) -> None:
    """Best-effort operator notice; a closed terminal (for example after SIGHUP) never changes the outcome."""
    try:
        print(message, file=sys.stderr, flush=True)
    except OSError:
        pass


def _attempt(step: str, action: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """One owned cleanup operation; its failure is recorded and never skips the later ones."""
    try:
        return action()
    except BaseException as error:  # a cleanup failure is reported, never converted into success
        return {"step": step, "ok": False, "error": f"{type(error).__name__}: {error}"}


def _backend_cleanup(backend: Backend) -> list[dict[str, Any]]:
    try:
        return backend.cleanup()
    except BaseException as error:  # a cleanup failure is reported, never converted into success
        return [{"step": "backend-cleanup", "ok": False, "error": f"{type(error).__name__}: {error}"}]


def _remove_work(work: Path) -> dict[str, Any]:
    """Remove the owned work root, including the pgpass file, psql wrapper and runtime/.env secrets."""
    shutil.rmtree(work, ignore_errors=True)
    return {"step": "remove-work-root", "ok": not work.exists(), "path": str(work)}


def run_token() -> str:
    return secrets.token_hex(4)
