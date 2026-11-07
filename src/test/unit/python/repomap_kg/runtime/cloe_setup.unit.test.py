"""Runtime producer compatibility; no container or database execution."""
from __future__ import annotations

import os
import json
from pathlib import Path

import pytest

from common_lore_index.ops.config_loading import load_ops_config_home
from common_lore_index.runtime.local import query_local_runtime_status, setup_local_runtime
from common_lore_index.runtime.plan import LocalRuntimeError


def snapshot(home: Path) -> dict[str, bytes]:
    return {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()}


def test_explicit_cloe_setup_produces_loadable_private_overlay(tmp_path: Path) -> None:
    home = tmp_path / "home"
    result = setup_local_runtime(home, config_format="cloe")
    target = home / "repomap.local.cloe.toml"
    assert result.result == "success" and target.is_file()
    assert target.stat().st_mode & 0o777 == 0o600
    assert home.stat().st_mode & 0o777 == 0o700
    assert not (home / "repomap.rpl.toml").exists()
    config = load_ops_config_home(home)
    assert config.config_files == (target.name,)
    assert result.plan.identity == query_local_runtime_status(home).plan.identity
    text = (home / "runtime/compose.yaml").read_text()
    assert f'source: "{target}"' in text
    assert 'target: "/repo-map-home/repomap.local.cloe.toml"' in text


def test_existing_cloe_home_selects_cloe_without_an_option(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    original = home / "00.cloe.toml"
    original.write_text("schema_version = 1\n")
    result = setup_local_runtime(home)
    assert result.plan.config is not None
    assert result.plan.config.config_files == ("00.cloe.toml", "repomap.local.cloe.toml")
    assert original.read_text() == "schema_version = 1\n"
    assert not (home / "repomap.rpl.toml").exists()


@pytest.mark.parametrize("existing,requested", [("00.rp.toml", "cloe"), ("00.cloe.toml", "legacy")])
def test_explicit_conflict_refuses_before_runtime_writes(tmp_path: Path, existing: str, requested: str) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    (home / existing).write_text("schema_version = 1\n")
    before = snapshot(home)
    with pytest.raises(LocalRuntimeError) as raised:
        setup_local_runtime(home, config_format=requested)
    assert raised.value.diagnostics[0].code == "runtime-config-format-conflict"
    assert snapshot(home) == before and not (home / "runtime").exists()


@pytest.mark.parametrize("suffix", [".rp.toml", ".cloe.toml"])
def test_known_sqlite_home_refused_without_backend_switch(tmp_path: Path, suffix: str) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    (home / ("00" + suffix)).write_text('schema_version = 1\n[storage]\nbackend = "sqlite"\n')
    before = snapshot(home)
    with pytest.raises(LocalRuntimeError) as raised:
        setup_local_runtime(home)
    assert raised.value.diagnostics[0].code == "sqlite-local-home-requires-local-command"
    assert snapshot(home) == before and not (home / "runtime").exists()


def test_repeat_setup_preserves_overlay_and_secret_bytes(tmp_path: Path) -> None:
    setup_local_runtime(tmp_path, config_format="cloe")
    overlay = tmp_path / "repomap.local.cloe.toml"
    overlay.write_text(overlay.read_text() + "\n# operator note\n")
    before = snapshot(tmp_path)
    result = setup_local_runtime(tmp_path, config_format="cloe")
    assert snapshot(tmp_path) == before
    assert result.created_files == ()
    assert "config-exists" in {d.code for d in result.diagnostics}


@pytest.mark.parametrize("family", ["legacy", "cloe"])
@pytest.mark.parametrize("kind", ["directory", "symlink", "broken-symlink", "case-alias"])
def test_unsafe_generated_target_refused_before_other_files(tmp_path: Path, kind: str, family: str) -> None:
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    target = home / ("repomap.local.cloe.toml" if family == "cloe" else "repomap.rpl.toml")
    outside = tmp_path / "untouched"
    if kind == "directory":
        target.mkdir()
    elif kind == "case-alias":
        (home / target.name.upper()).write_text("unchanged")
    else:
        if kind == "symlink":
            outside.write_text("unchanged")
        target.symlink_to(outside)
    before = snapshot(home)
    with pytest.raises(LocalRuntimeError) as raised:
        setup_local_runtime(home, config_format=family)
    expected = "runtime-config-target-collision" if kind == "case-alias" else "runtime-config-target-unsafe"
    assert raised.value.diagnostics[0].code == expected
    assert snapshot(home) == before
    assert not (home / "runtime").exists()
    if outside.exists():
        assert outside.read_text() == "unchanged"


def test_invalid_format_is_refused_without_creating_home(tmp_path: Path) -> None:
    home = tmp_path / "absent"
    with pytest.raises(LocalRuntimeError) as raised:
        setup_local_runtime(home, config_format="unsupported")
    assert raised.value.diagnostics[0].code == "runtime-config-format-invalid"
    assert not home.exists()


def test_cloe_dry_run_never_creates_or_chmods(tmp_path: Path) -> None:
    home = tmp_path / "absent"
    result = setup_local_runtime(home, dry_run=True, config_format="cloe")
    assert result.result == "dry_run" and not home.exists()
    assert "setup-config-format-cloe" in {d.code for d in result.diagnostics}
    home.mkdir(mode=0o755)
    setup_local_runtime(home, dry_run=True, config_format="cloe")
    assert home.stat().st_mode & 0o777 == 0o755 and list(home.iterdir()) == []


def test_cloe_private_config_creation_ignores_permissive_umask(tmp_path: Path) -> None:
    previous = os.umask(0)
    try:
        setup_local_runtime(tmp_path / "home", config_format="cloe")
    finally:
        os.umask(previous)
    assert (tmp_path / "home/repomap.local.cloe.toml").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("choice", [None, "legacy", "cloe"])
def test_mixed_home_refuses_without_setup_state(tmp_path: Path, choice: str | None) -> None:
    for name in ("00.rp.toml", "00.cloe.toml"):
        (tmp_path / name).write_text("schema_version = 1\n")
    before = snapshot(tmp_path)
    with pytest.raises(LocalRuntimeError) as raised:
        setup_local_runtime(tmp_path, config_format=choice)
    assert raised.value.diagnostics[0].code == "config-home-mixed-format"
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("payload", ['schema_version = "private-sentinel"\n', 'schema_version = 1\n[storage]\nbackend = "unknown-private-sentinel"\n'])
def test_invalid_cloe_input_is_refused_without_echoing_values(tmp_path: Path, payload: str) -> None:
    (tmp_path / "00.cloe.toml").write_text(payload)
    before = snapshot(tmp_path)
    with pytest.raises(LocalRuntimeError) as raised:
        setup_local_runtime(tmp_path)
    assert "private-sentinel" not in str(raised.value)
    assert snapshot(tmp_path) == before


def test_existing_target_with_foreign_owner_is_not_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from common_lore_index.runtime.setup_config import create_setup_config

    target = tmp_path / "repomap.local.cloe.toml"
    target.write_text("unchanged")
    monkeypatch.setattr(os, "getuid", lambda: target.stat().st_uid + 1)
    with pytest.raises(LocalRuntimeError):
        create_setup_config(target, "replacement")
    assert target.read_text() == "unchanged"


@pytest.mark.parametrize("family", ["legacy", "cloe"])
def test_dry_run_command_replays_the_selected_format(tmp_path: Path, family: str) -> None:
    from common_lore_index.cli.parser import build_parser

    home = tmp_path / "absent"
    result = setup_local_runtime(home, dry_run=True, config_format=family)
    assert not home.exists()
    assert str(home) not in json.dumps(result.to_jsonable())
    assert result.planned_command[-2:] == ("--config-format", family)
    args = build_parser().parse_args(result.planned_command)
    setup_local_runtime(args.repo_map_home, config_format=args.config_format)
    expected = "repomap.local.cloe.toml" if family == "cloe" else "repomap.rpl.toml"
    assert (home / expected).is_file()


@pytest.mark.parametrize("payload", ['schema_version = "bad-schema"\n', 'broken = "unterminated\n', 'schema_version = 1\n[storage]\nbackend = "unknown"\n', 'schema_version = 1\nstorage = 1\n'])
def test_legacy_bootstrap_retains_tolerance_and_existing_bytes(tmp_path: Path, payload: str) -> None:
    target = tmp_path / "repomap.rpl.toml"
    target.write_text(payload)
    assert setup_local_runtime(tmp_path).result == "success"
    assert target.read_text() == payload


def test_legacy_wrapped_read_failure_keeps_bootstrap_tolerance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "repomap.rpl.toml"
    target.write_text("schema_version = 1\n")
    original = Path.read_text
    calls: list[Path] = []
    def refusing(path: Path, *args, **kwargs):
        if path == target:
            calls.append(path)
            raise PermissionError("private-sentinel")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", refusing)
    assert setup_local_runtime(tmp_path).result == "success"
    assert calls and all(path == target for path in calls)
    assert target.read_bytes() == b"schema_version = 1\n"


@pytest.mark.parametrize("kind", ["directory", "broken-link"])
def test_nonfile_legacy_base_entries_remain_ignored(tmp_path: Path, kind: str) -> None:
    base = tmp_path / "00.rp.toml"
    if kind == "directory":
        base.mkdir()
    else:
        base.symlink_to(tmp_path / "absent")
    assert setup_local_runtime(tmp_path).result == "success"
    assert (tmp_path / "repomap.rpl.toml").is_file()


@pytest.mark.parametrize("family", ["legacy", "cloe"])
def test_undecodable_configuration_is_bounded_before_runtime_writes(tmp_path: Path, family: str) -> None:
    target = tmp_path / ("repomap.rpl.toml" if family == "legacy" else "repomap.local.cloe.toml")
    target.write_bytes(b"\xffprivate-sentinel")
    with pytest.raises(LocalRuntimeError) as raised:
        setup_local_runtime(tmp_path)
    assert raised.value.diagnostics[0].code == "runtime-config-unavailable"
    assert "private-sentinel" not in str(raised.value)
    assert not (tmp_path / "runtime").exists()


def test_later_cloe_overlay_preserves_effective_operator_settings(tmp_path: Path) -> None:
    from common_lore_index.runtime.plan import default_repomap_rpl_toml

    (tmp_path / "00.cloe.toml").write_text(default_repomap_rpl_toml())
    override = tmp_path / "zz.local.cloe.toml"
    content = 'schema_version = 1\n[postgres]\ndatabase = "fixture_database"\n[runtime]\nserver_host_port = 55997\n'
    override.write_text(content)
    before = load_ops_config_home(tmp_path)
    result = setup_local_runtime(tmp_path)
    after = load_ops_config_home(tmp_path)
    assert before.postgres.database == after.postgres.database == result.plan.database == "fixture_database"
    assert before.runtime.server_host_port == after.runtime.server_host_port == result.plan.server_host_port == 55997
    assert override.read_text() == content


@pytest.mark.parametrize("family", ["legacy", "cloe"])
def test_owned_existing_target_permissions_are_preserved(tmp_path: Path, family: str) -> None:
    setup_local_runtime(tmp_path, config_format=family)
    target = tmp_path / ("repomap.rpl.toml" if family == "legacy" else "repomap.local.cloe.toml")
    before = target.read_bytes()
    target.chmod(0o644)
    result = setup_local_runtime(tmp_path)
    assert target.read_bytes() == before and target.stat().st_mode & 0o777 == 0o644
    assert str(tmp_path) not in json.dumps(result.to_jsonable())


@pytest.mark.parametrize("dry_run", [True, False])
def test_unfinished_config_migration_blocks_setup_before_writes(tmp_path: Path, dry_run: bool) -> None:
    from common_lore_index.ops.config_migration import apply_cloe_config_migration

    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    (home / "00.rp.toml").write_text("schema_version = 1\n")
    assert apply_cloe_config_migration(home, confirmed=True)["result"] == "applied"
    before = {str(p.relative_to(home)): p.lstat().st_mode for p in home.rglob("*")}
    with pytest.raises(LocalRuntimeError) as raised:
        setup_local_runtime(home, dry_run=dry_run)
    assert raised.value.diagnostics[0].code == "config-migration-in-progress"
    assert {str(p.relative_to(home)): p.lstat().st_mode for p in home.rglob("*")} == before
    assert not (home / "runtime").exists() and not (home / "repomap.local.cloe.toml").exists()
