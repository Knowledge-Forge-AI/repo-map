"""Every SQLite Local mutation owner serializes on the one graph lock (LOCAL10, L9).

A real child process holds a graph's lock through the shared lock owner,
synchronized by pipes. Direct refresh, init, backup, restore, upgrade and
cleanup (``--yes`` and dry run) each refuse ``graph-publication-in-progress``
with the home unchanged, and each proceeds once the child releases. The
cleanup missing-store case: when the graph store is absent at the lock
decision, orphans stay ``not-inspected`` even if a store and an init temporary
appear during the run. Mixed CLI operations are owned by the containerized
``cli/sqlite_local_locking`` integration owner.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.ops import local_cleanup, local_refresh
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from repomap_kg.ops.local_backup import backup_local_graph, restore_local_graph, upgrade_local_graph
from repomap_kg.ops.local_cleanup import cleanup_local_graph
from repomap_kg.ops.local_state_layout import attempts_namespace
from repomap_kg.ops.portable_refresh import portable_attempts_parent
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
from repomap_test_support.cli_in_process import module_process_environment
from repomap_test_support.host_read_store_config import fail_if_reached
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_sqlite_home
from repomap_test_support.sqlite_local_harness import remove_database
from repomap_test_support.sqlite_local_lock_children import release_holder, start_holder

IN_PROGRESS = "graph-publication-in-progress"


class Reached(Exception):
    """Refresh got past the lock and reconciliation to source capture."""


def _reached(*_args: Any, **_kwargs: Any) -> Any:
    raise Reached


def _home(tmp_path: Path) -> LocalSqliteConfig:
    source = tmp_path / "src"
    source.mkdir(exist_ok=True)
    home = write_sqlite_home(tmp_path / "home", graph_toml("one", source) + graph_toml("two", source))
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    return config


def _database(config: LocalSqliteConfig, graph: str) -> Path:
    return config.graph_store_root / f"{graph}.sqlite3"


def _tree(root: Path) -> dict[str, tuple[int, int, str]]:
    snapshot: dict[str, tuple[int, int, str]] = {}
    for path in sorted(root.rglob("*")):
        details = path.lstat()
        content = hashlib.sha256(path.read_bytes()).hexdigest() if stat.S_ISREG(details.st_mode) else ""
        snapshot[str(path.relative_to(root))] = (stat.S_IFMT(details.st_mode), stat.S_IMODE(details.st_mode), content)
    return snapshot


def _prepared(tmp_path: Path) -> LocalSqliteConfig:
    """Graph ``one`` initialized; graph ``two`` absent with a verified backup of it."""
    config = _home(tmp_path)
    for graph in ("one", "two"):
        assert local_refresh.initialize_local_graph(config, graph)["result"] == "initialized"
    backup_local_graph(config, "two", tmp_path / "backup-two")
    remove_database(_database(config, "two"))
    return config


# operation -> (graph whose lock it needs, call, result once the lock is free)
def _operations(tmp_path: Path) -> dict[str, tuple[str, Callable[[LocalSqliteConfig], Any], str]]:
    return {
        "refresh": ("one", lambda config: local_refresh.refresh_local_graph(config, "one"), "reached-capture"),
        "init": ("two", lambda config: local_refresh.initialize_local_graph(config, "two"), "initialized"),
        "backup": ("one", lambda config: backup_local_graph(config, "one", tmp_path / "out"), "created"),
        "restore": ("two", lambda config: restore_local_graph(config, "two", tmp_path / "backup-two"), "restored"),
        "upgrade": ("one", lambda config: upgrade_local_graph(config, "one", tmp_path / "out"), "already-current"),
        "cleanup-yes": ("one", lambda config: cleanup_local_graph(config, "one", execute=True), "cleaned"),
        "cleanup-dry-run": ("one", lambda config: cleanup_local_graph(config, "one", execute=False), "dry-run"),
    }


def _result(call: Callable[[LocalSqliteConfig], Any], config: LocalSqliteConfig) -> str:
    try:
        return str(call(config)["result"])
    except Reached:
        return "reached-capture"


@pytest.mark.parametrize("operation", tuple(_operations(Path("."))))
def test_every_mutation_owner_refuses_a_held_graph_lock_then_proceeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    config = _prepared(tmp_path)
    graph, call, expected = _operations(tmp_path)[operation]
    monkeypatch.setattr(local_refresh, "capture_portable_candidate", fail_if_reached)
    holder, ready = start_holder(_database(config, graph), module_process_environment())
    try:
        assert ready == "ready"
        before = _tree(config.control_root)
        with pytest.raises(LocalStoreError) as caught:
            call(config)
        assert str(caught.value) == IN_PROGRESS
        assert _tree(config.control_root) == before, "a refused operation changed the home"
        assert not (tmp_path / "out").exists()
    finally:
        assert release_holder(holder) == 0
    monkeypatch.setattr(local_refresh, "capture_portable_candidate", _reached)
    assert _result(call, config) == expected


def test_cleanup_never_inspects_a_store_that_appears_after_the_lock_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _home(tmp_path)
    portable_attempts_parent(config, attempts_namespace("one")).mkdir(mode=0o700, parents=True)
    store = config.graph_store_root
    orphan = store / ".one.sqlite3.init-0123456789abcdef"
    original = local_cleanup.classify_retained_attempts

    def racing_init(parent: Path, *, now: int) -> Any:
        # A concurrent sqlite-init creates the store and its temporary under its own lock.
        if not store.exists():
            store.mkdir(mode=0o700, parents=True)
            os.close(os.open(orphan, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600))
        return original(parent, now=now)

    monkeypatch.setattr(local_cleanup, "classify_retained_attempts", racing_init)
    monkeypatch.setattr(local_cleanup.orphans, "pinned_store", fail_if_reached)
    payload = cleanup_local_graph(config, "one", execute=True)
    assert (payload["result"], payload["final_database"], payload["changed"]) == ("cleaned", "not-inspected", False)
    assert payload["orphans"]["partial_found"] == 0 and orphan.exists(), "an unlocked orphan was touched"
    assert sorted(path.name for path in store.iterdir()) == [orphan.name], "no lock file was created"
