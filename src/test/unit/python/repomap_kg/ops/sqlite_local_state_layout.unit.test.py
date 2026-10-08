"""SQLite Local ``state/`` integrity rule for mutation owners (LOCAL10).

Mutation-owned Local state must be a real, owner-controlled ``state/`` tree
under the resolved home. Init, refresh, backup, restore, upgrade and cleanup
refuse a symlinked ``state`` (even one whose target is itself named ``state``),
a symlinked level below it and a non-directory level before any lock or
mutation: the redirect target stays byte-identical and no lock file, store,
temporary or backup appears. The refusal is path-free. A symlinked home still
works, and read-only paths (readiness and the MCP read binding) do not refuse
because ``state`` is a symlink. The record-level guard is owned by
``ops/sqlite_local_retention_layout``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.ops import local_refresh, local_state_layout
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home, local_graph_binding
from repomap_kg.ops.local_backup import backup_local_graph, restore_local_graph, upgrade_local_graph
from repomap_kg.ops.local_cleanup import cleanup_local_graph
from repomap_kg.ops.local_readiness import probe_local_graphs
from repomap_kg.server import sqlite_read_binding
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
from repomap_test_support.host_read_store_config import fail_if_reached
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_sqlite_home

GRAPH = "one"
LAYOUT = "local-state-layout-invalid: a Local state level is not a private directory"
CLEANUP_LAYOUT = "sqlite-cleanup-layout-invalid: a Local state level is not a private directory"


def _config(home: Path, tmp_path: Path) -> LocalSqliteConfig:
    source = tmp_path / "src"
    source.mkdir(exist_ok=True)
    write_sqlite_home(home, graph_toml(GRAPH, source))
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    return config


def _tree(root: Path) -> dict[str, tuple[int, int, str]]:
    snapshot: dict[str, tuple[int, int, str]] = {}
    for path in sorted(root.rglob("*")):
        details = path.lstat()
        content = hashlib.sha256(path.read_bytes()).hexdigest() if stat.S_ISREG(details.st_mode) else ""
        snapshot[str(path.relative_to(root))] = (stat.S_IFMT(details.st_mode), stat.S_IMODE(details.st_mode), content)
    return snapshot


def _operations(tmp_path: Path) -> dict[str, Callable[[LocalSqliteConfig], Any]]:
    return {
        "init": lambda config: local_refresh.initialize_local_graph(config, GRAPH),
        "refresh": lambda config: local_refresh.refresh_local_graph(config, GRAPH),
        "backup": lambda config: backup_local_graph(config, GRAPH, tmp_path / "backup-out"),
        # Refused before the backup is even read: it does not exist.
        "restore": lambda config: restore_local_graph(config, GRAPH, tmp_path / "no-such-backup"),
        "upgrade": lambda config: upgrade_local_graph(config, GRAPH, tmp_path / "upgrade-out"),
        "cleanup": lambda config: cleanup_local_graph(config, GRAPH, execute=True),
        "cleanup-dry-run": lambda config: cleanup_local_graph(config, GRAPH, execute=False),
    }


def _redirected(tmp_path: Path, kind: str) -> tuple[LocalSqliteConfig, Path]:
    """An initialized home whose ``state`` tree is redirected; return it and the redirect target."""
    home = tmp_path / "home"
    config = _config(home, tmp_path)
    assert local_refresh.initialize_local_graph(config, GRAPH)["result"] == "initialized"
    if kind == "state-named-state":
        target = tmp_path / "volume" / "state"
        target.parent.mkdir()
        shutil.move(home / "state", target)
        (home / "state").symlink_to(target)
    elif kind == "sqlite-local-named-sqlite-local":
        target = tmp_path / "volume" / "sqlite-local"
        target.parent.mkdir()
        shutil.move(home / "state" / "sqlite-local", target)
        (home / "state" / "sqlite-local").symlink_to(target)
    else:  # state is a regular file
        target = tmp_path / "moved-state"
        shutil.move(home / "state", target)
        (home / "state").write_bytes(b"not a directory")
    return config, target


@pytest.mark.parametrize("kind", ("state-named-state", "sqlite-local-named-sqlite-local", "state-is-a-file"))
@pytest.mark.parametrize("operation", tuple(_operations(Path("."))))
def test_every_mutation_owner_refuses_a_redirected_state_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, operation: str
) -> None:
    config, target = _redirected(tmp_path, kind)
    monkeypatch.setattr(local_refresh, "capture_portable_candidate", fail_if_reached)
    before, home_before = _tree(target), _tree(config.control_root)
    with pytest.raises(LocalStoreError) as caught:
        _operations(tmp_path)[operation](config)
    expected = CLEANUP_LAYOUT if operation.startswith("cleanup") else LAYOUT
    assert str(caught.value) == expected and str(tmp_path) not in str(caught.value)
    assert _tree(target) == before, "the redirect target changed"
    assert _tree(config.control_root) == home_before, "the home changed"
    assert not (tmp_path / "backup-out").exists() and not (tmp_path / "upgrade-out").exists()


def test_refresh_reports_the_layout_before_not_initialized(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config = _config(home, tmp_path)
    elsewhere = tmp_path / "volume" / "state"
    elsewhere.mkdir(parents=True)
    (home / "state").symlink_to(elsewhere)
    for operation in ("refresh", "backup", "upgrade", "init"):
        with pytest.raises(LocalStoreError) as caught:
            _operations(tmp_path)[operation](config)
        assert str(caught.value) == LAYOUT, operation
    assert list(elsewhere.iterdir()) == [], "no store or lock file was created"


def test_an_unverifiable_or_foreign_owner_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(tmp_path / "home", tmp_path)
    assert local_refresh.initialize_local_graph(config, GRAPH)["result"] == "initialized"
    uid = os.getuid()
    monkeypatch.setattr(local_state_layout, "_current_uid", lambda: uid + 1)
    with pytest.raises(LocalStoreError) as caught:
        local_refresh.initialize_local_graph(config, GRAPH)
    assert str(caught.value) == LAYOUT
    monkeypatch.setattr(local_state_layout, "_current_uid", lambda: None)
    for operation in ("init", "cleanup"):
        with pytest.raises(LocalStoreError) as caught:
            _operations(tmp_path)[operation](config)
        assert str(caught.value).endswith(": Local state ownership cannot be verified on this platform")


def test_a_symlinked_home_still_works(tmp_path: Path) -> None:
    real = tmp_path / "real-home"
    _config(real, tmp_path)
    alias = tmp_path / "alias-home"
    alias.symlink_to(real)
    config = _config(alias, tmp_path)
    assert local_refresh.initialize_local_graph(config, GRAPH)["result"] == "initialized"
    assert (real / "state" / "sqlite-local" / "graphs" / f"{GRAPH}.sqlite3").is_file()
    assert cleanup_local_graph(config, GRAPH, execute=False)["result"] == "dry-run"
    assert cleanup_local_graph(config, GRAPH, execute=True)["result"] == "cleaned"


def test_read_only_paths_do_not_refuse_a_symlinked_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config, _ = _redirected(tmp_path, "state-named-state")
    monkeypatch.setattr(local_state_layout, "require_private_levels", fail_if_reached)
    states = [item.to_jsonable() for item in probe_local_graphs(config)]
    assert [(item["graph_id"], item["state"]) for item in states] == [(GRAPH, "current")], states
    graph = config.graphs[0]
    store = sqlite_read_binding.SqliteCanonicalReadStore(
        sqlite_read_binding._database(config, graph), local_graph_binding(graph)
    )
    summary = store.canonical_storage_summary()
    assert summary is not None
