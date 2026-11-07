"""Real CLI/configuration compatibility without a database or home migration."""
from __future__ import annotations

import builtins
from collections.abc import Callable
import io
import json
import os
from pathlib import Path
import sys
from typing import Any

import pytest

from common_lore_index.cli.main import main as cli_main
from repomap_test_support.cli_integration import OPS_CONFIG_TEMPLATE, run_cli_module
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.sqlite_local_fixtures import graph_toml, sqlite_home_toml
from repomap_test_support.sqlite_local_harness import LocalHarness, initialize, structured, tool


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("backend", ["postgresql", "sqlite"])
def test_cloe_home_real_cli_layering_and_no_mutation(tmp_path: Path, backend: str) -> None:
    home = tmp_path / "home with spaces"
    home.mkdir()
    content = OPS_CONFIG_TEMPLATE if backend == "postgresql" else sqlite_home_toml(
        graph_toml("one", "/not-read/source")
    )
    (home / "90-project.cloe.toml").write_text(content)
    (home / "00-private.local.cloe.toml").write_text('schema_version = 1\n[service]\nlog_level = "debug"\n')
    before = _snapshot(tmp_path)
    checked = run_cli_module("ops", "config-check", "--repo-map-home", str(home), "--json")
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["valid"] is True
    planned = run_cli_module("ops", "config-migration-plan", "--repo-map-home", str(home), "--json")
    assert planned.returncode == 0, planned.stderr
    payload = json.loads(planned.stdout)
    assert payload["source_order"] == ["90-project.cloe.toml", "00-private.local.cloe.toml"]
    assert payload["conversion_required"] is False
    assert payload["changes"] == []
    assert str(tmp_path) not in planned.stdout
    assert _snapshot(tmp_path) == before
    assert not (home / "state").exists()


@pytest.mark.parametrize("unsafe", [False, True])
def test_real_cli_plans_legacy_names_and_refuses_unsafe_conversion(tmp_path: Path, unsafe: bool) -> None:
    names = ("x.local.rp.toml", "x.rpl.toml") if unsafe else ("00-project.rp.toml", "90-private.rpl.toml")
    (tmp_path / names[0]).write_text(OPS_CONFIG_TEMPLATE.replace(
        'password_env = "REPOMAP_PG_PASSWORD"', 'password = "private-plan-sentinel"'
    ))
    (tmp_path / names[1]).write_text("schema_version = 1\n")
    before = _snapshot(tmp_path)
    result = run_cli_module("ops", "config-migration-plan", "--repo-map-home", str(tmp_path), "--json")
    assert result.returncode == (1 if unsafe else 0), result.stderr
    payload = json.loads(result.stdout)
    assert payload["filename_conversion_ready"] is not unsafe
    assert payload["writes_performed"] == 0 and payload["apply_supported"] is False
    assert "private-plan-sentinel" not in result.stdout + result.stderr
    assert str(tmp_path) not in result.stdout
    assert _snapshot(tmp_path) == before


def test_real_cli_refuses_mixed_formats_and_invalid_schema(tmp_path: Path) -> None:
    (tmp_path / "legacy.rp.toml").write_text("schema_version = 1\n")
    new = tmp_path / "new.cloe.toml"
    new.write_text("schema_version = 1\n")
    result = run_cli_module("ops", "config-migration-plan", "--repo-map-home", str(tmp_path), "--json")
    assert result.returncode == 1 and not result.stdout
    assert "config-home-mixed-format" in result.stderr
    new.unlink()
    (tmp_path / "legacy.rp.toml").write_text("schema_version = 999\n")
    result = run_cli_module("ops", "config-migration-plan", "--repo-map-home", str(tmp_path), "--json")
    assert result.returncode == 1 and not result.stdout
    assert "schema" in result.stderr


def test_planner_honors_new_home_without_storage_dispatch_or_source_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    home, source = tmp_path / "cloe home", tmp_path / "source"
    home.mkdir()
    source.mkdir()
    (source / "private.txt").write_text("source-read-tripwire")
    (home / "00.cloe.toml").write_text(sqlite_home_toml(graph_toml("one", source)))
    monkeypatch.setenv("CLOE_HOME", str(home))
    monkeypatch.setenv("REPOMAP_HOME", str(tmp_path / "wrong"))
    def guarded(operation: Callable[..., Any]) -> Callable[..., Any]:
        def invoke(path: Any, *args: Any, **kwargs: Any) -> Any:
            if isinstance(path, (str, bytes, os.PathLike)) and Path(os.fsdecode(path)).absolute().is_relative_to(source):
                raise AssertionError("source filesystem was accessed")
            return operation(path, *args, **kwargs)
        return invoke

    def no_storage_dispatch(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("storage dispatch was reached")

    monkeypatch.setitem(sys.modules, "psycopg", None)
    monkeypatch.setitem(sys.modules, "psycopg.pq", None)
    for owner, name in (
        (Path, "open"), (Path, "iterdir"), (Path, "stat"), (Path, "lstat"),
        (builtins, "open"), (io, "open"), (os, "open"),
        (os, "scandir"), (os, "listdir"), (os, "stat"), (os, "lstat"), (os, "access"),
    ):
        monkeypatch.setattr(owner, name, guarded(getattr(owner, name)))
    monkeypatch.setitem(cli_main.__globals__, "dispatch_ops_sqlite_command", no_storage_dispatch)
    code, stdout, stderr = run_repo_map_in_process("ops", "config-migration-plan", "--json")
    assert code == 0 and stderr == ""
    assert json.loads(stdout)["source_format"] == "cloe"
    assert "source-read-tripwire" not in stdout
    assert not (home / "state").exists()


def test_fresh_guarded_server_planning_never_imports_driver(tmp_path: Path) -> None:
    home = tmp_path / "server home"
    home.mkdir()
    (home / "00.rp.toml").write_text(OPS_CONFIG_TEMPLATE)
    before = _snapshot(home)
    harness = LocalHarness(tmp_path / "guarded", block_psycopg=True)
    result = harness.run(
        "ops", "config-migration-plan", "--json",
        extra_env={"CLOE_HOME": str(home), "REPOMAP_HOME": str(tmp_path / "wrong")},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["filename_conversion_ready"] is True
    assert not harness.forbidden_events() and not harness.shim_invocations()
    assert "psycopg" not in harness.imported_modules()
    assert _snapshot(home) == before


def test_cloe_home_owns_local_state_with_driver_unavailable(tmp_path: Path) -> None:
    home = tmp_path / "cloe home"
    home.mkdir()
    (home / "00.cloe.toml").write_text(sqlite_home_toml(graph_toml("one", "/not-read/source")))
    harness = LocalHarness(tmp_path / "guarded", block_psycopg=True)
    result = harness.run(
        "ops", "sqlite-init", "--graph", "one", "--json",
        extra_env={"CLOE_HOME": str(home), "REPOMAP_HOME": str(tmp_path / "wrong")},
    )
    assert result.returncode == 0, result.stderr
    assert (home / "state/sqlite-local/graphs/one.sqlite3").is_file()
    assert not (tmp_path / "wrong").exists()
    assert not harness.forbidden_events() and not harness.shim_invocations()


@pytest.mark.parametrize("invalid", ['schema_version = "private-error-sentinel"\n', 'password = "private-error-sentinel\n'])
def test_invalid_input_stderr_never_echoes_values_or_home(tmp_path: Path, invalid: str) -> None:
    (tmp_path / "00.rp.toml").write_text(invalid)
    result = run_cli_module("ops", "config-migration-plan", "--repo-map-home", str(tmp_path), "--json")
    assert result.returncode == 1 and result.stdout == ""
    assert "private-error-sentinel" not in result.stderr
    assert str(tmp_path) not in result.stderr
    assert "configuration filename plan refused" in result.stderr


@pytest.mark.parametrize("kind", ["directory", "broken-symlink"])
def test_existing_non_file_target_is_refused(tmp_path: Path, kind: str) -> None:
    (tmp_path / "00-project.rp.toml").write_text("schema_version = 1\n")
    target = tmp_path / "00-project.cloe.toml"
    if kind == "directory":
        target.mkdir()
    else:
        target.symlink_to(tmp_path / "absent")
    result = run_cli_module("ops", "config-migration-plan", "--repo-map-home", str(tmp_path), "--json")
    assert result.returncode == 1, result.stderr
    assert "target-already-exists" in {item["code"] for item in json.loads(result.stdout)["refusals"]}
    assert target.is_dir() if kind == "directory" else target.is_symlink()


def test_explicit_mcp_home_wins_in_a_fresh_driver_free_process(tmp_path: Path) -> None:
    home = tmp_path / "explicit home"
    home.mkdir()
    (home / "00.cloe.toml").write_text(sqlite_home_toml(graph_toml("one", "/not-read/source")))
    harness = LocalHarness(tmp_path / "guarded", block_psycopg=True)
    responses = harness.mcp(
        home, [initialize(1), tool(2, "repomap_list_graphs", {})],
        extra_env={"CLOE_HOME": str(tmp_path / "wrong ambient")},
    )
    payload = structured(responses, 2)
    assert [graph["graph_id"] for graph in payload["graphs"]] == ["one"]
    assert not harness.forbidden_events() and not harness.shim_invocations()
    assert not (tmp_path / "wrong ambient").exists()


def test_guarded_harness_scrubs_ambient_cloe_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOE_HOME", str(tmp_path / "unselected"))
    harness = LocalHarness(tmp_path / "guarded", block_psycopg=True)
    assert "CLOE_HOME" not in harness.environment()
    assert harness.environment({"CLOE_HOME": "selected"})["CLOE_HOME"] == "selected"


def test_runtime_setup_refusal_preserves_cloe_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    (home / "00.cloe.toml").write_text(sqlite_home_toml(graph_toml("one", "/not-read/source")))
    before = _snapshot(home)
    harness = LocalHarness(tmp_path / "guarded")
    result = harness.run("local", "setup", "--repo-map-home", str(home), "--json")
    assert result.returncode == 1, result.stderr
    assert "sqlite-local-home-requires-local-command" in result.stderr, result.stderr
    assert _snapshot(home) == before
    assert sorted(p.name for p in home.iterdir()) == ["00.cloe.toml"]
    assert not harness.forbidden_events() and not harness.shim_invocations()
