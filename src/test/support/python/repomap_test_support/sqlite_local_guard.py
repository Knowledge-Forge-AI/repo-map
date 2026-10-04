"""Test-owned launcher that runs the RepoMap CLI with PostgreSQL paths denied.

Executed by path as a child process (``python sqlite_local_guard.py <cli args>``)
before ``repomap_kg`` is imported. It records and denies, through a
``sys.addaudithook`` hook and a psycopg import finder:

* every ``socket.connect`` (TCP, IPv6 and Unix sockets, including
  ``.s.PGSQL.*`` and container daemon sockets);
* every spawn of a PostgreSQL client or server tool, Liquibase, a container
  runtime or a service manager;
* every ``psycopg`` connection attempt (libpq sockets are not audited, so the
  connect entry points themselves are replaced after import).

Whether ``psycopg`` was imported at all is recorded as information only,
unless ``REPOMAP_TEST_SQLITE_BLOCK_PSYCOPG=1`` makes the whole driver family
unavailable: then every attempt raises ``ModuleNotFoundError`` and is recorded
as ``import-blocked`` (no stand-in module is ever provided). An
optional test-owned pause at a named publisher, initialization, backup,
restore or upgrade fault point
writes a ``ready`` file and waits for a ``release`` file (hang-guarded), so
tests can kill, interrupt or contend with a writer at an exact point without
timing thresholds. A paused child restores the default SIGINT handler.
``REPOMAP_TEST_SQLITE_SCHEMA_CEILING=<n>`` truncates the migration catalog to
its first ``n`` historical migrations before the CLI is imported, so a child
creates, reads and publishes a genuine older-schema database from the
preserved historical SQL bytes (LOCAL8).
``REPOMAP_TEST_SQLITE_SYNC_LOG=<file>`` appends every directory the child
fsynced through ``durability.fsync_directory`` (after it succeeded) to that
file, one resolved path per line (LOCAL9); it is not a guard event.
This file is test harness code; production has no environment-driven seam.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import json
import os
import signal
import socket
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

GUARD_LOG_ENV = "REPOMAP_TEST_SQLITE_GUARD_LOG"
PAUSE_AT_ENV = "REPOMAP_TEST_SQLITE_PAUSE_AT"
BARRIER_ENV = "REPOMAP_TEST_SQLITE_BARRIER"
ABRUPT_SETTLEMENT_ENV = "REPOMAP_TEST_SQLITE_ABRUPT_SETTLEMENT"
SCHEMA_CEILING_ENV = "REPOMAP_TEST_SQLITE_SCHEMA_CEILING"
SYNC_LOG_ENV = "REPOMAP_TEST_SQLITE_SYNC_LOG"
PAUSE_DEADLINE_SECONDS = 300
FORBIDDEN_EXECUTABLES = frozenset(
    {
        "psql", "postgres", "initdb", "liquibase", "docker", "docker-compose", "podman",
        "nerdctl", "launchctl", "systemctl", "orb", "orbctl", "colima", "lima",
    }
)


class GuardDenied(PermissionError):
    """Raised inside a guarded child when a forbidden path is attempted."""


def _record(kind: str, detail: str) -> None:
    line = json.dumps({"pid": os.getpid(), "kind": kind, "detail": detail}, sort_keys=True)
    with open(os.environ[GUARD_LOG_ENV], "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _forbidden(name: str) -> bool:
    base = os.path.basename(name)
    return base in FORBIDDEN_EXECUTABLES or base.startswith("pg_")


_imported: set[str] = set()


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if event == "socket.connect":
        family = getattr(args[0], "family", None)
        _record("socket.connect", str(getattr(family, "name", family)))
        raise GuardDenied("guard: socket connections are denied in SQLite Local children")
    if event in {"subprocess.Popen", "os.posix_spawn", "os.exec", "os.spawn"}:
        executable = args[0]
        argv = args[1] if len(args) > 1 else None
        name = str(executable or (argv[0] if argv else ""))
        if isinstance(executable, bytes):
            name = executable.decode(errors="replace")
        if _forbidden(name):
            _record(event, os.path.basename(name))
            raise GuardDenied(f"guard: {os.path.basename(name)} is denied")
    elif event == "os.system":
        command = str(args[0]).split()
        if command and _forbidden(command[0]):
            _record(event, os.path.basename(command[0]))
            raise GuardDenied("guard: shell command denied")
    elif event == "import" and args[0] in INFO_IMPORTS and args[0] not in _imported:
        _imported.add(args[0])
        _record("import-info", str(args[0]))


def _deny_connect(*_args: object, **_kwargs: object) -> None:
    _record("psycopg.connect", "denied")
    raise GuardDenied("guard: psycopg connections are denied in SQLite Local children")


class _PsycopgGuard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
        if fullname != "psycopg":
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return spec
        loader = spec.loader
        original = loader.exec_module

        def exec_module(module: ModuleType) -> None:
            original(module)
            setattr(module, "connect", _deny_connect)
            for name in ("Connection", "AsyncConnection"):
                cls = getattr(module, name, None)
                if cls is not None:
                    cls.connect = classmethod(lambda _cls, *a, **k: _deny_connect())

        setattr(loader, "exec_module", exec_module)
        return spec


# Opt-in driver absence for import-independence proofs (LOCAL6).
BLOCK_PSYCOPG_ENV = "REPOMAP_TEST_SQLITE_BLOCK_PSYCOPG"
BLOCKED_DRIVER_ROOTS = frozenset({"psycopg", "psycopg2", "psycopg_binary", "psycopg_c", "psycopg_pool"})
# Recorded as ``import-info`` only: the driver and the PostgreSQL-implementation
# modules whose absence proves an early, side-effect-free route.
INFO_IMPORTS = frozenset(
    {
        "psycopg",
        "psycopg2",
        "repomap_kg.coordinator.client",
        "repomap_kg.coordinator.local_lifecycle",
        "repomap_kg.coordinator.local_mode",
        "repomap_kg.ops.refresh",
        "repomap_kg.runtime.maintenance",
        "repomap_kg.runtime.release_cluster",
        "repomap_kg.service_package.api",
        "repomap_kg.storage.staged_ingestion",
    }
)


class _PsycopgBlocker(importlib.abc.MetaPathFinder):
    """Makes the PostgreSQL driver family genuinely unavailable; nothing is faked."""

    def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
        if fullname.split(".", 1)[0] not in BLOCKED_DRIVER_ROOTS:
            return None
        _record("import-blocked", fullname)
        raise ModuleNotFoundError(f"No module named {fullname!r} (test blocker)", name=fullname)


def _install_psycopg_blocker() -> None:
    loaded = sorted(name for name in sys.modules if name.split(".", 1)[0] in BLOCKED_DRIVER_ROOTS)
    if loaded:
        raise RuntimeError(f"psycopg blocker installed after an import: {loaded}")
    sys.meta_path.insert(0, _PsycopgBlocker())


def _install_pause() -> None:
    point = os.environ.get(PAUSE_AT_ENV)
    if not point:
        return
    barrier = Path(os.environ[BARRIER_ENV])
    from repomap_kg.storage.sqlite_local import backup, connection, publisher, restore, upgrade

    # A paused child must turn SIGINT into KeyboardInterrupt even when it
    # inherited an ignored SIGINT disposition from its launcher.
    signal.signal(signal.SIGINT, signal.default_int_handler)

    def pause(name: str) -> None:
        if name != point:
            return
        is_abrupt = os.environ.get(ABRUPT_SETTLEMENT_ENV) == "1"
        if is_abrupt:
            coverage_armed = bool(
                os.environ.get("COVERAGE_PROCESS_START")
                or os.environ.get("COVERAGE_CHILD_MANIFEST_DIR")
            )
            sc = sys.modules.get("sitecustomize")
            if coverage_armed:
                if not sc or not hasattr(sc, "_settle_terminal_receipt"):
                    err_msg = "guard: abrupt terminal settlement hook missing or renamed while coverage is armed"
                    (barrier / "settlement_error").write_text(f"RuntimeError: {err_msg}\n", encoding="utf-8")
                    raise RuntimeError(err_msg)
                try:
                    sc._settle_terminal_receipt()
                except Exception as error:
                    (barrier / "settlement_error").write_text(f"{type(error).__name__}: {error}\n", encoding="utf-8")
                    raise RuntimeError(f"abrupt terminal settlement failed: {error}") from error
            elif sc and hasattr(sc, "_settle_terminal_receipt"):
                try:
                    sc._settle_terminal_receipt()
                except Exception as error:
                    (barrier / "settlement_error").write_text(f"{type(error).__name__}: {error}\n", encoding="utf-8")
                    raise RuntimeError(f"abrupt terminal settlement failed: {error}") from error
        (barrier / "ready").write_text(str(os.getpid()), encoding="utf-8")
        deadline = time.monotonic() + PAUSE_DEADLINE_SECONDS
        while not (barrier / "release").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("guard pause was never released")
            time.sleep(0.05)
        if is_abrupt:
            sc = sys.modules.get("sitecustomize")
            if sc and hasattr(sc, "_invalidate_terminal_receipt"):
                sc._invalidate_terminal_receipt()
            raise RuntimeError("guard: abrupt termination child was released instead of killed")

    publisher._fault_point = pause
    connection._fault_point = pause
    backup._fault_point = pause
    restore._fault_point = pause
    upgrade._fault_point = pause


def _install_schema_ceiling() -> None:
    ceiling = os.environ.get(SCHEMA_CEILING_ENV)
    if not ceiling:
        return
    from repomap_kg.storage.sqlite_local import migrations

    count = int(ceiling)
    if not 1 <= count <= len(migrations.MIGRATIONS):
        raise RuntimeError(f"schema ceiling outside the catalog: {count}")
    migrations.MIGRATIONS = migrations.MIGRATIONS[:count]


def _install_sync_log() -> None:
    log = os.environ.get(SYNC_LOG_ENV)
    if not log:
        return
    from repomap_kg.storage.sqlite_local import durability

    synced = durability.fsync_directory

    def recorded(path: Path) -> None:
        synced(path)
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(f"{path}\n")

    durability.fsync_directory = recorded


def main(argv: list[str]) -> int:
    sys.addaudithook(_audit)
    sys.meta_path.insert(0, _PsycopgGuard())
    if os.environ.get(BLOCK_PSYCOPG_ENV) == "1":
        # Ahead of the connect guard and of every repomap import below.
        _install_psycopg_blocker()
    socket.setdefaulttimeout(1.0)
    _install_pause()
    _install_schema_ceiling()
    _install_sync_log()
    from repomap_kg.cli.main import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
