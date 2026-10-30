"""Real default selection, retained Local state and stdio compatibility."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import stat

import pytest

from repomap_test_support.cli_integration import OPS_CONFIG_TEMPLATE, run_cli_module
from repomap_test_support.sqlite_local_fixtures import graph_toml, sqlite_home_toml
from repomap_test_support.sqlite_local_harness import LocalHarness, initialize, tool
from repomap_kg.runtime.plan import LOCAL_RUNTIME_ENV_FILE


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = tmp_path / "user with spaces"
    root.mkdir()
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.setenv("CLOE_HOME", "")
    monkeypatch.setenv("REPOMAP_HOME", "")
    return root / ".cloe", root / ".repo-map"


@pytest.mark.parametrize("foreign_new", [False, True])
def test_default_legacy_json_and_mcp_readback_preserve_existing_sqlite_state(tmp_path: Path, foreign_new: bool) -> None:
    harness = LocalHarness(tmp_path / "guarded with spaces", block_psycopg=True)
    home = harness.user_home / ".repo-map"
    home.mkdir(mode=0o700)
    (home / "00.rp.toml").write_text(sqlite_home_toml(graph_toml("one", "/not-read/source")))
    initialized = harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", "one", "--json")
    assert initialized.returncode == 0, initialized.stderr
    current = harness.user_home / ".cloe"
    if foreign_new:
        current.mkdir()
        (current / "language-state").write_text("foreign opaque sentinel")
    cold = snapshot(harness.user_home)
    planned = harness.run("ops", "config-migration-plan", "--json")
    assert planned.returncode == 0, planned.stderr
    assert json.loads(planned.stdout)["writes_performed"] == 0
    assert snapshot(harness.user_home) == cold  # Selection/configuration does not open SQLite.
    # Establish ordinary SQLite reader sidecars with the explicit incumbent route.
    warm = harness.run("ops", "graphs", "--repo-map-home", str(home), "--check-db", "--json")
    assert warm.returncode == 0, warm.stderr
    before = snapshot(harness.user_home)
    implicit = harness.run("ops", "graphs", "--check-db", "--json")
    explicit = harness.run("ops", "graphs", "--repo-map-home", str(home), "--check-db", "--json")
    assert implicit.returncode == explicit.returncode == 0, implicit.stderr + explicit.stderr
    assert implicit.stdout == explicit.stdout
    status = json.loads(implicit.stdout)["graphs"][0]["storage_status"]
    assert status["state"] == "current" and status["accepted_generation"] is None
    assert "legacy-default-home" in implicit.stderr and "legacy-default-home" not in explicit.stderr
    assert str(home) not in implicit.stderr and "foreign opaque sentinel" not in implicit.stderr
    payload = "".join(json.dumps(item) + "\n" for item in (
        initialize(), tool(2, "repomap_graph_status", {"graph_id": "one"}),
    ))
    served = harness.run("mcp", "serve", input_text=payload)
    served_explicit = harness.run("mcp", "serve", "--repo-map-home", str(home), input_text=payload)
    assert served.returncode == 0, served.stderr
    assert served_explicit.returncode == 0 and served.stdout == served_explicit.stdout
    responses = [json.loads(line) for line in served.stdout.splitlines() if line.strip()]
    assert [item["id"] for item in responses] == [1, 2]
    assert not responses[1]["result"].get("isError", False)
    after = snapshot(harness.user_home)
    assert after == before, {"added": sorted(after.keys() - before.keys()),
                             "removed": sorted(before.keys() - after.keys()),
                             "changed": sorted(name for name in before.keys() & after.keys() if before[name] != after[name])}
    assert not harness.forbidden_events() and not harness.shim_invocations()
    assert "psycopg" not in harness.imported_modules()
    if not foreign_new:
        assert not current.exists()


def test_fresh_default_setup_is_cloe_private_and_dry_run_replayable(tmp_path: Path, monkeypatch) -> None:
    current, legacy = defaults(tmp_path, monkeypatch)
    planned = run_cli_module("local", "setup", "--dry-run", "--json")
    assert planned.returncode == 0, planned.stderr
    assert not current.exists() and not legacy.exists()
    result = run_cli_module("local", "setup", "--json")
    assert result.returncode == 0, result.stderr
    assert (current / "repomap.local.cloe.toml").is_file()
    assert not (current / "repomap.rpl.toml").exists() and not legacy.exists()
    assert stat.S_IMODE(current.stat().st_mode) == 0o700
    assert str(tmp_path) not in result.stdout
    before = snapshot(current)
    repeated = run_cli_module("local", "setup", "--json")
    assert repeated.returncode == 0, repeated.stderr
    assert snapshot(current) == before


def test_legacy_default_setup_dry_run_never_initializes_new_home(tmp_path: Path, monkeypatch) -> None:
    current, legacy = defaults(tmp_path, monkeypatch)
    legacy.mkdir(mode=0o700)
    (legacy / "00.rp.toml").write_text(OPS_CONFIG_TEMPLATE)
    before = snapshot(legacy)
    result = run_cli_module("local", "setup", "--dry-run", "--json")
    assert result.returncode == 0, result.stderr
    assert "legacy-default-home" in result.stderr
    assert snapshot(legacy) == before and not current.exists()


@pytest.mark.parametrize("kind", ["foreign", "symlink", "fifo", "invalid"])
def test_unrecognized_new_default_refuses_without_writes_or_content_disclosure(tmp_path: Path, monkeypatch, kind: str) -> None:
    current, legacy = defaults(tmp_path, monkeypatch)
    current.mkdir(mode=0o700)
    if kind == "symlink":
        current.rmdir()
        current.symlink_to(tmp_path, target_is_directory=True)
    elif kind == "fifo":
        os.mkfifo(current / "00.cloe.toml", 0o600)
    else:
        (current / ("00.cloe.toml" if kind == "invalid" else "language-state")).write_text("opaque private sentinel")
    before = snapshot(current) if kind not in ("fifo", "symlink") else None
    result = run_cli_module("local", "setup", "--json")
    assert result.returncode == 1 and not result.stdout
    assert "default-home-" in result.stderr
    assert "opaque private sentinel" not in result.stderr and str(tmp_path) not in result.stderr
    assert not legacy.exists()
    if before is not None:
        assert snapshot(current) == before


@pytest.mark.parametrize("operation", ["apply", "rollback", "finalize"])
def test_migration_still_requires_explicit_home_even_with_recognized_defaults(tmp_path: Path, monkeypatch, operation: str) -> None:
    current, _legacy = defaults(tmp_path, monkeypatch)
    current.mkdir(mode=0o700)
    (current / "00.cloe.toml").write_text(OPS_CONFIG_TEMPLATE)
    before = snapshot(current)
    result = run_cli_module("ops", f"config-migration-{operation}", "--yes", "--json")
    assert result.returncode == 2  # argparse retains the explicit required argument.
    assert snapshot(current) == before
    assert "explicit" in result.stderr or "required" in result.stderr


def test_two_concurrent_setups_retain_one_private_credential_and_configuration(tmp_path: Path, monkeypatch) -> None:
    current, legacy = defaults(tmp_path, monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        completed = list(pool.map(lambda _index: run_cli_module("local", "setup", "--json"), range(2)))
    assert any(item.returncode == 0 for item in completed), [item.stderr for item in completed]
    assert (current / "repomap.local.cloe.toml").is_file()
    assert (current / LOCAL_RUNTIME_ENV_FILE).is_file()
    assert stat.S_IMODE((current / LOCAL_RUNTIME_ENV_FILE).stat().st_mode) == 0o600
    assert not legacy.exists()
    assert len(list(current.glob("*.cloe.toml"))) == 1


def test_mcp_explicit_config_environment_survives_foreign_default(tmp_path: Path) -> None:
    harness = LocalHarness(tmp_path / "explicit-config", block_psycopg=True)
    home = harness.scratch / "selected-home"
    home.mkdir(mode=0o700)
    config = home / "00.rp.toml"
    config.write_text(sqlite_home_toml(graph_toml("one", "/not-read/source")))
    initialized = harness.run("ops", "sqlite-init", "--repo-map-home", str(home), "--graph", "one", "--json")
    assert initialized.returncode == 0, initialized.stderr
    current = harness.user_home / ".cloe"
    current.mkdir(mode=0o700)
    (current / "foreign.txt").write_text("opaque private sentinel")
    before = snapshot(current)
    payload = "".join(json.dumps(item) + "\n" for item in (
        initialize(), tool(2, "repomap_graph_status", {"graph_id": "one"}),
    ))
    served = harness.run("mcp", "serve", input_text=payload, extra_env={"REPOMAP_OPS_CONFIG": str(config)})
    assert served.returncode == 0, served.stderr
    responses = [json.loads(line) for line in served.stdout.splitlines() if line.strip()]
    assert [item["id"] for item in responses] == [1, 2]
    assert not responses[1]["result"].get("isError", False)
    assert not served.stderr and snapshot(current) == before
    assert not (harness.user_home / ".repo-map").exists()
    assert not harness.forbidden_events() and not harness.shim_invocations()


@pytest.mark.parametrize("operation", ["up_local_runtime", "down_local_runtime", "query_local_runtime_status"])
def test_runtime_api_refuses_implicit_foreign_home_before_runtime_work(tmp_path: Path, monkeypatch, operation: str) -> None:
    from repomap_kg.runtime import local
    current, legacy = defaults(tmp_path, monkeypatch)
    current.mkdir(mode=0o700)
    (current / "foreign.txt").write_text("opaque private sentinel")
    before = snapshot(current)
    with pytest.raises(local.LocalRuntimeError) as raised:
        getattr(local, operation)()
    assert raised.value.diagnostics[0].code == "default-home-unrecognized"
    assert "opaque private sentinel" not in str(raised.value) and str(tmp_path) not in str(raised.value)
    assert snapshot(current) == before and not legacy.exists()
