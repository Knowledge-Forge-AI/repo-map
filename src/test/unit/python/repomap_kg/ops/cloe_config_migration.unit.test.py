"""ADR 0114 apply preflight, conversion, refusals, confirmation, CLI and redaction contracts."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from typing import Any

import pytest

from repomap_kg.cli.main import main
from repomap_kg.ops import config_migration
from repomap_kg.ops.config_loading import _read_ops_config_home_payload
from repomap_kg.ops.config_migration import (
    apply_cloe_config_migration, finalize_cloe_config_migration, rollback_cloe_config_migration,
)
from repomap_kg.ops.config_migration_fs import OPERATION_DIRECTORY, Home, MigrationRefusal, owned_regular, valid_name
from repomap_test_support.sqlite_local_fixtures import graph_toml, sqlite_home_toml

SECRET = "migration-secret-sentinel"
SERVER = f'schema_version = 1\n[postgres]\nhost = "127.0.0.1"\npassword = "{SECRET}"\n'
OVERLAY = 'schema_version = 1\n[service]\nlog_level = "debug"\n'
RESULT_KEYS = {
    "schema", "operation", "result", "dry_run", "writes_performed", "changes", "source_order", "proposed_order",
    "journal_state", "refusals", "rollback_available", "finalize_pending", "operation_directory_retained",
}


def make_home(tmp_path: Path, files: dict[str, str] | None = None, mode: int = 0o700) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    defaults = {"00-project.rp.toml": SERVER, "90-machine.rpl.toml": OVERLAY}
    for name, body in (defaults if files is None else files).items():
        (home / name).write_text(body)
        (home / name).chmod(0o644)
    home.chmod(mode)
    return home


def tree(root: Path) -> dict[str, tuple[int, bytes | str | None]]:
    """Every entry's mode and content (link target for symlinks), recursively, without following."""
    found: dict[str, tuple[int, bytes | str | None]] = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        body: bytes | str | None = None
        if stat.S_ISLNK(info.st_mode):
            body = os.readlink(path)
        elif stat.S_ISREG(info.st_mode):
            body = path.read_bytes()
        found[str(path.relative_to(root))] = (info.st_mode, body)
    found["."] = (root.lstat().st_mode, None)
    return found


def codes(result: dict[str, Any]) -> list[str]:
    return [item["code"] for item in result["refusals"]]


def test_apply_converts_both_layers_preserving_bytes_mode_inode_and_effective_order(tmp_path: Path) -> None:
    home = make_home(tmp_path)
    (home / "notes.toml").write_text("unrelated = true\n")
    (home / "notes.toml").chmod(0o640)
    before = {name: (home / name).stat() for name in ("00-project.rp.toml", "90-machine.rpl.toml")}
    _, payload, files, _ = _read_ops_config_home_payload(home)
    result = apply_cloe_config_migration(home, confirmed=True)
    assert set(result) == RESULT_KEYS and result["result"] == "applied" and result["refusals"] == []
    assert result["changes"] == [
        {"source": "00-project.rp.toml", "target": "00-project.cloe.toml", "layer": "base"},
        {"source": "90-machine.rpl.toml", "target": "90-machine.local.cloe.toml", "layer": "local"},
    ]
    assert result["journal_state"] == "applied" and result["rollback_available"] and result["finalize_pending"]
    assert result["writes_performed"] > 0 and not result["dry_run"]
    for source, target in (("00-project.rp.toml", "00-project.cloe.toml"), ("90-machine.rpl.toml", "90-machine.local.cloe.toml")):
        info = (home / target).stat()
        assert not (home / source).exists()
        assert (info.st_ino, info.st_mode, info.st_nlink) == (before[source].st_ino, before[source].st_mode, 1)
    assert (home / "notes.toml").stat().st_mode & 0o777 == 0o640
    _, converted, converted_files, _ = _read_ops_config_home_payload(home)
    assert converted == payload and len(converted_files) == len(files)
    operation = home / OPERATION_DIRECTORY
    assert operation.stat().st_mode & 0o777 == 0o700
    assert sorted(p.name for p in operation.iterdir()) == ["backup-0000.bin", "backup-0001.bin", "journal.json", "lock"]
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in operation.iterdir())
    assert (operation / "backup-0000.bin").read_text() == SERVER


def test_local_sqlite_home_converts_without_state_or_source_access(tmp_path: Path) -> None:
    content = sqlite_home_toml(graph_toml("one", tmp_path / "absent-source"))
    home = make_home(tmp_path, {"repomap.rp.toml": content})
    assert apply_cloe_config_migration(home, confirmed=True)["result"] == "applied"
    _, payload, files, _ = _read_ops_config_home_payload(home)
    assert files == ("repomap.cloe.toml",) and payload["storage"] == {"backend": "sqlite"}
    assert not (home / "state").exists() and not (tmp_path / "absent-source").exists()


def test_already_converted_and_empty_operation_results_write_nothing(tmp_path: Path) -> None:
    home = make_home(tmp_path, {"00.cloe.toml": OVERLAY, "10.local.cloe.toml": OVERLAY})
    before = tree(home)
    for operation, expected in (
        (apply_cloe_config_migration, "already-converted"),
        (rollback_cloe_config_migration, "nothing-to-recover"),
        (finalize_cloe_config_migration, "nothing-to-finalize"),
    ):
        for kwargs in ({"confirmed": True}, {"dry_run": True}):
            result = operation(home, **kwargs)
            assert result["result"] == expected and result["writes_performed"] == 0
    assert tree(home) == before


@pytest.mark.parametrize("mode", [0o700, 0o750, 0o755])
def test_dry_run_and_unsafe_homes_never_write_or_chmod(tmp_path: Path, mode: int) -> None:
    home = make_home(tmp_path, mode=mode)
    before = tree(tmp_path)
    dry = apply_cloe_config_migration(home, dry_run=True)
    assert dry["result"] == ("would-apply" if mode == 0o700 else "refused")
    if mode != 0o700:
        assert codes(dry) == ["repo-map-home-unsafe"]
        assert codes(apply_cloe_config_migration(home, confirmed=True)) == ["repo-map-home-unsafe"]
    else:
        assert len(dry["changes"]) == 2 and dry["journal_state"] is None
    assert dry["writes_performed"] == 0
    assert tree(tmp_path) == before


@pytest.mark.parametrize(("home", "kwargs", "code"), [
    (None, {"confirmed": True}, "repo-map-home-required"),
    ("", {"confirmed": True}, "repo-map-home-required"),
    ("home", {}, "confirmation-required"),
    ("home", {"confirmed": True, "dry_run": True}, "confirmation-conflict"),
])
def test_api_confirmation_and_explicit_home_are_required(
    tmp_path: Path, home: str | None, kwargs: dict[str, bool], code: str,
) -> None:
    real = make_home(tmp_path)
    before = tree(real)
    selected = None if home is None else (str(real) if home else "")
    for operation in (apply_cloe_config_migration, rollback_cloe_config_migration, finalize_cloe_config_migration):
        result = operation(selected, **kwargs)
        assert result["result"] == "refused" and codes(result) == [code]
    assert tree(real) == before


def test_unopenable_home_path_is_a_refusal_not_an_exception(tmp_path: Path) -> None:
    for operation in (apply_cloe_config_migration, rollback_cloe_config_migration, finalize_cloe_config_migration):
        result = operation(f"{tmp_path}/bad\x00home", confirmed=True)
        assert result["result"] == "refused" and codes(result) == ["repo-map-home-unsafe"]


def test_unbound_created_operation_directory_is_reported_retained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = make_home(tmp_path)
    before = tree(home)

    def refuse(self: Home) -> None:
        raise MigrationRefusal("config-migration-residue-unsafe")

    monkeypatch.setattr(Home, "open_operation_directory", refuse)
    result = apply_cloe_config_migration(home, confirmed=True)
    assert codes(result) == ["config-migration-residue-unsafe"] and result["operation_directory_retained"]
    assert (home / OPERATION_DIRECTORY).is_dir()
    monkeypatch.undo()
    assert rollback_cloe_config_migration(home, confirmed=True)["result"] == "discarded" and tree(home) == before


def test_unqualified_platform_refuses_every_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = make_home(tmp_path)
    before = tree(home)
    monkeypatch.setattr(config_migration, "platform_supported", lambda: False)
    for kwargs in ({"confirmed": True}, {"dry_run": True}):
        assert codes(apply_cloe_config_migration(home, **kwargs)) == ["config-migration-platform-unsupported"]
    assert tree(home) == before


def _unsafe(home: Path, kind: str) -> str:
    if kind == "symlink":
        (home / "real.txt").write_text(OVERLAY)
        (home / "50.rp.toml").symlink_to(home / "real.txt")
    elif kind == "broken-symlink":
        (home / "50.rp.toml").symlink_to(home / "absent")
    elif kind == "directory":
        (home / "50.rp.toml").mkdir()
    elif kind == "hardlink":
        os.link(home / "00-project.rp.toml", home / "elsewhere.txt")
        return "00-project.rp.toml"
    elif kind == "fifo":
        os.mkfifo(home / "50.rp.toml")
    return "50.rp.toml"


@pytest.mark.parametrize("kind", ["symlink", "broken-symlink", "directory", "hardlink", "fifo"])
def test_unsafe_configuration_entries_refuse_before_any_write(tmp_path: Path, kind: str) -> None:
    home = make_home(tmp_path)
    name = _unsafe(home, kind)
    before = tree(home)
    result = apply_cloe_config_migration(home, confirmed=True)
    assert result["refusals"] == [{"code": "config-entry-unsafe", "file": name}]
    assert result["writes_performed"] == 0 and tree(home) == before


def test_entry_and_name_predicates_cover_foreign_owner_and_unencodable_names(tmp_path: Path) -> None:
    path = tmp_path / "f"
    path.write_text("x")
    info = path.lstat()
    foreign = os.stat_result((info.st_mode, info.st_ino, info.st_dev, 1, info.st_uid + 1, info.st_gid, 1, 0, 0, 0))
    setuid = os.stat_result((info.st_mode | stat.S_ISUID, *tuple(info)[1:10]))
    assert owned_regular(info) and not owned_regular(foreign) and not owned_regular(setuid)
    assert not valid_name("bad\udcff.rp.toml") and not valid_name("x" * 250 + ".rp.toml")


@pytest.mark.parametrize(("files", "expected"), [
    ({}, [("config-home-empty", "")]),
    ({"a.rp.toml": OVERLAY, "b.cloe.toml": OVERLAY}, [("config-home-mixed-format", "")]),
    ({"x.local.rp.toml": OVERLAY, "x.rpl.toml": OVERLAY}, None),
    ({"base.extra.rp.toml": OVERLAY, "base.rp.toml": OVERLAY}, [("layer-order-changed", "")]),
    ({"00-project.rp.toml": OVERLAY, "00-PROJECT.CLOE.TOML": "x"}, [("target-already-exists", "00-project.cloe.toml")]),
    ({"00.rp.toml": OVERLAY, ".CLOE-Config-Migration": "x"}, [("config-migration-alias-collision", ".CLOE-Config-Migration")]),
    ({"x" * 246 + ".rp.toml": OVERLAY}, [("config-filename-unsupported", "x" * 246 + ".rp.toml")]),
    ({"00.rp.toml": "schema_version = [\n"}, [("invalid-toml", "00.rp.toml")]),
    ({"00.rp.toml": "schema_version = 999\n"}, [("unsupported-schema-version", "00.rp.toml")]),
    ({"00.rp.toml": 'schema_version = 1\n[storage]\nbackend = "sqlite"\n', "10.rpl.toml": SERVER},
     [("storage-backend-conflict", "")]),
    ({"00.rp.toml": 'schema_version = 1\n[storage]\nbackend = "other"\n'}, [("unsupported-storage-backend", "")]),
])
def test_home_and_plan_refusals_are_stable_and_write_nothing(
    tmp_path: Path, files: dict[str, str], expected: list[tuple[str, str]] | None,
) -> None:
    home = make_home(tmp_path, files)
    before = tree(home)
    result = apply_cloe_config_migration(home, confirmed=True)
    assert result["result"] == "refused" and result["writes_performed"] == 0
    if expected is None:
        assert {"target-collision", "base-became-local"} <= set(codes(result))
    else:
        assert [(item["code"], item["file"]) for item in result["refusals"]] == expected
    assert tree(home) == before


def test_limits_refuse_before_reading_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = make_home(tmp_path)
    monkeypatch.setattr(config_migration, "MAX_CONFIG_FILES", 1)
    assert codes(apply_cloe_config_migration(home, dry_run=True)) == ["config-migration-limit-exceeded"]
    monkeypatch.setattr(config_migration, "MAX_CONFIG_FILES", 64)
    monkeypatch.setattr(config_migration, "MAX_FILE_BYTES", 8)
    assert apply_cloe_config_migration(home, dry_run=True)["refusals"] == [
        {"code": "config-migration-limit-exceeded", "file": "00-project.rp.toml"}
    ]


def test_cli_dry_run_default_json_contract_and_redaction(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = make_home(tmp_path)
    before = tree(home)
    assert main(["ops", "config-migration-apply", "--repo-map-home", str(home), "--json"]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dry["result"] == "would-apply" and dry["dry_run"] and tree(home) == before
    assert main(["ops", "config-migration-apply", "--repo-map-home", str(home), "--yes", "--json"]) == 0
    rendered = capsys.readouterr()
    applied = json.loads(rendered.out)
    assert set(applied) == RESULT_KEYS and applied["schema"] == "cloe-config-migration-result-v1"
    journal = (home / OPERATION_DIRECTORY / "journal.json").read_text()
    for text in (rendered.out, rendered.err, journal):
        assert SECRET not in text and str(tmp_path) not in text
    assert set(json.loads(journal)) >= {"entries", "effective_sha256"}
    assert main(["ops", "config-migration-finalize", "--repo-map-home", str(home), "--yes"]) == 0
    text = capsys.readouterr().out
    assert "finalize: finalized" in text and SECRET not in text and str(tmp_path) not in text


def test_cli_text_escapes_names_and_refusals_use_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = make_home(tmp_path, {"a\x1bb.rp.toml": OVERLAY})
    assert main(["ops", "config-migration-apply", "--repo-map-home", str(home)]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "'a\\x1bb.rp.toml' -> 'a\\x1bb.cloe.toml' (base)" in out
    assert "Dry run; no files or data changed" in out
    (home / "b.cloe.toml").write_text(OVERLAY)
    assert main(["ops", "config-migration-apply", "--repo-map-home", str(home), "--yes"]) == 1
    rendered = capsys.readouterr()
    assert "configuration migration apply refused: config-home-mixed-format" in rendered.err
    assert str(tmp_path) not in rendered.out + rendered.err


@pytest.mark.parametrize("argv", [
    ["ops", "config-migration-apply", "--yes"],
    ["ops", "config-migration-rollback", "--config", "x", "--yes"],
    ["ops", "config-migration-finalize", "--repo-map-home", "h", "--dry-run", "--yes"],
])
def test_cli_usage_requires_explicit_home_and_one_mode(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOE_HOME", "/nonexistent-ambient")
    with pytest.raises(SystemExit) as raised:
        main(argv)
    assert raised.value.code == 2


@pytest.mark.parametrize("backup_change", ["missing", "corrupt"])
@pytest.mark.parametrize("confirmed", [False, True])
def test_restore_scratch_is_preserved_when_backup_drift_prevents_recovery(
    tmp_path: Path, backup_change: str, confirmed: bool,
) -> None:
    home = make_home(tmp_path)
    assert apply_cloe_config_migration(home, confirmed=True)["result"] == "applied"
    operation = home / OPERATION_DIRECTORY
    backup = operation / "backup-0000.bin"
    (operation / "restore-0000.tmp").write_bytes(backup.read_bytes())
    (home / "00-project.cloe.toml").unlink()
    if backup_change == "missing":
        backup.unlink()
    else:
        backup.write_bytes(b"changed-backup")
    before = tree(home)
    result = rollback_cloe_config_migration(home, confirmed=confirmed, dry_run=not confirmed)
    assert result["result"] == "refused"
    assert codes(result) == ["config-migration-drift"]
    assert tree(home) == before
    assert result["writes_performed"] == 0
