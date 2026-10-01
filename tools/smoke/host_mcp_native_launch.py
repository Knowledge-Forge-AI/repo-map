"""Direct launch of the checkout ``repomap-kg`` console script for host MCP proofs.

The acceptance process is the console script itself, started with
``subprocess.Popen`` from an unrelated working directory with an environment
built from scratch. Nothing here wraps, re-implements, or imports the MCP
server; the parent only writes JSON-RPC lines to stdin, closes it (EOF
shutdown), and classifies the stdout lines it reads back.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
from typing import Any

ALLOWED_CHILD_KEYS = ("HOME", "LANG", "PATH", "PYTHONDONTWRITEBYTECODE", "REPOMAP_STORAGE_READBACK_DRIVER", "TMPDIR")
SHIM_COMMANDS = ("docker", "podman", "nerdctl", "docker-compose", "launchctl", "systemctl")
SHIM_EXIT = 97
NATIVE_FORMS = ("absolute-shebang", "sh-exec-trampoline")
MAX_REFUSAL_CHARS = 300
_TRAMPOLINE = re.compile(r"""^'''exec' (?:"([^"]+)"|'([^']+)'|(\S+)) "\$0" "\$@"\s*$""")
_WRAPPER_MARKERS = ("#!/bin/sh", "PYTHONPATH=", "from repomap_kg.cli import main")
_TOPOLOGY_MARKERS = ("docker", "Postgres container")
PROBE_SOURCE = (
    "import json, platform, sys\n"
    "import repomap_kg, psycopg\n"
    "print(json.dumps({'repomap_kg_file': repomap_kg.__file__, 'psycopg': psycopg.__version__,\n"
    "  'python': sys.version.split()[0], 'executable': sys.executable, 'machine': platform.machine(),\n"
    "  'platform': sys.platform}))\n"
)


@dataclass(frozen=True)
class ConsoleEntrypoint:
    path: Path
    sha256: str
    form: str
    shebang_lines: tuple[str, ...]
    interpreter: str | None
    interpreter_realpath: str | None
    targets_cli_main: bool

    def native_refusal(self, checkout: Path) -> str | None:
        """Why this console cannot be the native acceptance process, if it cannot."""
        if self.form not in NATIVE_FORMS:
            return f"console form {self.form!r} is not a checkout console script"
        if not self.targets_cli_main:
            return "console script does not target repomap_kg.cli main"
        if self.interpreter is None or Path(self.interpreter).parent != checkout / ".venv" / "bin":
            return "console interpreter is not lexically inside <checkout>/.venv/bin"
        return None

    def jsonable(self) -> dict[str, Any]:
        return {"path": str(self.path), "sha256": self.sha256, "form": self.form,
                "shebang_lines": list(self.shebang_lines), "interpreter": self.interpreter,
                "interpreter_realpath": self.interpreter_realpath, "targets_cli_main": self.targets_cli_main}


def console_entrypoint(path: Path) -> ConsoleEntrypoint:
    """Classify an installed console script by content; never execute it."""
    data = path.read_bytes()
    text = data[:8192].decode("utf-8", errors="replace")
    lines = text.splitlines()
    interpreter: str | None = None
    form = "unsupported"
    if all(marker in text for marker in _WRAPPER_MARKERS):
        form = "runner-provisioned-wrapper"
    elif lines and lines[0].startswith("#!/bin/sh") and len(lines) > 1 and _TRAMPOLINE.match(lines[1]):
        match = _TRAMPOLINE.match(lines[1])
        assert match is not None
        form, interpreter = "sh-exec-trampoline", next(group for group in match.groups() if group)
    elif lines and lines[0].startswith("#!/") and "python" in lines[0].split()[0]:
        form, interpreter = "absolute-shebang", lines[0][2:].split()[0]
    realpath = os.path.realpath(interpreter) if interpreter else None
    targets = "from repomap_kg.cli import main" in text and "main()" in text
    return ConsoleEntrypoint(path=path, sha256=hashlib.sha256(data).hexdigest(), form=form,
                             shebang_lines=tuple(lines[:2]), interpreter=interpreter,
                             interpreter_realpath=realpath, targets_cli_main=targets)


@dataclass(frozen=True)
class ChildLayout:
    """Run-owned directories for the MCP child; ``cwd`` deliberately contains a space."""

    root: Path

    @property
    def cwd(self) -> Path:
        return self.root / "unrelated cwd"

    @property
    def user_home(self) -> Path:
        return self.root / "user-home"

    @property
    def tmp(self) -> Path:
        return self.root / "child-tmp"

    @property
    def shims(self) -> Path:
        return self.root / "shims"

    @property
    def shim_log(self) -> Path:
        return self.root / "shim-invocations.log"

    def create(self) -> ChildLayout:
        for directory in (self.cwd, self.user_home, self.tmp, self.shims):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in SHIM_COMMANDS:
            shim = self.shims / name
            shim.write_text(f"#!/bin/sh\necho \"{name} $*\" >> '{self.shim_log}'\nexit {SHIM_EXIT}\n",
                            encoding="utf-8")
            shim.chmod(0o700)
        return self

    def shim_invocations(self) -> str:
        return self.shim_log.read_text(encoding="utf-8") if self.shim_log.exists() else ""


def child_environment(layout: ChildLayout, platform: str, *,
                      test_extra_path: Sequence[str] = ()) -> dict[str, str]:
    """The complete exec environment; nothing is inherited from the parent.

    ``test_extra_path`` exists only for the Linux harness seam, whose
    provisioned wrapper runs ``exec python3`` from ``PATH``. It is not
    reachable from the operator command line.
    """
    path = ":".join((str(layout.shims), *test_extra_path, "/usr/bin", "/bin"))
    return {
        "HOME": str(layout.user_home),
        "LANG": "en_US.UTF-8" if platform == "darwin" else "C.UTF-8",
        "PATH": path,
        "PYTHONDONTWRITEBYTECODE": "1",
        "REPOMAP_STORAGE_READBACK_DRIVER": "psycopg",
        "TMPDIR": str(layout.tmp),
    }


def import_probe(interpreter: str, layout: ChildLayout, env: Mapping[str, str], *,
                 runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> dict[str, Any]:
    """Prerequisite probe with the child environment; never the acceptance process."""
    argv = [interpreter, "-c", PROBE_SOURCE]
    record: dict[str, Any] = {"argv": [interpreter, "-c", "<probe>"], "cwd": str(layout.cwd),
                              "role": "prerequisite-probe-not-acceptance"}
    try:
        completed = runner(argv, cwd=layout.cwd, env=dict(env), stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return {**record, "ok": False, "error": f"{type(error).__name__}: {error}"}
    record.update(exit=completed.returncode, stderr=completed.stderr[-2000:])
    try:
        record["result"] = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {**record, "ok": False, "error": "probe produced no JSON result"}
    return {**record, "ok": completed.returncode == 0}


@dataclass
class SessionRecord:
    label: str
    argv: tuple[str, ...]
    cwd: str
    env: dict[str, str]
    pid: int | None = None
    returncode: int | None = None
    deadline_exceeded: bool = False
    responses: dict[int, dict[str, Any]] = field(default_factory=dict)
    unidentified: list[dict[str, Any]] = field(default_factory=list)
    malformed_lines: list[str] = field(default_factory=list)
    stderr: str = ""
    requests: list[dict[str, Any]] = field(default_factory=list)

    def jsonable(self) -> dict[str, Any]:
        return {"label": self.label, "argv": list(self.argv), "cwd": self.cwd, "exec_env": self.env,
                "exec_env_keys": sorted(self.env), "pid": self.pid, "exit": self.returncode,
                "deadline_exceeded": self.deadline_exceeded, "requests": self.requests,
                "responses": {str(key): value for key, value in sorted(self.responses.items())},
                "unidentified_responses": self.unidentified, "malformed_lines": self.malformed_lines,
                "stderr_tail": self.stderr[-4000:]}


class ChildTracker:
    """The one live MCP child, so interruption cleanup can reap it."""

    def __init__(self) -> None:
        self.live: subprocess.Popen[str] | None = None
        self.launched: list[int] = []

    def reap(self) -> dict[str, Any]:
        process, self.live = self.live, None
        if process is None:
            return {"step": "reap-child", "ok": True, "detail": "no live child"}
        return {"step": "reap-child", "ok": terminate_group(process), "pid": process.pid}


def terminate_group(process: subprocess.Popen[str]) -> bool:
    """Stop only this child's own process group (``start_new_session``), then reap it."""
    if process.poll() is None:
        for sig, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 10)):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=grace)
                break
            except subprocess.TimeoutExpired:
                continue
    return process.poll() is not None


def run_session(label: str, console: Path, home: Path, layout: ChildLayout, env: Mapping[str, str],
                requests: Sequence[dict[str, Any]], *, deadline: float = 120,
                tracker: ChildTracker | None = None) -> SessionRecord:
    """One real ``repomap-kg mcp serve`` process: write all requests, close stdin, read to EOF."""
    argv = (str(console), "mcp", "serve", "--repo-map-home", str(home))
    record = SessionRecord(label=label, argv=argv, cwd=str(layout.cwd), env=dict(env), requests=list(requests))
    tracker = tracker or ChildTracker()
    process = subprocess.Popen(list(argv), cwd=layout.cwd, env=dict(env), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               start_new_session=True, close_fds=True)
    tracker.live, record.pid = process, process.pid
    tracker.launched.append(process.pid)
    payload = "".join(json.dumps(request) + "\n" for request in requests)
    try:
        stdout, stderr = process.communicate(payload, timeout=deadline)
    except subprocess.TimeoutExpired:
        record.deadline_exceeded = True
        terminate_group(process)
        stdout, stderr = process.communicate()
    finally:
        if process.poll() is None:
            terminate_group(process)
        tracker.live = None
    record.returncode, record.stderr = process.returncode, stderr or ""
    for line in (stdout or "").splitlines():
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            record.malformed_lines.append(line[:500])
            continue
        if isinstance(message, dict) and isinstance(message.get("id"), int):
            record.responses[message["id"]] = message
        else:
            record.unidentified.append(message if isinstance(message, dict) else {"value": message})
    return record


@dataclass(frozen=True)
class Expectation:
    """``positive`` compares a projection with an oracle; refusals compare text."""

    kind: str  # positive | refusal | bounded_refusal | protocol
    expected: Any = None
    project: Callable[[Any], Any] | None = None
    nonempty: Callable[[Any], bool] | None = None


def classify_session(record: SessionRecord, expectations: Mapping[int, Expectation]) -> dict[str, Any]:
    """Classify every expected message plus session-level failures; never raises."""
    messages: dict[str, str] = {}
    for mid, expectation in expectations.items():
        messages[str(mid)] = _classify(record.responses.get(mid), expectation)
    session: list[str] = []
    if record.returncode != 0:
        session.append("child_failed")
    if record.deadline_exceeded:
        session.append("deadline_exceeded")
    if record.malformed_lines:
        session.append("malformed_line")
    if set(record.responses) - set(expectations) or record.unidentified:
        session.append("unexpected_response")
    good = {"positive_ok", "expected_refusal_ok", "protocol_ok"}
    return {"session": session, "messages": messages,
            "ok": not session and all(status in good for status in messages.values())}


def _classify(response: dict[str, Any] | None, expectation: Expectation) -> str:
    if response is None:
        return "missing_response"
    if "error" in response:
        return "jsonrpc_error"
    result = response.get("result")
    if not isinstance(result, dict):
        return "malformed_result"
    if expectation.kind == "protocol":
        return "protocol_ok" if _matches(result, expectation) else "mismatch"
    refused = result.get("isError") is True
    if expectation.kind == "positive":
        if refused:
            return "unexpected_refusal"
        payload = result.get("structuredContent")
        if expectation.nonempty is not None and not expectation.nonempty(payload):
            return "empty_positive"
        return "positive_ok" if _matches(payload, expectation) else "mismatch"
    if not refused:
        return "unexpected_success"
    text = str((result.get("structuredContent") or {}).get("error", ""))
    if expectation.kind == "refusal":
        return "expected_refusal_ok" if text == expectation.expected else "mismatch"
    bounded = 0 < len(text) <= MAX_REFUSAL_CHARS and not any(mark in text for mark in _TOPOLOGY_MARKERS)
    return "expected_refusal_ok" if bounded else "unbounded_refusal"


def _matches(payload: Any, expectation: Expectation) -> bool:
    project = expectation.project or (lambda value: value)
    try:
        return json.loads(json.dumps(project(payload), sort_keys=True)) == expectation.expected
    except (KeyError, TypeError, IndexError, AttributeError):
        return False
