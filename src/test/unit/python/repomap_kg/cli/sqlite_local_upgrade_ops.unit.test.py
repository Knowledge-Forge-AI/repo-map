"""SQLite Local ``ops sqlite-upgrade`` routing, refusals and path-free payloads (LOCAL8).

In-process CLI over temporary SQLite homes; historical v1 databases come from
the preserved v1 catalog prefix. A PostgreSQL home refuses before any action;
an absent database refuses without creating ``state/``; forbidden outputs and
a held publisher lock refuse before anything is written. ``config-check`` and
``graphs --check-db`` report an exact-behind database as ``schema-behind``
without changing it, and ``sqlite-init`` and ``refresh-graph`` refuse it
before any capture or worker. The JSON and text outcomes carry no path. No
PostgreSQL command, source capture or worker is ever reached.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from repomap_kg import cli
from repomap_kg.ops import local_refresh, portable_refresh
from repomap_kg.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home, local_graph_binding
from repomap_kg.storage.sqlite_local import migrations
from repomap_kg.storage.sqlite_local.connection import publisher_lock
from repomap_kg.storage.sqlite_local.publisher import publish_generation
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
UPGRADE_KEYS = {
    "command", "storage_backend", "result", "graph_id", "from_schema_version", "schema_version",
    "accepted_publication", "accepted_generation", "publication_bundle_id", "backup_created",
    "backup_database_sha256",
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
    return write_sqlite_home(tmp_path / "home", graph_toml("zulu", source))


def _config(home: Path) -> LocalSqliteConfig:
    config = load_graph_registry_config_home(home)
    assert isinstance(config, LocalSqliteConfig)
    return config


def _database(home: Path) -> Path:
    return _config(home).graph_store_root.resolve() / "zulu.sqlite3"


def _historical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = _home(tmp_path)
    config = _config(home)
    with monkeypatch.context() as v1:
        v1.setattr(migrations, "MIGRATIONS", migrations.MIGRATIONS[:1])
        assert local_refresh.initialize_local_graph(config, "zulu")["result"] == "initialized"
        bundle = generation_bundle(1)
        publication = replace(publication_for(bundle, "zulu"), binding=local_graph_binding(config.graphs[0]))
        publish_generation(_database(home), publication, bundle.families, expected_generation=0)
    return home


def _run(home: Path, command: str, *args: str) -> tuple[int, str, str]:
    return run_repo_map_in_process("ops", command, "--repo-map-home", str(home), *args)


def _refused(tmp_path: Path, home: Path, command: str, *args: str) -> str:
    code, stdout, stderr = _run(home, command, *args)
    assert code == 1 and stdout == "", (code, stdout, stderr)
    assert "[redacted-path]" not in stderr and str(tmp_path) not in stderr, stderr
    return stderr.strip()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_upgrade_payload_is_complete_and_path_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _historical(tmp_path, monkeypatch)
    code, stdout, stderr = _run(home, "sqlite-upgrade", "--graph", "zulu", "--backup-output", str(tmp_path / "bk"), "--json")
    assert code == 0, stderr
    upgraded = json.loads(stdout)
    assert set(upgraded) == UPGRADE_KEYS and str(tmp_path) not in stdout, upgraded
    assert (upgraded["result"], upgraded["from_schema_version"], upgraded["schema_version"]) == ("upgraded", 1, 2)
    assert (upgraded["accepted_generation"], upgraded["backup_created"]) == (1, True)
    assert upgraded["backup_database_sha256"] == _sha(tmp_path / "bk" / "graph.sqlite3")
    code, stdout, stderr = _run(home, "sqlite-upgrade", "--graph", "zulu", "--backup-output", str(tmp_path / "bk"), "--json")
    assert code == 0, stderr
    assert json.loads(stdout) == {
        **upgraded, "result": "already-current", "from_schema_version": 2, "backup_created": False,
        "backup_database_sha256": None,
    }
    code, stdout, _ = _run(home, "sqlite-upgrade", "--graph", "zulu", "--backup-output", str(tmp_path / "unused"))
    assert (code, stdout.strip()) == (0, "sqlite-upgrade zulu: already-current (accepted generation 1)")
    assert not (tmp_path / "unused").exists()


def test_behind_database_is_reported_and_refused_by_ordinary_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _historical(tmp_path, monkeypatch)
    database = _database(home)
    before = _sha(database)
    for command in ("config-check", "graphs"):
        code, stdout, stderr = _run(home, command, "--check-db", "--json")
        assert code == 0, stderr
        payload = json.loads(stdout)
        status = (
            payload["storage_status"]["graphs"][0] if command == "config-check"
            else payload["graphs"][0]["storage_status"]
        )
        assert (status["state"], status["accepted_generation"], status["error"]) == (
            "schema-behind", 1, "graph-database-schema-behind",
        ), status
    for command, args in (("sqlite-init", ()), ("refresh-graph", ())):
        message = _refused(tmp_path, home, command, "--graph", "zulu", *args)
        assert message == "ERROR: graph-database-schema-behind: run ops sqlite-upgrade", message
    assert _sha(database) == before, "an ordinary command changed or migrated a behind database"


def test_postgres_home_refuses_before_any_action(tmp_path: Path) -> None:
    home = tmp_path / "pg"
    home.mkdir()
    (home / "repomap.rpl.toml").write_text(setup_owned_config(), encoding="utf-8")
    before = sorted(path.name for path in home.rglob("*"))
    message = _refused(tmp_path, home, "sqlite-upgrade", "--graph", "host-one", "--backup-output", str(tmp_path / "bk"))
    assert "sqlite-local-home-required" in message, message
    assert sorted(path.name for path in home.rglob("*")) == before and not (tmp_path / "bk").exists()


def test_absent_database_and_forbidden_outputs_refuse_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = _home(tmp_path)
    message = _refused(tmp_path, home, "sqlite-upgrade", "--graph", "zulu", "--backup-output", str(tmp_path / "bk"))
    assert message == "ERROR: graph-database-not-initialized: run ops sqlite-init for this graph first", message
    assert not (home / "state").exists() and not (tmp_path / "bk").exists()
    assert "unknown graph_id" in _refused(
        tmp_path, home, "sqlite-upgrade", "--graph", "nope", "--backup-output", str(tmp_path / "bk")
    )
    home = _historical(tmp_path / "second", monkeypatch)
    before = _sha(_database(home))
    for forbidden in (home / "state" / "bk", tmp_path / "second" / "src" / "bk"):
        message = _refused(tmp_path, home, "sqlite-upgrade", "--graph", "zulu", "--backup-output", str(forbidden))
        assert message.startswith("ERROR: sqlite-backup-output-forbidden"), message
        assert not forbidden.exists()
    assert _sha(_database(home)) == before


def test_upgrade_refuses_while_the_graph_publisher_lock_is_held(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _historical(tmp_path, monkeypatch)
    before = _sha(_database(home))
    with publisher_lock(_database(home)):
        message = _refused(tmp_path, home, "sqlite-upgrade", "--graph", "zulu", "--backup-output", str(tmp_path / "bk"))
    assert message == "ERROR: graph-publication-in-progress"
    assert not (tmp_path / "bk").exists() and _sha(_database(home)) == before


def test_filesystem_errors_are_translated_without_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = _historical(tmp_path, monkeypatch)
    locked = tmp_path / "locked"
    locked.mkdir(mode=0o500)
    try:
        message = _refused(tmp_path, home, "sqlite-upgrade", "--graph", "zulu", "--backup-output", str(locked / "bk"))
    finally:
        locked.chmod(0o700)
    assert message == "ERROR: sqlite-upgrade-io-failed: EACCES", message
    assert os.listdir(locked) == []
