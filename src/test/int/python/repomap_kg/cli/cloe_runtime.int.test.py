"""Real CLI CLOE runtime configuration production in the disposable sandbox."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from repomap_test_support.cli_integration import run_cli_module
from repomap_test_support.sqlite_local_harness import LocalHarness


def snapshot(home: Path) -> dict[str, bytes]:
    return {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()}


def test_cloe_setup_readback_status_and_plan_without_runtime_execution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "cloe home"
    harness = LocalHarness(tmp_path / "guard")
    result = harness.run("local", "setup", "--repo-map-home", str(home), "--config-format", "cloe", "--json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["result"] == "success"
    assert "setup-config-format-cloe" in {d["code"] for d in payload["diagnostics"]}
    assert str(home) not in result.stdout
    overlay = home / "repomap.local.cloe.toml"
    assert overlay.is_file() and not (home / "repomap.rpl.toml").exists()
    assert overlay.stat().st_mode & 0o777 == 0o600
    compose = (home / "runtime/compose.yaml").read_text()
    assert 'target: "/repo-map-home/repomap.local.cloe.toml"' in compose
    assert '/repo-map-home/repomap.rpl.toml' not in compose
    before = snapshot(home)
    for command in [("ops", "config-check"), ("local", "status")]:
        checked = harness.run(*command, "--repo-map-home", str(home), "--json")
        assert checked.returncode == 0, checked.stderr
        if command[0] == "ops":
            assert json.loads(checked.stdout)["valid"] is True
        else:
            assert json.loads(checked.stdout)["container_runtime_checked"] is False
    repeated = harness.run("local", "setup", "--repo-map-home", str(home), "--json")
    assert repeated.returncode == 0, repeated.stderr
    assert str(home) not in repeated.stdout
    assert snapshot(home) == before
    assert not harness.forbidden_events() and not harness.shim_invocations()
    # Port availability belongs to a normal nonexecuting runtime up plan.
    monkeypatch.setenv("PATH", str(harness.shims) + os.pathsep + os.environ.get("PATH", ""))
    planned = run_cli_module("local", "up", "--repo-map-home", str(home), "--dry-run", "--json")
    assert planned.returncode == 0, planned.stderr
    assert json.loads(planned.stdout)["result"] == "dry_run"
    assert snapshot(home) == before
    assert not harness.shim_invocations()
    assert "repomap.rpl.toml" not in (home / "runtime/repomap-server.Dockerfile").read_text()


def test_cloe_dry_run_replays_as_the_same_real_cli_format(tmp_path: Path) -> None:
    from repomap_kg.runtime.local import setup_local_runtime

    home = tmp_path / "absent"
    preview = setup_local_runtime(home, dry_run=True, config_format="cloe")
    assert not home.exists()
    result = run_cli_module(*preview.planned_command, "--json")
    assert result.returncode == 0, result.stderr
    assert (home / "repomap.local.cloe.toml").is_file()
    assert not (home / "repomap.rpl.toml").exists()


def test_cloe_home_environment_selects_the_only_setup_destination(tmp_path: Path) -> None:
    home, wrong = tmp_path / "selected", tmp_path / "unselected"
    harness = LocalHarness(tmp_path / "guard")
    result = harness.run("local", "setup", "--config-format", "cloe", "--json",
                         extra_env={"CLOE_HOME": str(home), "REPOMAP_HOME": str(wrong)})
    assert result.returncode == 0, result.stderr
    assert (home / "repomap.local.cloe.toml").is_file() and not wrong.exists()
    assert str(home) not in result.stdout
    assert not harness.forbidden_events() and not harness.shim_invocations()


@pytest.mark.parametrize("name,requested", [("00.rp.toml", "cloe"), ("00.cloe.toml", "legacy")])
def test_cli_format_conflicts_leave_existing_home_unchanged(tmp_path: Path, name: str, requested: str) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    (home / name).write_text("schema_version = 1\n")
    before = snapshot(home)
    harness = LocalHarness(tmp_path / "guard")
    result = harness.run("local", "setup", "--repo-map-home", str(home), "--config-format", requested, "--json")
    assert result.returncode == 1, result.stderr
    assert "runtime-config-format-conflict" in result.stderr
    assert snapshot(home) == before and not (home / "runtime").exists()
    assert not harness.forbidden_events() and not harness.shim_invocations()


def test_cli_auto_detects_cloe_family_and_preserves_base_bytes(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    base = home / "00.cloe.toml"
    base.write_text("schema_version = 1\n# keep this base\n")
    harness = LocalHarness(tmp_path / "guard")
    result = harness.run("local", "setup", "--repo-map-home", str(home), "--json")
    assert result.returncode == 0, result.stderr
    assert base.read_text() == "schema_version = 1\n# keep this base\n"
    assert (home / "repomap.local.cloe.toml").is_file()
    assert not (home / "repomap.rpl.toml").exists()
    assert not harness.forbidden_events() and not harness.shim_invocations()


def test_cli_cloe_dry_run_creates_nothing_and_rejects_invalid_choice(tmp_path: Path) -> None:
    home = tmp_path / "absent"
    result = run_cli_module("local", "setup", "--repo-map-home", str(home), "--config-format", "cloe", "--dry-run", "--json")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"] == "dry_run"
    assert not home.exists()
    result = run_cli_module("local", "setup", "--repo-map-home", str(home), "--config-format", "invalid")
    assert result.returncode == 2 and not home.exists()


@pytest.mark.parametrize("case", ["mixed", "invalid-cloe", "sqlite-legacy", "unsafe-target"])
def test_cli_preflight_failures_preserve_home_without_secret_output(tmp_path: Path, case: str) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    if case == "mixed":
        for name in ("00.rp.toml", "00.cloe.toml"):
            (home / name).write_text("schema_version = 1\n")
    elif case == "invalid-cloe":
        (home / "00.cloe.toml").write_text('schema_version = "private-sentinel"\n')
    elif case == "sqlite-legacy":
        (home / "00.rp.toml").write_text('schema_version = 1\n[storage]\nbackend = "sqlite"\n')
    else:
        (home / "repomap.local.cloe.toml").symlink_to(tmp_path / "absent")
    before = snapshot(home)
    harness = LocalHarness(tmp_path / "guard")
    choice = ("--config-format", "cloe") if case == "unsafe-target" else ()
    result = harness.run("local", "setup", "--repo-map-home", str(home), *choice, "--json")
    assert result.returncode == 1, result.stderr
    assert "private-sentinel" not in result.stdout + result.stderr
    assert snapshot(home) == before and not (home / "runtime").exists()
    assert not harness.forbidden_events() and not harness.shim_invocations()


@pytest.mark.parametrize("dry_run", [True, False])
def test_cli_setup_refuses_an_unfinished_config_migration(tmp_path: Path, dry_run: bool) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    (home / "00.rp.toml").write_text("schema_version = 1\n")
    applied = run_cli_module("ops", "config-migration-apply", "--repo-map-home", str(home), "--yes", "--json")
    assert applied.returncode == 0, applied.stderr
    before = snapshot(home)
    harness = LocalHarness(tmp_path / "guard")
    result = harness.run("local", "setup", "--repo-map-home", str(home), *(("--dry-run",) if dry_run else ()), "--json")
    assert result.returncode == 1 and "config-migration-in-progress" in result.stderr
    assert snapshot(home) == before and not (home / "runtime").exists()
    assert not harness.forbidden_events() and not harness.shim_invocations()
