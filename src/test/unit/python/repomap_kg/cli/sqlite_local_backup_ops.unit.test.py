"""SQLite Local ``ops sqlite-backup`` and ``ops sqlite-restore`` (LOCAL7).

In-process CLI over temporary SQLite Local homes with publications written
directly by the maintained fixture bundles (no worker, source capture or
PostgreSQL). PostgreSQL homes refuse before any filesystem or database action;
outputs inside the home state or a source root are refused; a held publisher
lock refuses immediately; a tampered backup is refused before the target store
exists; and every refusal and every JSON payload is path-free by construction
(the CLI path sanitizer never has anything to redact). Real refresh, source
removal and MCP reads after restore are owned by the containerized
backup/restore integration owner.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from repomap_kg import cli
from repomap_kg.ops import local_backup, local_refresh, portable_refresh
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home, local_graph_binding
from repomap_kg.storage.sqlite_local import connection, restore
from repomap_kg.storage.sqlite_local.connection import publisher_lock
from repomap_kg.storage.sqlite_local.publisher import publish_generation
from repomap_kg.storage.sqlite_local.schema import LocalStoreError
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.host_read_store_config import fail_if_reached, setup_owned_config
from repomap_test_support.sqlite_local_fixtures import (
    generation_bundle,
    graph_toml,
    publication_for,
    write_shell_source,
    write_sqlite_home,
)

PG_NAMES = ("refresh_graph", "refresh_enabled_graphs", "load_ops_config_home", "maintenance_activity_for_home")
BACKUP_KEYS = {
    "command", "storage_backend", "result", "graph_id", "accepted_publication", "accepted_generation",
    "publication_bundle_id", "database_bytes", "database_sha256", "schema_version",
}


@pytest.fixture(autouse=True)
def _source_blind() -> Iterator[None]:
    """No PostgreSQL command, source capture or worker is ever reached."""
    patches = [patch.object(cli, name, fail_if_reached) for name in PG_NAMES] + [
        patch.object(local_refresh, "capture_portable_candidate", fail_if_reached),
        patch.object(portable_refresh, "run_portable_worker", fail_if_reached),
    ]
    for item in patches:
        item.start()
    try:
        yield
    finally:
        for item in patches:
            item.stop()


def _home(tmp_path: Path) -> Path:
    source = write_shell_source(tmp_path / "src")
    return write_sqlite_home(
        tmp_path / "home", graph_toml("zulu", source) + graph_toml("mike", source, enabled=False)
    )


def _config(home: Path) -> LocalSqliteConfig:
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    return config


def _database(home: Path, graph: str = "zulu") -> Path:
    return _config(home).graph_store_root.resolve() / f"{graph}.sqlite3"


def _published(tmp_path: Path, generations: int = 1, graph: str = "zulu") -> Path:
    home = _home(tmp_path)
    config = _config(home)
    assert local_refresh.initialize_local_graph(config, graph)["result"] == "initialized"
    binding = local_graph_binding(next(item for item in config.graphs if item.id == graph))
    for generation in range(1, generations + 1):
        bundle = generation_bundle(generation)
        publication = replace(publication_for(bundle, graph), binding=binding)
        publish_generation(_database(home, graph), publication, bundle.families, expected_generation=generation - 1)
    return home


def _run(home: Path, command: str, *args: str) -> tuple[int, str, str]:
    return run_repo_map_in_process("ops", command, "--repo-map-home", str(home), *args)


def _refused(tmp_path: Path, home: Path, command: str, *args: str) -> str:
    code, stdout, stderr = _run(home, command, *args)
    assert code == 1 and stdout == "", (code, stdout, stderr)
    assert "[redacted-path]" not in stderr and str(tmp_path) not in stderr, stderr
    return stderr.strip()


def test_backup_and_restore_payloads_are_path_free(tmp_path: Path) -> None:
    home = _published(tmp_path)
    code, stdout, stderr = _run(home, "sqlite-backup", "--graph", "zulu", "--output", str(tmp_path / "bk"), "--json")
    assert code == 0, stderr
    created = json.loads(stdout)
    assert set(created) == BACKUP_KEYS and created["result"] == "created", created
    assert (created["accepted_publication"], created["accepted_generation"], created["schema_version"]) == (True, 1, 2)
    assert str(tmp_path) not in stdout
    database = _database(home)
    database.unlink()
    for suffix in ("-wal", "-shm"):
        database.with_name(database.name + suffix).unlink(missing_ok=True)
    code, stdout, stderr = _run(home, "sqlite-restore", "--graph", "zulu", "--backup", str(tmp_path / "bk"), "--json")
    assert code == 0, stderr
    restored = json.loads(stdout)
    assert restored == {
        "command": "sqlite-restore", "storage_backend": "sqlite", "result": "restored", "graph_id": "zulu",
        "schema_version": 2, "schema_state": "current", "accepted_publication": True, "accepted_generation": 1,
        "publication_bundle_id": created["publication_bundle_id"], "database_sha256": created["database_sha256"],
    }
    assert str(tmp_path) not in stdout


def test_text_summaries(tmp_path: Path) -> None:
    home = _published(tmp_path, generations=0)
    code, stdout, _ = _run(home, "sqlite-backup", "--graph", "zulu", "--output", str(tmp_path / "bk"))
    assert (code, stdout.strip()) == (0, "sqlite-backup zulu: created (unpublished)")
    code, stdout, _ = _run(home, "sqlite-init", "--graph", "mike")
    assert (code, stdout.strip()) == (0, "sqlite-init mike: initialized")


def test_postgres_home_refuses_both_commands_without_side_effects(tmp_path: Path) -> None:
    home = tmp_path / "pg"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    (tmp_path / "bk").mkdir()
    before = sorted(path.name for path in home.rglob("*"))
    for command, option in (("sqlite-backup", "--output"), ("sqlite-restore", "--backup")):
        message = _refused(tmp_path, home, command, "--graph", "host-one", option, str(tmp_path / "bk" / "x"))
        assert "sqlite-local-home-required" in message, message
    assert sorted(path.name for path in home.rglob("*")) == before
    assert os.listdir(tmp_path / "bk") == []


def test_backup_refusals_create_nothing(tmp_path: Path) -> None:
    home = _published(tmp_path)
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "keep").write_text("x", encoding="utf-8")
    cases = {
        str(tmp_path / "missing" / "bk"): "sqlite-backup-output-invalid: output parent is not a directory",
        str(tmp_path / "full"): "sqlite-backup-target-exists: output directory is not empty",
        str(home / "state" / "bk"): "sqlite-backup-output-forbidden: output must be outside the home state and every source root",
        str(tmp_path / "src" / "bk"): "sqlite-backup-output-forbidden: output must be outside the home state and every source root",
        str(tmp_path / "src"): "sqlite-backup-output-forbidden: output must be outside the home state and every source root",
    }
    for output, expected in cases.items():
        assert _refused(tmp_path, home, "sqlite-backup", "--graph", "zulu", "--output", output) == f"ERROR: {expected}"
    assert not (home / "state" / "bk").exists() and not (tmp_path / "src" / "bk").exists()
    assert os.listdir(tmp_path / "full") == ["keep"]
    assert _refused(tmp_path, home, "sqlite-backup", "--graph", "mike", "--output", str(tmp_path / "m")) == (
        "ERROR: graph-database-not-initialized: run ops sqlite-init for this graph first"
    )
    assert _refused(tmp_path, home, "sqlite-backup", "--graph", "nope", "--output", str(tmp_path / "n")) == (
        "ERROR: unknown graph_id: nope"
    )
    assert not (tmp_path / "m").exists() and not (tmp_path / "n").exists()
    assert not _database(home, "mike").exists()


def test_backup_refuses_while_the_graph_publisher_lock_is_held(tmp_path: Path) -> None:
    home = _published(tmp_path)
    with publisher_lock(_database(home)):
        message = _refused(tmp_path, home, "sqlite-backup", "--graph", "zulu", "--output", str(tmp_path / "bk"))
    assert message == "ERROR: graph-publication-in-progress"
    assert not (tmp_path / "bk").exists()


def test_filesystem_errors_are_translated_without_paths(tmp_path: Path) -> None:
    home = _published(tmp_path)
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    try:
        message = _refused(tmp_path, home, "sqlite-backup", "--graph", "zulu", "--output", str(locked / "bk"))
    finally:
        locked.chmod(0o700)
    assert message == "ERROR: sqlite-backup-io-failed: EACCES", message


def test_disabled_graph_can_be_backed_up(tmp_path: Path) -> None:
    home = _published(tmp_path, generations=0, graph="mike")
    code, stdout, stderr = _run(home, "sqlite-backup", "--graph", "mike", "--output", str(tmp_path / "bk"), "--json")
    assert code == 0 and json.loads(stdout)["accepted_publication"] is False, stderr


def test_restore_validates_before_creating_the_store_and_never_clobbers(tmp_path: Path) -> None:
    home = _published(tmp_path)
    assert _run(home, "sqlite-backup", "--graph", "zulu", "--output", str(tmp_path / "bk"))[0] == 0
    assert _refused(tmp_path, home, "sqlite-restore", "--graph", "zulu", "--backup", str(tmp_path / "bk")) == (
        "ERROR: sqlite-restore-target-exists: a graph database already exists"
    )
    assert _refused(tmp_path, home, "sqlite-restore", "--graph", "mike", "--backup", str(tmp_path / "bk")) == (
        "ERROR: sqlite-backup-artifact-invalid: graph-mismatch"
    )
    fresh = write_sqlite_home(tmp_path / "fresh", graph_toml("zulu", tmp_path / "src"))
    database = tmp_path / "bk" / "graph.sqlite3"
    data = bytearray(database.read_bytes())
    data[-1] ^= 0x01
    database.write_bytes(bytes(data))
    assert _refused(tmp_path, fresh, "sqlite-restore", "--graph", "zulu", "--backup", str(tmp_path / "bk")) == (
        "ERROR: sqlite-backup-artifact-invalid: database-digest-mismatch"
    )
    (tmp_path / "bk" / "manifest.json").unlink()
    assert _refused(tmp_path, fresh, "sqlite-restore", "--graph", "zulu", "--backup", str(tmp_path / "bk")) == (
        "ERROR: sqlite-backup-incomplete: no completed manifest"
    )
    assert not (fresh / "state").exists(), "a refused restore created the store"


def test_init_and_restore_sync_every_store_level_up_to_the_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _published(tmp_path)
    assert _run(home, "sqlite-backup", "--graph", "zulu", "--output", str(tmp_path / "bk"))[0] == 0
    levels: list[tuple[str, Path, int]] = []

    def record(owner: str, real: Any) -> Any:
        def chain(leaf: Path, ancestors: int) -> None:
            levels.append((owner, leaf, ancestors))
            real(leaf, ancestors)

        return chain

    monkeypatch.setattr(connection, "fsync_directory_chain", record("init", connection.fsync_directory_chain))
    monkeypatch.setattr(restore, "fsync_directory_chain", record("restore", restore.fsync_directory_chain))
    fresh = write_sqlite_home(tmp_path / "fresh", graph_toml("zulu", tmp_path / "src") + graph_toml("mike", tmp_path / "src"))
    assert _run(fresh, "sqlite-init", "--graph", "mike")[0] == 0
    assert _run(fresh, "sqlite-restore", "--graph", "zulu", "--backup", str(tmp_path / "bk"))[0] == 0
    store = _config(fresh).graph_store_root.resolve()
    assert levels == [("init", store, 3), ("restore", store, 3)], levels
    assert store.parent.parent.parent == fresh.resolve()


def test_ops_refusals_carry_no_path_at_all(tmp_path: Path) -> None:
    home = _published(tmp_path)
    config = _config(home)
    for call in (
        lambda: local_backup.backup_local_graph(config, "zulu", tmp_path / "missing" / "bk"),
        lambda: local_backup.backup_local_graph(config, "mike", tmp_path / "bk"),
        lambda: local_backup.restore_local_graph(config, "zulu", tmp_path / "absent"),
    ):
        with pytest.raises(LocalStoreError) as caught:
            call()
        assert "/" not in str(caught.value), str(caught.value)
