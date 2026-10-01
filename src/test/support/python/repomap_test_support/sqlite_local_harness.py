"""Guarded SQLite Local child processes for containerized integration proofs.

Every SQLite Local child (``ops sqlite-init``, ``ops refresh-graph`` and
``mcp serve``) runs through ``sqlite_local_guard.py`` with:

* no PostgreSQL, password or secret environment variables;
* a ``PATH`` whose first entry holds recording shims for PostgreSQL clients,
  Liquibase, container runtimes and service managers;
* socket, forbidden-spawn and psycopg-connect denial recorded in a guard log;
* optionally (``block_psycopg``) no importable PostgreSQL driver at all.

The integration harness itself may still use containers and PostgreSQL for
the independent comparison publication; that is test infrastructure, not
the SQLite path under test.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from runner_coverage_observer import launch_observed_process, popen_observed_process

from repomap_test_support import sqlite_local_guard
from repomap_test_support.cli_in_process import module_process_environment

SHIMS = (
    "psql", "pg_ctl", "pg_dump", "pg_restore", "pg_isready", "initdb", "postgres",
    "liquibase", "docker", "docker-compose", "podman", "nerdctl", "launchctl", "systemctl",
)
_SCRUBBED_MARKERS = ("PASSWORD", "PGPASS", "SECRET", "TOKEN", "REPOMAP_PG", "REPOMAP_STORAGE")
_SCRUBBED_KEYS = frozenset(
    {"PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGSERVICE", "DATABASE_URL", "DOCKER_HOST",
     "REPOMAP_OPS_CONFIG", "REPOMAP_PSQL_COMMAND", "REPOMAP_HOME"}
)
CHILD_DEADLINE_SECONDS = 300
BARRIER_DEADLINE_SECONDS = 240


class LocalHarness:
    """Owns shims, guard log, registry and environment for guarded children."""

    def __init__(self, scratch: Path, *, block_psycopg: bool = False) -> None:
        self.scratch = scratch
        self.block_psycopg = block_psycopg
        self.shims = scratch / "shims"
        self.shim_log = scratch / "shim-invocations.log"
        self.guard_log = scratch / "guard.log"
        self.cwd = scratch / "unrelated-cwd"
        self.user_home = scratch / "user-home"
        for path in (self.shims, self.cwd, self.user_home):
            path.mkdir(parents=True, exist_ok=True)
        self.registry = scratch / "empty-mcp-registry.json"
        self.registry.write_text('{"projects": {}}\n', encoding="utf-8")
        for name in SHIMS:
            shim = self.shims / name
            shim.write_text(f"#!/bin/sh\necho \"{name} $*\" >> '{self.shim_log}'\nexit 97\n", encoding="utf-8")
            shim.chmod(0o700)

    def environment(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        base = module_process_environment()
        env = {
            key: value
            for key, value in base.items()
            if key not in _SCRUBBED_KEYS and not any(marker in key.upper() for marker in _SCRUBBED_MARKERS)
        }
        env.update(
            {
                "HOME": str(self.user_home),
                "PATH": f"{self.shims}:{Path(sys.executable).parent}:/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "REPOMAP_MCP_CONFIG": str(self.registry),
                sqlite_local_guard.GUARD_LOG_ENV: str(self.guard_log),
            }
        )
        if self.block_psycopg:
            env[sqlite_local_guard.BLOCK_PSYCOPG_ENV] = "1"
        env.update(extra or {})
        return env

    def argv(self, *args: str) -> list[str]:
        return [sys.executable, str(Path(sqlite_local_guard.__file__)), *args]

    def run(self, *args: str, input_text: str | None = None,
            extra_env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return launch_observed_process(
            self.argv(*args),
            family="cli_module",
            cwd=self.cwd,
            env=self.environment(extra_env),
            input_text=input_text,
            pid_namespace_relation="shared",
            timeout=CHILD_DEADLINE_SECONDS,
        )

    def start(self, *args: str, extra_env: Mapping[str, str] | None = None) -> subprocess.Popen[str]:
        return popen_observed_process(
            self.argv(*args),
            family="cli_module",
            cwd=self.cwd,
            env=self.environment(extra_env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pid_namespace_relation="shared",
        )

    def cli_json(self, *args: str) -> dict[str, Any]:
        completed = self.run(*args, "--json")
        if completed.returncode != 0:
            raise AssertionError(f"{args} failed: {completed.stderr}")
        payload = json.loads(completed.stdout)
        assert isinstance(payload, dict)
        return payload

    def mcp(self, home: Path, requests: Sequence[dict[str, Any]],
            extra_env: Mapping[str, str] | None = None) -> dict[int, dict[str, Any]]:
        payload = "".join(json.dumps(request) + "\n" for request in requests)
        completed = self.run(
            "mcp", "serve", "--repo-map-home", str(home), input_text=payload, extra_env=extra_env
        )
        if completed.returncode != 0:
            raise AssertionError(f"mcp serve failed: {completed.stderr}")
        responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
        return {int(response["id"]): response for response in responses}

    def guard_events(self) -> list[dict[str, Any]]:
        if not self.guard_log.exists():
            return []
        return [json.loads(line) for line in self.guard_log.read_text(encoding="utf-8").splitlines()]

    def forbidden_events(self) -> list[dict[str, Any]]:
        """Denied or blocked events; a blocked driver import counts as forbidden."""
        return [event for event in self.guard_events() if event["kind"] != "import-info"]

    def imported_modules(self) -> set[str]:
        return {event["detail"] for event in self.guard_events() if event["kind"] == "import-info"}

    def shim_invocations(self) -> str:
        return self.shim_log.read_text(encoding="utf-8") if self.shim_log.exists() else ""

    def ceiling_env(self, version: int) -> dict[str, str]:
        """Run a child as the historical code that knew only the first ``version`` migrations."""
        return {sqlite_local_guard.SCHEMA_CEILING_ENV: str(version)}

    def sync_env(self, log: Path) -> dict[str, str]:
        """Record every directory a child fsyncs into ``log`` (LOCAL9)."""
        return {sqlite_local_guard.SYNC_LOG_ENV: str(log)}

    def paused_env(self, point: str, barrier: Path) -> dict[str, str]:
        barrier.mkdir(parents=True, exist_ok=True)
        return {
            sqlite_local_guard.PAUSE_AT_ENV: point,
            sqlite_local_guard.BARRIER_ENV: str(barrier),
        }


def await_ready(barrier: Path, process: subprocess.Popen[str]) -> None:
    """Wait for a paused writer's ready file; a hang guard, not a timing claim."""
    deadline = time.monotonic() + BARRIER_DEADLINE_SECONDS
    while not (barrier / "ready").exists():
        if process.poll() is not None:
            _, stderr = process.communicate()
            raise AssertionError(f"paused writer exited early: {stderr}")
        if time.monotonic() > deadline:
            process.kill()
            raise AssertionError("paused writer never reached its barrier")
        time.sleep(0.05)


def release(barrier: Path) -> None:
    (barrier / "release").write_text("go", encoding="utf-8")


def tool(message_id: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}


def initialize(message_id: int = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "sqlite-local-proof", "version": "1"}}}


def structured(responses: Mapping[int, dict[str, Any]], message_id: int) -> Any:
    result = responses[message_id]["result"]
    if result.get("isError"):
        raise AssertionError(f"tool call {message_id} failed: {result.get('structuredContent')}")
    return result["structuredContent"]


def refusal(responses: Mapping[int, dict[str, Any]], message_id: int) -> str:
    result = responses[message_id]["result"]
    if result.get("isError") is not True:
        raise AssertionError(f"tool call {message_id} unexpectedly succeeded")
    return str(result["structuredContent"]["error"])


def init_orphans(path: Path) -> list[Path]:
    """Return orphan initialization files (and their sidecars) left for ``path``."""
    if not path.parent.is_dir():
        return []
    return sorted(path.parent.glob(f".{path.name}.init-*"))


def temp_orphans(path: Path) -> list[Path]:
    """Return orphan initialization and restore files (and their sidecars) left for ``path``."""
    if not path.parent.is_dir():
        return []
    return sorted([*path.parent.glob(f".{path.name}.init-*"), *path.parent.glob(f".{path.name}.restore-*")])


def remove_database(path: Path) -> None:
    """Remove one test-owned database with its sidecars, lock and init orphans."""
    for owned in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm"),
                  path.with_name(path.name + ".publish.lock"), *init_orphans(path)):
        owned.unlink(missing_ok=True)


__all__ = (
    "LocalHarness",
    "SHIMS",
    "await_ready",
    "init_orphans",
    "initialize",
    "refusal",
    "release",
    "remove_database",
    "structured",
    "temp_orphans",
    "tool",
)
