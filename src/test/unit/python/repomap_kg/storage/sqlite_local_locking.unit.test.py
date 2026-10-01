"""SQLite Local graph lock owner (LOCAL10): dispatch, import neutrality and POSIX.

Backend selection, the ``fcntl`` canary import blocker and the source census
are deterministic contract tests; the Windows algorithm's contract tests live
in ``storage/sqlite_local_locking_windows`` and neither is native Windows
evidence. The POSIX cases use the real ``flock`` backend, in-process and across
real child processes synchronized by pipes. Mutation consumers are owned by
``ops/sqlite_local_lock_consumers``.
"""

from __future__ import annotations

import ast
import errno
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from repomap_kg.storage.sqlite_local import locking
from repomap_kg.storage.sqlite_local.locking import (
    LOCKING_UNAVAILABLE,
    _backend_for,
    _PosixBackend,
    _WindowsBackend,
    hold_graph_lock,
    lock_path,
    probe_graph_lock,
)
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
from repomap_test_support.cli_in_process import module_process_environment
from repomap_test_support.sqlite_local_lock_children import (
    HOLD_AND_SPAWN,
    attempt,
    release_holder,
    start_holder,
)

IN_PROGRESS = "graph-publication-in-progress"
NOT_PRIVATE = "graph-database-unavailable: graph lock file is not private"
PACKAGE = Path(locking.__file__).parents[2]  # src/main/python/repomap_kg


def _code(caught: pytest.ExceptionInfo[LocalStoreError]) -> str:
    return str(caught.value)


def _store(tmp_path: Path) -> Path:
    store = tmp_path / "graphs"
    store.mkdir(mode=0o700)
    return store


def _opened(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    """Record every ``(flags, descriptor)`` the owner opens."""
    opened: list[tuple[int, int]] = []
    original = os.open

    def spy(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        descriptor = original(path, flags, *args, **kwargs)
        opened.append((flags, descriptor))
        return descriptor

    monkeypatch.setattr(os, "open", spy)
    return opened


def _closed(descriptor: int) -> bool:
    try:
        os.fstat(descriptor)
    except OSError as error:
        return error.errno == errno.EBADF
    return False


# (a) dispatch


def test_dispatch_selects_the_backend_by_os_name_only() -> None:
    assert isinstance(_backend_for("posix"), _PosixBackend)
    fake = ModuleType("msvcrt")
    setattr(fake, "locking", None)
    assert isinstance(_backend_for("nt", load={"msvcrt": fake}.__getitem__), _WindowsBackend)


@pytest.mark.parametrize(
    ("os_name", "load"),
    [
        ("java", None),
        ("riscos", None),
        ("nt", None),  # the real msvcrt is not importable here
        ("posix", lambda name: SimpleNamespace()),  # no flock
        ("nt", lambda name: SimpleNamespace()),  # no locking
    ],
)
def test_unsupported_or_incomplete_platforms_refuse_closed(os_name: str, load: Any) -> None:
    with pytest.raises(LocalStoreError) as caught:
        _backend_for(os_name) if load is None else _backend_for(os_name, load=load)
    assert caught.value.code == LOCKING_UNAVAILABLE


def test_no_environment_value_selects_a_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in (("OS", "Windows_NT"), ("REPOMAP_LOCK_BACKEND", "nt"), ("REPOMAP_STORAGE", "windows")):
        monkeypatch.setenv(key, value)
    assert isinstance(_backend_for(os.name), _PosixBackend)
    tree = ast.parse(Path(locking.__file__).read_text(encoding="utf-8"))
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not {"environ", "getenv", "environb"} & names


# (b) canary import blocker

CANARY = r"""
import errno, importlib, importlib.abc, json, os, sys
from pathlib import Path
sys.modules.pop("fcntl", None)  # a startup hook may have loaded it; every later import is observed
attempts = []
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name == "fcntl":
            frame = sys._getframe(1)
            while frame is not None and frame.f_globals.get("__name__", "").startswith(("importlib", "_frozen")):
                frame = frame.f_back
            attempts.append(None if frame is None else frame.f_globals.get("__name__"))
            raise ImportError("fcntl blocked by the LOCAL10 canary")
sys.meta_path.insert(0, Blocker())
package = Path(sys.argv[1]) / "storage" / "sqlite_local"
stage = {}
for module in sorted(p.stem for p in package.glob("*.py") if p.stem != "__init__"):
    importlib.import_module(f"repomap_kg.storage.sqlite_local.{module}")
stage["sqlite_local"] = list(attempts)
for module in ("ops.local_state_layout", "ops.local_backup", "ops.local_cleanup", "ops.local_refresh",
               "ops.local_refresh_enabled", "cli._ops_sqlite_dispatch"):
    importlib.import_module(f"repomap_kg.{module}")
stage["entries"] = list(attempts)
from repomap_kg.storage.sqlite_local import locking
class Fake:
    LK_UNLCK, LK_NBLCK = 0, 2
    held = set()
    def locking(self, fd, mode, nbytes):
        key = os.fstat(fd).st_ino
        if mode == self.LK_NBLCK:
            if key in self.held: raise OSError(errno.EACCES, "locked")
            self.held.add(key)
        else:
            self.held.discard(key)
before = len(attempts)
backend = locking._backend_for("nt", load=lambda name: Fake())
path = Path(sys.argv[2]) / "g.sqlite3.publish.lock"
outcomes = []
with locking._locked(path, backend, create=False) as held:
    outcomes.append(held)
with locking._locked(path, backend, create=True):
    try:
        with locking._locked(path, backend, create=False):
            outcomes.append("probe-acquired")
    except locking.LocalStoreError as error:
        outcomes.append(error.code)
with locking._locked(path, backend, create=False) as held:
    outcomes.append(held)
try:
    locking._backend_for("nt")
except locking.LocalStoreError as error:
    outcomes.append(error.code)
stage["windows"] = attempts[before:]
print(json.dumps({"stages": stage, "outcomes": outcomes}))
"""


def test_canary_local_closure_never_imports_fcntl(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-c", CANARY, str(PACKAGE), str(tmp_path)],
        capture_output=True, text=True, env=module_process_environment(), check=False, timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    stages = report["stages"]
    # Guarded stdlib importers (subprocess) may try fcntl; no repomap_kg module in the package may.
    assert not [name for name in stages["sqlite_local"] if str(name).startswith("repomap_kg")], stages
    # The entry closure imports successfully with fcntl blocked. Only the guarded
    # non-Local try/except importers (disclosed deviation D3) may attempt it.
    guarded = {"repomap_kg.coordinator.endpoint", "repomap_kg.coordinator._portable_authority",
               "repomap_kg.service_package._artifacts_locking"}
    assert {name for name in stages["entries"] if str(name).startswith("repomap_kg")} <= guarded, stages
    assert stages["windows"] == [], stages
    assert report["outcomes"] == [False, IN_PROGRESS, True, LOCKING_UNAVAILABLE], report


# (d) POSIX backend in process


def test_posix_nested_refusal_and_no_write(tmp_path: Path) -> None:
    database = _store(tmp_path) / "g.sqlite3"
    lock_path(database).write_bytes(b"previous")
    os.utime(lock_path(database), ns=(1_000_000_000, 1_000_000_000))
    with hold_graph_lock(database):
        for owner in (hold_graph_lock, probe_graph_lock):
            with pytest.raises(LocalStoreError) as caught, owner(database):
                pass
            assert _code(caught) == IN_PROGRESS
    assert lock_path(database).read_bytes() == b"previous"
    assert lock_path(database).stat().st_mtime_ns == 1_000_000_000


def test_posix_mutation_tightens_mode_and_probe_changes_nothing(tmp_path: Path) -> None:
    database = _store(tmp_path) / "g.sqlite3"
    lock = lock_path(database)
    with probe_graph_lock(database) as held:
        assert held is False
    assert not lock.exists()
    lock.write_bytes(b"")
    lock.chmod(0o644)
    with probe_graph_lock(database) as held:
        assert held is True
    assert lock.stat().st_mode & 0o777 == 0o644
    with hold_graph_lock(database):
        pass
    assert lock.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("kind", ("symlink", "fifo", "two-links", "directory", "foreign-uid"))
@pytest.mark.parametrize("owner", (hold_graph_lock, probe_graph_lock))
def test_posix_unsafe_lock_paths_refuse_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, owner: Any
) -> None:
    store = _store(tmp_path)
    database = store / "g.sqlite3"
    lock = lock_path(database)
    other = store / "other"
    other.write_bytes(b"")
    if kind == "symlink":
        lock.symlink_to(other)
    elif kind == "fifo":
        os.mkfifo(lock, 0o600)
    elif kind == "two-links":
        os.link(other, lock)
    elif kind == "directory":
        lock.mkdir()
    else:
        lock.write_bytes(b"")
        uid = os.getuid()
        monkeypatch.setattr(os, "getuid", lambda: uid + 1)
    opened = _opened(monkeypatch)
    with pytest.raises(LocalStoreError) as caught, owner(database):
        pass
    assert _code(caught) == NOT_PRIVATE and str(tmp_path) not in _code(caught)
    assert all(_closed(descriptor) for _, descriptor in opened)


# (f) census


def _fcntl_imports(path: Path) -> list[tuple[int, bool]]:
    """``(line, inside a function)`` for every ``fcntl`` import in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    local = {
        id(node)
        for function in ast.walk(tree)
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(function)
    }
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        if "fcntl" in names:
            found.append((node.lineno, id(node) in local))
    return found


def test_census_no_local_production_module_imports_fcntl() -> None:
    local = [*(PACKAGE / "storage" / "sqlite_local").glob("*.py"), *(PACKAGE / "ops").glob("local_*.py")]
    assert len(local) > 20, local
    assert {str(path.relative_to(PACKAGE)): _fcntl_imports(path) for path in local if _fcntl_imports(path)} == {}
    # The POSIX backend receives fcntl by name through importlib, lazily.
    assert '"fcntl"' in Path(locking.__file__).read_text(encoding="utf-8")
    telemetry = _fcntl_imports(PACKAGE / "storage" / "backend_telemetry_events.py")
    assert telemetry and all(inside for _, inside in telemetry), telemetry


# (e) real POSIX processes


def test_posix_lock_is_interprocess_and_released_by_exit_kill_and_not_inherited(tmp_path: Path) -> None:
    env = module_process_environment()
    store = _store(tmp_path)
    one, two = store / "one.sqlite3", store / "two.sqlite3"

    holder, ready = start_holder(one, env)
    assert ready == "ready"
    assert attempt(one, env) == IN_PROGRESS
    assert attempt(one, env, "probe") == IN_PROGRESS
    assert attempt(two, env) == "acquired", "another graph's lock is independent"
    assert release_holder(holder) == 0
    assert attempt(one, env) == "acquired"

    killed, _ = start_holder(one, env)
    assert attempt(one, env) == IN_PROGRESS
    killed.send_signal(signal.SIGKILL)
    killed.communicate(timeout=120)
    assert killed.returncode == -signal.SIGKILL
    assert attempt(one, env) == "acquired", "the OS released the killed holder's lock"

    keep_read, keep_write = os.pipe()
    try:
        spawner, ready = start_holder(one, env, HOLD_AND_SPAWN, keep_open=keep_read)
        grandchild = int(ready.split()[1])
        assert attempt(one, env) == IN_PROGRESS
        assert release_holder(spawner) == 0
        os.kill(grandchild, 0)  # still alive, and it inherited every inheritable descriptor
        assert attempt(one, env) == "acquired", "a child spawned under the lock does not keep it"
    finally:
        os.close(keep_write)
        os.close(keep_read)
