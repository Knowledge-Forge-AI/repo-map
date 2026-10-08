"""Host-native RepoMap MCP stdio sessions for integration proofs.

The child is the ``repomap-kg`` console script installed next to the runner
interpreter (a checkout venv), or else the runner-provisioned ``repomap-kg`` on
the runner ``PATH`` (the test sandbox wrapper). It starts with a from-scratch
environment: no inherited ``PYTHONPATH``, ``VIRTUAL_ENV``, or database
password, and a ``PATH`` whose first entry holds recording shims for container
and service managers.

Environment evidence is taken at the observer's final-exec seam: the mapping
``Popen`` receives for the launched executable, after coverage preparation.
When that executable is the runner-provisioned wrapper, the wrapper itself then
adds ``PYTHONPATH`` (workspace ``tools``, main and test-support roots) before it
execs ``python3``. Observed keys therefore prove what the harness injected into
the launched executable, not the final Python child's environment.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any

from runner_coverage_observer import launch_observed_process

SHIM_COMMANDS = ("docker", "podman", "nerdctl", "docker-compose", "launchctl", "systemctl")
SESSION_DEADLINE_SECONDS = 60
FORBIDDEN_ENV_MARKERS = ("PASSWORD", "PGPASS", "SECRET", "TOKEN", "VIRTUAL_ENV", "PYTHONPATH")
_SHIM_EXIT = 97
_WRAPPER_MARKERS = ("#!/bin/sh", "PYTHONPATH=", "from repomap_kg.cli import main")


def forbidden_env_keys(keys: Sequence[str]) -> tuple[str, ...]:
    """Key names (never values) that must not reach the MCP child."""
    return tuple(key for key in keys if any(marker in key.upper() for marker in FORBIDDEN_ENV_MARKERS))


def launch_mode(script: Path) -> tuple[str, str]:
    """Classify the launched executable by content and return its SHA-256."""
    data = script.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    text = data[:4096].decode("utf-8", errors="replace")
    if all(marker in text for marker in _WRAPPER_MARKERS):
        return "runner-provisioned-wrapper", digest
    if script.parent == Path(sys.executable).parent and text.startswith("#!"):
        return "checkout-venv-console-script", digest
    return "unclassified", digest


class _RecordingObserver:
    """Record the final-exec argv and environment key names, then delegate."""

    def __init__(self) -> None:
        self.launches: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
        self._delegate = _coverage_observer()

    def observe_launch(self, **kwargs: Any) -> Any:
        env = kwargs.get("env") or {}
        self.launches.append((tuple(kwargs.get("argv") or ()), tuple(sorted(env))))
        if self._delegate is not None:
            return self._delegate.observe_launch(**kwargs)
        return None


def _coverage_observer() -> Any:
    manifest = os.environ.get("COVERAGE_CHILD_MANIFEST_DIR")
    invocation = os.environ.get("COVERAGE_SESSION_INVOCATION_ID")
    if not (manifest and invocation):
        return None
    from runner_coverage_observer import ProcessObserver

    return ProcessObserver(observation_dir=Path(manifest).parent / "observations", invocation_id=invocation)


@dataclass(frozen=True)
class HostMcpSession:
    argv: tuple[str, ...]
    observed_env_keys: tuple[str, ...]
    launch_mode: str
    launch_sha256: str
    returncode: int
    responses: tuple[dict[str, Any], ...]
    stderr: str

    def result(self, message_id: int) -> dict[str, Any]:
        for response in self.responses:
            if response.get("id") == message_id:
                result = response.get("result")
                if not isinstance(result, dict):
                    raise AssertionError(f"response {message_id} has no result object")
                return result
        raise AssertionError(f"response {message_id} is missing")

    def structured(self, message_id: int) -> Any:
        result = self.result(message_id)
        if result.get("isError"):
            raise AssertionError(f"tool call {message_id} failed: {result.get('content')}")
        return result["structuredContent"]

    def refusal(self, message_id: int) -> str:
        result = self.result(message_id)
        if result.get("isError") is not True:
            raise AssertionError(f"tool call {message_id} unexpectedly succeeded")
        return str(result["structuredContent"]["error"])


class HostMcpHarness:
    """Build shims, environment, and requests for one host MCP child."""

    def __init__(self, scratch: Path, home: Path) -> None:
        self.home = home
        self.cwd = scratch / "unrelated-cwd"
        self.user_home = scratch / "user-home"
        self.shims = scratch / "shims"
        self.marker = scratch / "shim-invocations.log"
        registry = scratch / "empty-mcp-registry.json"
        for path in (self.cwd, self.user_home, self.shims):
            path.mkdir(parents=True, exist_ok=True)
        registry.write_text('{"projects": {}}\n', encoding="utf-8")
        self.registry = registry
        for name in SHIM_COMMANDS:
            shim = self.shims / name
            shim.write_text(
                f"#!/bin/sh\necho \"{name} $*\" >> '{self.marker}'\nexit {_SHIM_EXIT}\n",
                encoding="utf-8",
            )
            shim.chmod(0o700)

    @property
    def console_script(self) -> Path:
        script = Path(sys.executable).with_name("repomap-kg")
        if script.is_file():
            return script
        provisioned = shutil.which("repomap-kg")
        if provisioned is None:
            raise AssertionError(f"repomap-kg console script is missing: {script}")
        return Path(provisioned)

    def environment(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        env = {
            "HOME": str(self.user_home),
            "PATH": f"{self.shims}:{Path(sys.executable).parent}:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "REPOMAP_MCP_CONFIG": str(self.registry),
        }
        env.update(extra or {})
        return env

    def shim_invocations(self) -> str:
        return self.marker.read_text(encoding="utf-8") if self.marker.exists() else ""

    def run(
        self,
        requests: Sequence[dict[str, Any]],
        *,
        home: Path | None = None,
        extra_env: Mapping[str, str] | None = None,
    ) -> HostMcpSession:
        argv = (str(self.console_script), "mcp", "serve", "--repo-map-home", str(home or self.home))
        env = self.environment(extra_env)
        payload = "".join(json.dumps(request) + "\n" for request in requests)
        observer = _RecordingObserver()
        completed = launch_observed_process(
            list(argv),
            family="cli_module",
            cwd=self.cwd,
            env=env,
            input_text=payload,
            pid_namespace_relation="shared",
            timeout=SESSION_DEADLINE_SECONDS,
            observer=observer,
        )
        responses = tuple(
            json.loads(line) for line in completed.stdout.splitlines() if line.strip()
        )
        if len(observer.launches) != 1 or observer.launches[0][0] != argv:
            raise AssertionError("observer did not record exactly the launched argv")
        mode, digest = launch_mode(Path(argv[0]))
        return HostMcpSession(
            argv=argv,
            observed_env_keys=observer.launches[0][1],
            launch_mode=mode,
            launch_sha256=digest,
            returncode=completed.returncode,
            responses=responses,
            stderr=completed.stderr,
        )


def initialize_request(message_id: int = 1) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0", "id": message_id, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "host-native-proof", "version": "1"},
        },
    }


def tools_list_request(message_id: int) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "method": "tools/list", "params": {}}


def tool_request(message_id: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0", "id": message_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
