"""PREPARE1/PREPARE2 operator-runner contracts: modes, prerequisites, ownership, interruption, cleanup.

No test here starts Docker, PostgreSQL, or the product: subprocess boundaries
are injected runners, and ``execute_run`` receives a fake scenario and backend.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any
import zipfile

import pytest

from repomap_test_support import postgres_container
from smoke import host_mcp_native as cli
from smoke.host_mcp_native_backend import OwnedContainerBackend
from smoke.host_mcp_native_evidence import EvidenceWriter
from smoke.host_mcp_native_launch import ConsoleEntrypoint
from smoke.host_mcp_native_run import RunContext, execute_run, parent_environment, write_pgpass

SECRET = "admin-secret-value-0123456789"
HANDLED = ("SIGINT", "SIGTERM", "SIGHUP")


class Recorder:
    def __init__(self, replies: dict[str, tuple[int, str]] | None = None) -> None:
        self.commands: list[list[str]] = []
        self.replies, self.sessions = replies or {}, list[Any]()

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(argv))
        self.sessions.append(kwargs.get("start_new_session"))
        for marker, (code, stdout) in self.replies.items():
            if marker in " ".join(argv):
                return subprocess.CompletedProcess(argv, code, stdout, "")
        return subprocess.CompletedProcess(argv, 0, "", "")


class FakeBackend:
    """Only what ``execute_run`` itself calls; the fake scenarios never create databases or outages."""

    kind = "fake"
    password = SECRET

    def __init__(self, *, cleanup_ok: bool = True, described: dict[str, Any] | None = None) -> None:
        self.cleanup_ok, self.cleaned, self.described = cleanup_ok, False, described or {"kind": self.kind}
        self.on_start: Callable[[], Any] | None = None
        self.hook: Callable[[], Any] | None = None

    def describe(self) -> dict[str, Any]:
        return self.described

    def manual_cleanup(self) -> str:
        return "docker rm -f repomap-test-postgres-fake"

    def start(self) -> Any:
        if self.on_start is None:
            raise AssertionError("the fake scenario never starts the backend")
        return self.on_start()

    def cleanup(self) -> list[dict[str, Any]]:
        if self.hook is not None:
            self.hook()
        self.cleaned = True
        return [{"step": "fake-cleanup", "ok": self.cleanup_ok}]


def _console(tmp_path: Path) -> ConsoleEntrypoint:
    return ConsoleEntrypoint(path=tmp_path / "repomap-kg", sha256="0" * 64, form="absolute-shebang",
                             shebang_lines=("#!/c/.venv/bin/python3",), interpreter="/c/.venv/bin/python3",
                             interpreter_realpath="/c/.venv/bin/python3", targets_cli_main=True)


def _context(tmp_path: Path) -> RunContext:
    work = tmp_path / "work"
    work.mkdir(mode=0o700)
    evidence = EvidenceWriter(tmp_path / "outbox" / "PHASE-X" / "native1-run", run_id="native1-run", phase="PHASE-X")
    return RunContext(run_id="native1-run", work=work, evidence=evidence, parent_bin=Path(sys.executable).parent)


def _manifest(context: RunContext) -> dict[str, Any]:
    with zipfile.ZipFile(context.evidence.run_dir / "evidence.zip") as archive:
        return json.loads(archive.read("native1-run/MANIFEST.json"))


class Sentinels:
    """Explicit caller handlers, so the gate never depends on the inherited signal disposition."""

    def __init__(self) -> None:
        self.calls: list[int] = []
        self.handled = [getattr(signal, name) for name in HANDLED if hasattr(signal, name)]

    def __call__(self, signum: int, _frame: Any) -> None:
        self.calls.append(signum)

    def callback(self, sig: int) -> Callable[[int, Any], Any]:
        """The runner's installed handler; never the default action, SIG_IGN, or this sentinel."""
        handler = signal.getsignal(sig)
        assert callable(handler) and handler is not self and handler is not signal.default_int_handler, handler
        return handler

    def restored(self) -> bool:
        return all(signal.getsignal(sig) is self for sig in self.handled) and not self.calls


@pytest.fixture
def sentinels() -> Iterator[Sentinels]:
    sentinel = Sentinels()
    previous = {sig: signal.signal(sig, sentinel) for sig in sentinel.handled}
    try:
        yield sentinel
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, signal.SIG_DFL if handler is None else handler)


class LateProcess:
    """A finished child whose ``poll`` runs a hook at cleanup entry; it is never signalled."""

    pid = 999_999_999

    def __init__(self, hook: Callable[[], Any]) -> None:
        self.hook: Callable[[], Any] | None = hook

    def poll(self) -> int:
        hook, self.hook = self.hook, None
        if hook is not None:
            hook()
        return 0


def _run(context: RunContext, backend: Any, scenario: Callable[..., str],
         qualification_class: str = "linux-harness-exercise") -> int:
    return execute_run(context, backend, _console(context.work.parent), qualification_class=qualification_class,
                       scenario=scenario)


def _late(hook: Callable[[], Any], *, active: Callable[[], Any] | None = None) -> Callable[..., str]:
    """Scenario leaving a finished child whose ``poll`` runs ``hook`` at cleanup entry; ``active`` runs first."""
    def scenario(ctx, backend, console, layout, env, tracker, summary) -> str:
        tracker.live = LateProcess(hook)
        if active is not None:
            active()
        return "completed_pending_manager_review"

    return scenario


def _raising(error: BaseException) -> Callable[..., Any]:
    def fail(*args: Any, **kwargs: Any) -> Any:
        raise error

    return fail


@pytest.mark.parametrize("name", HANDLED)
def test_first_signal_at_cleanup_entry_cannot_unwind_cleanup_or_evidence(
        tmp_path: Path, sentinels: Sentinels, name: str) -> None:
    """Deterministic invocation of the installed callback from ``reap`` (not an OS signal); PREPARE1 escaped here."""
    if not hasattr(signal, name):
        pytest.skip(f"{name} is absent on this platform")
    sig, context, backend = getattr(signal, name), _context(tmp_path), FakeBackend()
    code = _run(context, backend, _late(lambda: sentinels.callback(sig)(sig, None)))
    manifest = _manifest(context)
    assert code == 0 and manifest["outcome"] == "completed_pending_manager_review" and sentinels.restored()
    assert backend.cleaned and not context.work.exists() and (context.evidence.run_dir / "receipt.json").is_file()
    assert manifest["summary"]["signals"] == [{"signal": name, "phase": "cleanup"}]
    assert manifest["summary"]["signal_timing"] == "teardown_only_deferred"


def test_parser_defaults_to_check_and_has_no_native_bypass() -> None:
    parser = cli.build_parser()
    options = {option for action in parser._actions for option in action.option_strings}
    assert options == {"-h", "--help", "--check", "--execute", "--build-kit", "--checkout", "--phase",
                       "--outbox-root"}
    args = parser.parse_args(["--checkout", "/c"])
    assert not args.execute and args.build_kit is None and args.phase == cli.DEFAULT_PHASE


def test_execute_off_macos_is_not_run_and_creates_no_resource(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = Recorder()
    pre = cli.check_prerequisites(tmp_path / "missing-checkout", tmp_path, platform="linux", runner=runner)
    assert pre.items[0] == {**pre.items[0], "name": "platform", "status": "refused"}
    assert not pre.ok and pre.items[-1] == {"name": "docker", "status": "skipped",
                                            "reason": "an earlier prerequisite was refused"}
    assert not any(command[0] == "docker" for command in runner.commands)

    monkeypatch.setattr(cli, "check_prerequisites", lambda *a, **k: pre)
    monkeypatch.setattr(OwnedContainerBackend, "__init__",
                        lambda *a, **k: pytest.fail("a backend was constructed for a refused run"))
    code = cli.main(["--execute", "--checkout", str(tmp_path), "--outbox-root", str(tmp_path / "out")],
                    kit_root=tmp_path, runner=runner)
    receipt = json.loads(next((tmp_path / "out").rglob("receipt.json")).read_text())
    assert code == 2 and receipt["outcome"] == "not_run" and receipt["exit_code"] == 2
    assert receipt["attests"] == "evidence delivery only; not Product step 3 acceptance"


def test_local_prerequisite_refusals_never_probe_docker(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    (checkout / ".venv" / "bin").mkdir(parents=True)
    runner = Recorder({"status --porcelain": (0, " M src/main/python/repomap_kg/cli.py\n"),
                       "rev-parse": (0, "abc\ndef\n")})
    pre = cli.check_prerequisites(checkout, tmp_path, platform="darwin", runner=runner)
    statuses = {item["name"]: item["status"] for item in pre.items}
    assert statuses["kit"] == statuses["checkout-clean"] == statuses["console-present"] == "refused"
    assert statuses["docker"] == "skipped" and not pre.ok and pre.port is None
    assert not any(command[0] == "docker" for command in runner.commands)


def test_docker_image_absence_names_the_manual_pull_and_pulls_nothing() -> None:
    runner = Recorder({"version": (0, "27.0\n"), "image inspect": (1, "")})
    pre = cli.Prerequisites()
    cli._docker(pre, runner)
    image = pre.items[-1]
    assert image["status"] == "refused" and image["manual_pull"].startswith("docker pull postgres:16-alpine@sha256:")
    assert not any("pull" in command for command in runner.commands)
    down = cli.Prerequisites()
    cli._docker(down, Recorder({"version": (1, "")}))
    assert [item["name"] for item in down.items] == ["docker"] and not down.ok


def test_owned_backend_acts_only_on_the_exact_loopback_container(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/local/bin/{name}")
    monkeypatch.setattr(postgres_container, "is_local_port_open", lambda host, port: False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    # Natively no in-process test resource run exists; the unit runner installs one.
    monkeypatch.setattr(postgres_container, "active_resource_run", lambda: None)
    runner = Recorder({"inspect --format {{.State.Running}}": (0, "false\n"), "port ": (0, "127.0.0.1:61234\n")})
    backend = OwnedContainerBackend(port=61234, run_id="native1ab12cd34", runner=runner)
    assert backend.name == "repomap-test-postgres-native1ab12cd34"
    admin = backend.start()
    run = next(command for command in runner.commands if command[:2] == ["docker", "run"])
    assert "--pull=never" in run and "127.0.0.1:61234:5432" in run and backend.name in run
    assert "org.repomap.test.run_id=native1ab12cd34" in run and "--tmpfs" in run
    assert not any(backend.password in part for part in run)
    assert admin.port == 61234 and Path(admin.psql_command).stat().st_mode & 0o777 == 0o700
    assert backend.route_evidence()["docker_port"] == "127.0.0.1:61234"
    assert backend.stop_for_outage()["command"] == f"docker stop --time 10 {backend.name}"
    assert backend.outage_active()
    steps = backend.cleanup()
    assert [step["ok"] for step in steps] == [True, True]
    assert ["docker", "rm", "-f", backend.name] in runner.commands
    assert ["docker", "ps", "-a", "-q", "--filter", f"label={backend.label}"] in runner.commands
    touched = {part for command in runner.commands for part in command if part.startswith("repomap-test-postgres-")}
    assert touched == {backend.name}
    assert not any(word in command for command in runner.commands for word in ("prune", "pull", "kill"))
    assert runner.sessions == [True] * len(runner.commands), "docker helpers must leave the terminal's group"


def test_parent_environment_strips_selectors_and_restores_exactly(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("PGPASSWORD", "PGSERVICE", "REPOMAP_STORAGE_PG_CONNECTOR", "REPOMAP_READ_STATUS_PASSWORD",
                "REPOMAP_MCP_CONFIG", "REPOMAP_HOME"):
        monkeypatch.setenv(key, "poison")
    monkeypatch.setenv("REPOMAP_TEST_UNRELATED", "kept")
    before, tempdir = dict(os.environ), tempfile.tempdir
    with parent_environment(tmp_path / "venv bin", tmp_path) as record:
        assert not any(key.startswith("PG") for key in os.environ)
        assert os.environ["REPOMAP_STORAGE_READBACK_DRIVER"] == "psycopg"
        assert os.environ["REPOMAP_TEST_UNRELATED"] == "kept"
        assert os.environ["PATH"].startswith(str(tmp_path / "venv bin"))
        assert "REPOMAP_READ_STATUS_PASSWORD" in record["removed_keys"] and "poison" not in json.dumps(record)
        admin = type("Admin", (), {"host": "127.0.0.1", "port": 5, "user": "u", "password": "p:w"})()
        pgpass = write_pgpass(tmp_path, admin)
        assert pgpass.stat().st_mode & 0o777 == 0o600 and os.environ["PGPASSFILE"] == str(pgpass)
        assert pgpass.read_text() == "127.0.0.1:5:*:u:p\\:w\n"
    assert dict(os.environ) == before and tempfile.tempdir == tempdir


def test_interruption_reaps_the_child_cleans_up_and_writes_evidence(tmp_path: Path, sentinels: Sentinels) -> None:
    """A real OS SIGINT (``os.kill``) during active work."""
    context, backend = _context(tmp_path), FakeBackend()
    children: list[subprocess.Popen[str]] = []

    def scenario(ctx, backend, console, layout, env, tracker, summary) -> str:
        tracker.live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                        start_new_session=True, text=True)
        children.append(tracker.live)
        os.kill(os.getpid(), signal.SIGINT)
        time.sleep(30)
        pytest.fail("SIGINT did not interrupt the run")

    code = _run(context, backend, scenario)
    manifest = _manifest(context)
    assert code == 130 and manifest["outcome"] == "interrupted" and children[0].poll() is not None
    assert backend.cleaned and not context.work.exists() and sentinels.restored()
    assert manifest["summary"]["interrupted_by"] == "SIGINT"
    assert manifest["summary"]["signal_timing"] == "interrupted_active_work"


def test_active_interrupt_then_repeated_cleanup_signals_unwind_nothing(tmp_path: Path, sentinels: Sentinels) -> None:
    """Callback invocations plus one real ``signal.raise_signal`` delivered while cleanup runs."""
    context, backend, sigint, sigterm = _context(tmp_path), FakeBackend(), signal.SIGINT, signal.SIGTERM

    def cleanup_signals() -> None:
        sentinels.callback(sigint)(sigint, None)
        signal.raise_signal(sigint)

    backend.hook = lambda: sentinels.callback(sigint)(sigint, None)
    code = _run(context, backend, _late(cleanup_signals, active=lambda: sentinels.callback(sigterm)(sigterm, None)))
    summary = _manifest(context)["summary"]
    assert code == 130 and summary["interrupted_by"] == "SIGTERM" and sentinels.restored()
    assert [entry["phase"] for entry in summary["signals"]] == ["active", "cleanup", "cleanup", "cleanup"]
    assert backend.cleaned and not context.work.exists() and (context.evidence.run_dir / "receipt.json").is_file()


def test_finalize_entry_signal_keeps_evidence_and_a_finalize_failure_restores_handlers(
        tmp_path: Path, sentinels: Sentinels, monkeypatch: pytest.MonkeyPatch) -> None:
    context, sig = _context(tmp_path), getattr(signal, "SIGHUP", signal.SIGTERM)
    finalize = context.evidence.finalize

    def late_finalize(**kwargs: Any) -> dict[str, Any]:
        sentinels.callback(sig)(sig, None)
        return finalize(**kwargs)

    monkeypatch.setattr(context.evidence, "finalize", late_finalize)
    assert _run(context, FakeBackend(), lambda *args: "checks_failed") == 1 and sentinels.restored()
    assert _manifest(context)["summary"]["signals"] == [{"signal": signal.Signals(sig).name, "phase": "finalize"}]
    assert (context.evidence.run_dir / "receipt.json").is_file()
    (tmp_path / "full").mkdir()
    full = _context(tmp_path / "full")
    monkeypatch.setattr(full.evidence, "finalize", _raising(OSError("no space")))
    with pytest.raises(OSError, match="no space"):
        _run(full, FakeBackend(), lambda *args: "completed_pending_manager_review")
    assert sentinels.restored() and not full.work.exists()


def test_each_cleanup_step_runs_after_an_earlier_one_fails(tmp_path: Path, sentinels: Sentinels) -> None:
    context, backend = _context(tmp_path), FakeBackend()
    assert _run(context, backend, _late(_raising(OSError("reap failed")))) == 3
    with zipfile.ZipFile(context.evidence.run_dir / "evidence.zip") as archive:
        cleanup = json.loads(archive.read("native1-run/cleanup.json"))
    assert cleanup["steps"][0] == {"step": "reap-child", "ok": False, "error": "OSError: reap failed"}
    assert backend.cleaned and not context.work.exists() and sentinels.restored()
    assert _manifest(context)["summary"]["outcome_before_cleanup"] == "completed_pending_manager_review"


def test_an_ignored_signal_stays_ignored(tmp_path: Path, sentinels: Sentinels) -> None:
    sighup = getattr(signal, "SIGHUP", None)
    if sighup is None:
        pytest.skip("SIGHUP is absent on this platform")
    signal.signal(sighup, signal.SIG_IGN)
    context, seen = _context(tmp_path), list[Any]()
    assert _run(context, FakeBackend(), _late(lambda: None, active=lambda: seen.append(signal.getsignal(sighup)))) == 0
    assert seen == [signal.SIG_IGN] and signal.getsignal(sighup) == signal.SIG_IGN
    assert _manifest(context)["summary"]["signal_handling"]["SIGHUP"] == "left to the caller: ignored"


def test_ownership_record_is_on_disk_before_the_backend_starts(tmp_path: Path, sentinels: Sentinels) -> None:
    context, seen, owner_path = _context(tmp_path), dict[str, Any](), tmp_path / "outbox/PHASE-X/native1-run/OWNER.json"
    backend = FakeBackend(described={"kind": "fake", "container_name": "repomap-test-postgres-x",
                                     "label": "org.repomap.test.run_id=x", "start_command": ["docker", "run"]})
    backend.on_start = lambda: seen.update(bytes=owner_path.read_bytes(), mode=owner_path.stat().st_mode & 0o777)
    assert _run(context, backend, _late(lambda: None, active=backend.start)) == 0
    owner = json.loads(seen["bytes"])
    assert seen["mode"] == 0o600 and set(owner) == {"schema", "run_id", "runner_pid", "work_root", "evidence_dir",
                                                    "backend", "manual_cleanup", "use"}
    assert owner["backend"] == {"kind": "fake", "container_name": "repomap-test-postgres-x",
                                "label": "org.repomap.test.run_id=x"}
    assert owner["manual_cleanup"] == [backend.manual_cleanup(), f"rm -rf -- {shlex.quote(str(context.work))}"]
    assert backend.password not in seen["bytes"].decode() and owner_path.read_bytes() == seen["bytes"]
    entry = _manifest(context)["members"]["OWNER.json"]
    assert entry["early_file_sha256"] == entry["recorded_sha256"] == hashlib.sha256(seen["bytes"]).hexdigest()


def test_setup_failure_is_redacted_and_cleanup_failure_overrides_success(tmp_path: Path) -> None:
    context = _context(tmp_path)

    def failing(ctx, *args) -> str:
        ctx.evidence.add_secret(SECRET)
        raise RuntimeError(f"password={SECRET} rejected")

    assert _run(context, FakeBackend(), failing) == 1
    with zipfile.ZipFile(context.evidence.run_dir / "evidence.zip") as archive:
        assert not any(SECRET.encode() in archive.read(name) for name in archive.namelist())
        assert "[REDACTED]" in archive.read("native1-run/error.txt").decode()

    other = tmp_path / "second"
    other.mkdir()
    second, backend = _context(other), FakeBackend(cleanup_ok=False)
    assert _run(second, backend, failing) == 3
    manifest = _manifest(second)
    assert manifest["outcome"] == "cleanup_incomplete" and manifest["summary"]["outcome_before_cleanup"] == "failed"
    assert manifest["summary"]["error"] == "RuntimeError: password=[REDACTED] rejected"
    assert "error.txt" in manifest["members"]
    with pytest.raises(ValueError):
        _run(second, backend, failing, "native-qualified")
