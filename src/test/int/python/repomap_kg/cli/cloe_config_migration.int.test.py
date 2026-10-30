"""ADR 0114 real CLI/API configuration migration apply, rollback and finalize in the disposable sandbox."""
from __future__ import annotations

import builtins
from collections.abc import Callable
import io
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

import pytest

from repomap_kg.ops.config_migration import (
    apply_cloe_config_migration, finalize_cloe_config_migration, rollback_cloe_config_migration,
)
from repomap_test_support.cli_integration import OPS_CONFIG_TEMPLATE, run_cli_module
from repomap_test_support.sqlite_local_fixtures import graph_toml, sqlite_home_toml
from repomap_test_support.sqlite_local_harness import LocalHarness

SECRET = "migration-int-secret-sentinel"
OVERLAY = 'schema_version = 1\n[service]\nlog_level = "debug"\n'
OPERATION = ".cloe-config-migration"


@pytest.mark.parametrize("backend", ["postgresql", "sqlite"])
@pytest.mark.parametrize("backup_change", ["missing", "corrupt"])
@pytest.mark.parametrize("confirmed", [False, True])
def test_cli_preserves_restore_scratch_when_required_backup_has_drifted(
    tmp_path: Path, backend: str, backup_change: str, confirmed: bool,
) -> None:
    home = make_home(tmp_path, backend)
    assert cli(home, "apply", "--yes")["result"] == "applied"
    operation = home / OPERATION
    backup = operation / "backup-0000.bin"
    (operation / "restore-0000.tmp").write_bytes(backup.read_bytes())
    (home / "00-project.cloe.toml").unlink()
    if backup_change == "missing":
        backup.unlink()
    else:
        backup.write_bytes(b"changed-backup")
    before = tree(home)
    flags = ("--yes",) if confirmed else ("--dry-run",)
    result = cli(home, "rollback", *flags, code=1)
    assert result["result"] == "refused"
    assert result["refusals"] == [{"code": "config-migration-drift", "file": "00-project.rp.toml"}]
    assert tree(home) == before
    assert result["writes_performed"] == 0


def make_home(tmp_path: Path, backend: str, source: Path | None = None) -> Path:
    home = tmp_path / "home with spaces"
    home.mkdir()
    base = OPS_CONFIG_TEMPLATE.replace('password_env = "REPOMAP_PG_PASSWORD"', f'password = "{SECRET}"')
    if backend == "sqlite":
        base = sqlite_home_toml(graph_toml("one", source or "/not-read/source"))
    (home / "00-project.rp.toml").write_text(base)
    (home / "90-machine.rpl.toml").write_text(OVERLAY)
    for path in home.iterdir():
        path.chmod(0o644)
    home.chmod(0o700)
    return home


def tree(root: Path) -> dict[str, tuple[int, bytes | None]]:
    found: dict[str, tuple[int, bytes | None]] = {".": (root.lstat().st_mode, None)}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        found[str(path.relative_to(root))] = (info.st_mode, path.read_bytes() if stat.S_ISREG(info.st_mode) else None)
    return found


def cli(home: Path, command: str, *flags: str, code: int = 0) -> dict[str, Any]:
    result = run_cli_module("ops", f"config-migration-{command}", "--repo-map-home", str(home), *flags, "--json")
    assert result.returncode == code, result.stderr
    assert SECRET not in result.stdout + result.stderr and str(home) not in result.stdout + result.stderr
    payload: dict[str, Any] = json.loads(result.stdout)
    assert payload["schema"] == "cloe-config-migration-result-v1" and payload["operation"] == command
    return payload


def graphs(home: Path) -> list[str]:
    checked = run_cli_module("ops", "config-check", "--repo-map-home", str(home), "--json")
    assert checked.returncode == 0, checked.stderr
    payload = json.loads(checked.stdout)
    assert payload["valid"] is True and SECRET not in checked.stdout
    return sorted(graph["id"] for graph in payload["graphs"])


@pytest.mark.parametrize("backend", ["postgresql", "sqlite"])
def test_real_cli_apply_load_rollback_reapply_finalize_lifecycle(tmp_path: Path, backend: str) -> None:
    home = make_home(tmp_path, backend)
    original = tree(home)
    configured = graphs(home)
    assert cli(home, "apply")["result"] == "would-apply" and tree(home) == original
    applied = cli(home, "apply", "--yes")
    assert applied["result"] == "applied" and applied["rollback_available"] and applied["finalize_pending"]
    assert sorted(p.name for p in home.iterdir()) == [OPERATION, "00-project.cloe.toml", "90-machine.local.cloe.toml"]
    assert graphs(home) == configured
    assert cli(home, "apply", "--yes")["result"] == "already-applied"
    assert cli(home, "rollback", "--yes")["result"] == "rolled-back"
    assert tree(home) == original and graphs(home) == configured
    assert cli(home, "apply", "--yes")["result"] == "applied"
    assert cli(home, "finalize", "--dry-run")["result"] == "would-finalize"
    finalized = cli(home, "finalize", "--yes")
    assert finalized["result"] == "finalized" and not finalized["rollback_available"]
    assert not (home / OPERATION).exists() and graphs(home) == configured
    assert {p.name: p.stat().st_mode & 0o777 for p in home.iterdir()} == {
        "00-project.cloe.toml": 0o644, "90-machine.local.cloe.toml": 0o644,
    }
    assert cli(home, "finalize", "--yes")["result"] == "nothing-to-finalize"
    assert cli(home, "rollback", "--yes")["result"] == "nothing-to-recover"
    assert cli(home, "apply", "--yes")["result"] == "already-converted"
    assert not (home / "state").exists()


def test_guarded_driver_free_cli_apply_and_rollback(tmp_path: Path) -> None:
    home = make_home(tmp_path, "postgresql")
    original = tree(home)
    harness = LocalHarness(tmp_path / "guarded", block_psycopg=True)
    for command in ("apply", "rollback"):
        result = harness.run(
            "ops", f"config-migration-{command}", "--repo-map-home", str(home), "--yes", "--json",
            extra_env={"CLOE_HOME": str(tmp_path / "wrong"), "REPOMAP_HOME": str(tmp_path / "wrong")},
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["refusals"] == []
    assert tree(home) == original and not (tmp_path / "wrong").exists()
    assert not harness.forbidden_events() and not harness.shim_invocations()
    assert "psycopg" not in harness.imported_modules()


def test_in_process_api_never_touches_source_roots_or_databases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "private.txt").write_text("source-read-tripwire")
    home = make_home(tmp_path, "sqlite", source)
    original = tree(home)

    def guarded(operation: Callable[..., Any]) -> Callable[..., Any]:
        def invoke(path: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)).absolute().is_relative_to(source):
                raise AssertionError("source filesystem was accessed")
            return operation(path, *args, **kwargs)
        return invoke

    monkeypatch.setitem(sys.modules, "psycopg", None)
    monkeypatch.setitem(sys.modules, "sqlite3", None)
    for owner, name in (
        (Path, "open"), (Path, "iterdir"), (Path, "stat"), (Path, "lstat"), (builtins, "open"), (io, "open"),
        (os, "open"), (os, "scandir"), (os, "listdir"), (os, "stat"), (os, "lstat"), (os, "access"),
    ):
        monkeypatch.setattr(owner, name, guarded(getattr(owner, name)))
    refused = apply_cloe_config_migration(home)
    assert refused["result"] == "refused" and refused["refusals"][0]["code"] == "confirmation-required"
    assert apply_cloe_config_migration(home, confirmed=True)["result"] == "applied"
    assert rollback_cloe_config_migration(home, dry_run=True)["result"] == "would-roll-back"
    assert rollback_cloe_config_migration(home, confirmed=True)["result"] == "rolled-back"
    assert apply_cloe_config_migration(home, confirmed=True)["result"] == "applied"
    assert finalize_cloe_config_migration(home, confirmed=True)["result"] == "finalized"
    monkeypatch.undo()
    assert sorted(tree(home)) == [".", "00-project.cloe.toml", "90-machine.local.cloe.toml"]
    assert not (home / "state").exists() and original


def test_real_owned_dual_link_and_missing_target_recover_through_cli(tmp_path: Path) -> None:
    home = make_home(tmp_path, "postgresql")
    original = tree(home)
    cli(home, "apply", "--yes")
    os.link(home / "00-project.cloe.toml", home / "00-project.rp.toml")
    (home / "90-machine.local.cloe.toml").unlink()
    assert cli(home, "apply", "--yes", code=1)["refusals"][0]["code"] == "config-migration-recovery-required"
    preview = cli(home, "rollback")
    assert preview["result"] == "would-roll-back" and preview["dry_run"]
    assert cli(home, "rollback", "--yes")["result"] == "rolled-back"
    assert tree(home) == original


def test_edited_after_apply_refuses_with_json_exit_and_retained_bytes(tmp_path: Path) -> None:
    home = make_home(tmp_path, "postgresql")
    cli(home, "apply", "--yes")
    (home / "90-machine.local.cloe.toml").write_text(OVERLAY.replace("debug", "info"))
    edited = tree(home)
    for command in ("rollback", "finalize"):
        refused = cli(home, command, "--yes", code=1)
        assert refused["result"] == "refused" and refused["journal_state"] == "applied"
        assert refused["refusals"] == [{"code": "config-migration-drift", "file": "90-machine.rpl.toml"}]
    text = run_cli_module("ops", "config-migration-rollback", "--repo-map-home", str(home), "--yes")
    assert text.returncode == 1 and "configuration migration rollback refused: config-migration-drift" in text.stderr
    assert "'90-machine.rpl.toml'" in text.stdout and str(home) not in text.stdout + text.stderr
    assert tree(home) == edited


def test_cli_usage_and_unsafe_home_contracts(tmp_path: Path) -> None:
    home = make_home(tmp_path, "postgresql")
    assert run_cli_module("ops", "config-migration-apply", "--yes").returncode == 2
    assert run_cli_module("ops", "config-migration-apply", "--repo-map-home", str(home), "--yes", "--dry-run").returncode == 2
    home.chmod(0o755)
    before = tree(home)
    refused = cli(home, "apply", "--yes", code=1)
    assert refused["refusals"] == [{"code": "repo-map-home-unsafe", "file": ""}] and refused["writes_performed"] == 0
    assert tree(home) == before
