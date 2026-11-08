"""Real plan CLI: independent metadata counts and forbidden-effect witnesses."""

from __future__ import annotations

import builtins
import fcntl
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, NoReturn

import psycopg
import pytest

from common_lore_index.cli.main import main
from repomap_test_support.retrieval_evaluation_fixture import write_mixed_v1_postgres_home
from repomap_test_support.sealing_governance_fixtures import write_tree
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_sqlite_home

GRAPH = "plan-boundary-proof"
CORE = {"a.py": b"a=1\n", "deep/b.txt": b"metadata only\n"}
COMPANION = {"one.py": b"b=2\n", "excluded_cache/blocked.py": b"excluded body\n"}


def _snapshot(roots: list[Path]) -> dict[str, tuple[int, int, int, str | None]]:
    return {
        f"{index}/{path.relative_to(root).as_posix()}": (
            path.lstat().st_mode, path.lstat().st_size, path.lstat().st_mtime_ns,
            os.readlink(path) if path.is_symlink() else None,
        )
        for index, root in enumerate(roots)
        for path in sorted(root.rglob("*"))
    }


@pytest.mark.parametrize("backend", ("sqlite", "postgresql"))
def test_plan_cli_never_opens_source_bodies_or_operational_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], backend: str,
) -> None:
    working = tmp_path / "sources"
    core = write_tree(working / "core", CORE)
    (core / "alias.py").symlink_to("a.py")
    roots = [core]
    total = sum(map(len, CORE.values()))
    files, entries, listings = 2, 4, 2
    if backend == "sqlite":
        home = write_sqlite_home(tmp_path / "home", graph_toml(GRAPH, core))
    else:
        companion = write_tree(working / "companion", COMPANION)
        roots.append(companion)
        total += len(COMPANION["one.py"])
        files, entries, listings = 3, 6, 3
        home = write_mixed_v1_postgres_home(
            tmp_path / "home", working, graph_id=GRAPH, port=59999,
            database="never_started", user="nobody", password=os.urandom(16).hex(),
            declared_aliases=("core", "companion"),
        )
    before = _snapshot([*roots, home])
    forbidden: list[str] = []
    real_io_open, real_builtin_open, real_os_open = io.open, builtins.open, os.open

    def fail(kind: str) -> NoReturn:
        forbidden.append(kind)
        raise AssertionError(f"metadata plan attempted forbidden effect: {kind}")

    def path_for(file: Any, dir_fd: int | None = None) -> Path | None:
        if isinstance(file, int):
            return None
        path = Path(os.fsdecode(file))
        if not path.is_absolute():
            base = Path(os.readlink(f"/proc/self/fd/{dir_fd}")) if dir_fd is not None else Path.cwd()
            path = base / path
        return path

    def check_path(path: Path | None, *, writing: bool) -> None:
        if path is None:
            return
        raw = path.absolute()
        resolved = path.resolve()
        if any(raw.is_relative_to(root) or resolved.is_relative_to(root) for root in roots):
            if writing:
                fail("source-write")
            if path.is_file():
                fail("source-body-open")
        if writing and (raw.is_relative_to(home) or resolved.is_relative_to(home)):
            fail("home-write")

    def guarded_io(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        check_path(path_for(file), writing=any(flag in mode for flag in "wax+"))
        return real_io_open(file, mode, *args, **kwargs)

    def guarded_builtin(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        check_path(path_for(file), writing=any(flag in mode for flag in "wax+"))
        return real_builtin_open(file, mode, *args, **kwargs)

    def guarded_os(file: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        writing = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
        check_path(path_for(file, dir_fd), writing=writing)
        return real_os_open(file, flags, mode, dir_fd=dir_fd)

    def no_process(*_args: Any, **_kwargs: Any) -> NoReturn:
        fail("subprocess-or-worker")

    def no_database(*_args: Any, **_kwargs: Any) -> NoReturn:
        fail("database-connect")

    def no_lock(*_args: Any, **_kwargs: Any) -> NoReturn:
        fail("operational-lock")

    with monkeypatch.context() as patch:
        patch.setattr(io, "open", guarded_io)
        patch.setattr(builtins, "open", guarded_builtin)
        patch.setattr(os, "open", guarded_os)
        patch.setattr(subprocess, "Popen", no_process)
        patch.setattr(sqlite3, "connect", no_database)
        patch.setattr(psycopg, "connect", no_database)
        patch.setattr(psycopg.Connection, "connect", no_database)
        patch.setattr(fcntl, "flock", no_lock)
        code = main([
            "ops", "sealing-plan", "--repo-map-home", str(home), "--graph", GRAPH, "--json",
        ], prog="cloe")
    captured = capsys.readouterr()
    assert code == 0 and captured.err == "" and forbidden == []
    plan = json.loads(captured.out)
    assert len(captured.out.encode("utf-8")) <= 4096
    assert plan["schema"] == "cloe-sealing-plan-v1" and plan["refusal"] is None
    assert plan["bindings"] == len(roots)
    assert (plan["inventory_files"], plan["inventory_bytes"]) == (files, total)
    assert plan["inventory_symlinked_files"] == 1
    assert (plan["directory_entries"], plan["opens"]) == (entries, listings)
    assert plan["planned_min_read_bytes"] == 6 * total + 1
    assert plan["planned_min_read_bytes_basis"] == "derived_lower_bound"
    assert plan["planned_min_write_bytes"] == total
    assert plan["effective_max_directory_entries"] == 100_000
    assert plan["projected_directory_entries"] == 3 * entries
    assert plan["projection_basis"] == "three_walks_of_unchanged_metadata_tree_estimate"
    assert plan["factors"] == {
        "full_body_reads_per_file": 6, "collision_extra_reads_per_file": 2,
        "stable_capture_max_attempts": 3,
    }
    assert _snapshot([*roots, home]) == before
    for secret in (str(home), str(working), GRAPH, "unused-secret", "never_started"):
        assert secret not in captured.out
