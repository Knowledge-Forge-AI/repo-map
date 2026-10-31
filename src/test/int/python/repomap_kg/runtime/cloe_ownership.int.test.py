"""Connected CLI identity and real migration-catalog filesystem readback."""
import json
from pathlib import Path
import shutil

from common_lore_index.coordinator import _control_schema as control
from common_lore_index.storage import _schema_migrations as graph
from repomap_test_support.cli_integration import run_cli_module

ROOT = Path(__file__).resolve().parents[6]


def test_real_cli_keeps_identity_shape_and_reports_the_repository_license() -> None:
    result = run_cli_module("identity", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"name": "Common Lore Index", "distribution": "common-lore-index",
                                        "package": "common_lore_index", "cli": "cloe",
                                        "license": "AGPL-3.0-or-later", "database": "Postgres"}
    version = run_cli_module("--version")
    assert version.returncode == 0 and version.stdout.strip() == "cloe 0.0.3"


def test_real_catalog_readback_in_simulated_installed_layout_preserves_frozen_prefix(tmp_path: Path, monkeypatch) -> None:
    golden = json.loads((ROOT / "src/test/fixtures/cloe/migration-continuity-v1.json").read_text())
    prefix = tmp_path / "share/common-lore-index"
    for family in ("rdbms", "coordinator-rdbms"):
        shutil.copytree(ROOT / "src/main/resources" / family, prefix / family)
    monkeypatch.setattr(graph, "__file__", str(tmp_path / "site/common_lore_index/storage/schema.py"))
    monkeypatch.setattr(graph.sysconfig, "get_path", lambda _name: str(tmp_path))
    for family, rows in (("graph", graph.discover_migrations()), ("control", control.discover_control_migrations())):
        observed = [{"ordinal": row.ordinal, "changeset_id": row.changeset_id,
                     "relative_path": row.relative_path, "checksum": row.checksum} for row in rows]
        assert observed[:len(golden[family])] == golden[family]
    assert graph.default_rdbms_root() == prefix / "rdbms"
    assert control.default_control_rdbms_root() == prefix / "coordinator-rdbms"
