"""Installed ownership preparation without changing current package identities."""
import json
from pathlib import Path
import tomllib

import common_lore_index
from common_lore_index.coordinator import _control_schema as control
from common_lore_index.runtime.project_identity import PROJECT_IDENTITY
from common_lore_index.storage import _schema_migrations as graph

ROOT = Path(__file__).resolve().parents[6]
GOLDEN = ROOT / "src/test/fixtures/cloe/migration-continuity-v1.json"


def records(rows):
    return [{"ordinal": row.ordinal, "changeset_id": row.changeset_id,
             "relative_path": row.relative_path, "checksum": row.checksum} for row in rows]


def test_current_identity_and_license_agree_with_owned_distribution_metadata() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert PROJECT_IDENTITY.distribution == common_lore_index.DISTRIBUTION_NAME == project["name"] == "repomap-kg"
    assert PROJECT_IDENTITY.package == common_lore_index.IMPORT_PACKAGE == "common_lore_index"
    assert PROJECT_IDENTITY.cli == common_lore_index.PREFERRED_CLI == "repomap-kg"
    assert PROJECT_IDENTITY.license == project["license"] == "AGPL-3.0-or-later"
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in (ROOT / "LICENSE").read_text()
    assert set(PROJECT_IDENTITY.as_dict()) == {"name", "distribution", "package", "cli", "license", "database"}


def test_migration_catalogs_preserve_every_frozen_relative_identity_and_checksum() -> None:
    golden = json.loads(GOLDEN.read_text())
    for family, rows in (("graph", graph.discover_migrations()), ("control", control.discover_control_migrations())):
        assert golden[family]
        assert records(rows)[:len(golden[family])] == golden[family]
    assert "CREATE TABLE repomap_schema_migrations" in graph.graph_schema_ledger_bootstrap_sql()
    assert "'repomap-graph-schema-ledger:1'" in graph.graph_schema_ledger_bootstrap_sql()
    assert "CREATE TABLE repomap_control_schema_migrations" in control.control_schema_ledger_bootstrap_sql()
    assert "'repomap-control-schema-ledger:1'" in control.control_schema_ledger_bootstrap_sql()


def test_installed_resource_prefix_has_one_owner_and_never_falls_back(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(graph, "__file__", str(tmp_path / "site/common_lore_index/storage/schema.py"))
    monkeypatch.setattr(graph.sysconfig, "get_path", lambda _name: str(tmp_path))
    old = tmp_path / "share/repomap-kg/rdbms"
    old.mkdir(parents=True)
    monkeypatch.setattr(graph, "DISTRIBUTION_NAME", "future-owner")
    assert graph.default_rdbms_root() == tmp_path / "share/future-owner/rdbms"
    assert control.default_control_rdbms_root() == tmp_path / "share/future-owner/coordinator-rdbms"
