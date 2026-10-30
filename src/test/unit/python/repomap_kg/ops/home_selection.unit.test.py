"""Default-home ownership and precedence without a database or private runtime."""
from pathlib import Path
import os

import pytest

from common_lore_index.ops.config_loading import _resolve_home_selection, resolve_repo_map_home
from common_lore_index.ops.config_records import OpsConfigError
from common_lore_index.ops import home_selection

SQLITE = 'schema_version = 1\n[storage]\nbackend = "sqlite"\n'
POSTGRES = 'schema_version = 1\n[postgres]\nhost = "localhost"\ndatabase = "fixture"\nuser = "fixture"\n'


@pytest.fixture
def defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = tmp_path / "user with spaces"
    root.mkdir()
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.delenv("CLOE_HOME", raising=False)
    monkeypatch.delenv("REPOMAP_HOME", raising=False)
    return root / ".cloe", root / ".repo-map"


def populate(path: Path, kind: str) -> None:
    if kind == "absent":
        return
    if kind == "file":
        path.write_text("opaque foreign material")
        return
    path.mkdir(mode=0o700)
    if kind == "empty":
        return
    if kind == "foreign":
        (path / "foreign.txt").write_text("opaque foreign material")
        return
    name = "00-project.cloe.toml" if path.name == ".cloe" else "00-project.rp.toml"
    content = POSTGRES if kind == "postgres" else SQLITE
    if kind == "invalid":
        content = 'schema_version = 999\n[storage]\nbackend = "sqlite"\n'
    (path / name).write_text(content)


@pytest.mark.parametrize(("new", "old", "source"), [
    ("absent", "absent", "fresh-default"), ("empty", "absent", "fresh-default"),
    ("sqlite", "sqlite", "cloe-default"), ("postgres", "absent", "cloe-default"),
    ("absent", "sqlite", "legacy-default"), ("empty", "postgres", "legacy-default"),
    ("foreign", "sqlite", "legacy-default"), ("invalid", "sqlite", "legacy-default"),
])
def test_default_selection_table(defaults: tuple[Path, Path], new: str, old: str, source: str) -> None:
    current, legacy = defaults
    populate(current, new)
    populate(legacy, old)
    before = {p: p.read_bytes() for root in defaults if root.is_dir() for p in root.iterdir() if p.is_file()}
    selection = _resolve_home_selection()
    assert selection.source == source
    assert selection.path == (legacy if source == "legacy-default" else current)
    assert bool(selection.notices) == (source == "legacy-default")
    assert all(str(current.parent) not in message for message in selection.notices)
    assert {p: p.read_bytes() for p in before} == before
    if new == "absent":
        assert not current.exists()


@pytest.mark.parametrize(("new", "old", "code"), [
    ("foreign", "absent", "default-home-unrecognized"),
    ("invalid", "absent", "default-home-unrecognized"),
    ("file", "sqlite", "default-home-unsafe"),
    ("absent", "foreign", "legacy-default-home-unrecognized"),
    ("absent", "empty", "legacy-default-home-unrecognized"),
    ("absent", "file", "legacy-default-home-unrecognized"),
])
def test_unrecognized_defaults_refuse_without_disclosing_or_creating(
    defaults: tuple[Path, Path], new: str, old: str, code: str,
) -> None:
    current, legacy = defaults
    populate(current, new)
    populate(legacy, old)
    with pytest.raises(OpsConfigError) as raised:
        resolve_repo_map_home()
    assert [item.code for item in raised.value.diagnostics] == [code]
    assert str(current.parent) not in str(raised.value) and "opaque foreign" not in str(raised.value)
    if new == "absent":
        assert not current.exists()


def test_explicit_precedence_does_not_inspect_defaults(defaults, monkeypatch: pytest.MonkeyPatch) -> None:
    current, legacy = defaults
    monkeypatch.setattr(home_selection, "_classify", lambda *_args: pytest.fail("explicit selector inspected defaults"))
    monkeypatch.setenv("REPOMAP_HOME", str(legacy))
    monkeypatch.setenv("CLOE_HOME", str(current))
    assert resolve_repo_map_home() == current
    assert _resolve_home_selection(legacy).source == "explicit"
    monkeypatch.setenv("CLOE_HOME", "")
    assert resolve_repo_map_home() == legacy


def test_cloe_path_is_never_a_product_setting(defaults, monkeypatch: pytest.MonkeyPatch) -> None:
    current, legacy = defaults
    monkeypatch.setenv("CLOE_PATH", str(legacy))
    assert resolve_repo_map_home() == current and not current.exists() and not legacy.exists()


@pytest.mark.parametrize("object_kind", ["home-link", "config-link", "hardlink", "oversized", "mixed", "boolean-schema", "overlay-only"])
def test_implicit_ownership_witness_refuses_aliases_and_invalid_material(defaults, object_kind: str) -> None:
    current, _legacy = defaults
    populate(current, "sqlite")
    config = current / "00-project.cloe.toml"
    if object_kind == "home-link":
        target = current.with_name("other")
        current.rename(target)
        current.symlink_to(target, target_is_directory=True)
    elif object_kind == "config-link":
        target = current / "other.txt"
        config.rename(target)
        config.symlink_to(target)
    elif object_kind == "hardlink":
        os.link(config, current / "other.txt")
    elif object_kind == "oversized":
        config.write_bytes(b"x" * (home_selection.MAX_RECOGNITION_FILE_BYTES + 1))
    elif object_kind == "mixed":
        (current / "old.rp.toml").write_text(SQLITE)
    elif object_kind == "boolean-schema":
        config.write_text(SQLITE.replace("= 1", "= true"))
    else:
        config.write_text('schema_version = 1\n[service]\nlog_level = "info"\n')
    with pytest.raises(OpsConfigError):
        resolve_repo_map_home()


def test_default_read_failure_is_bounded(defaults, monkeypatch: pytest.MonkeyPatch) -> None:
    current, _legacy = defaults
    populate(current, "sqlite")
    monkeypatch.setattr(home_selection, "_read_config", lambda *_args: (_ for _ in ()).throw(PermissionError("private sentinel")))
    with pytest.raises(OpsConfigError) as raised:
        resolve_repo_map_home()
    assert "private sentinel" not in str(raised.value)


def test_parser_brand_is_explicit_and_canonical_default_is_selected() -> None:
    from common_lore_index.cli.parser import build_parser
    assert build_parser().prog == "cloe"
    assert build_parser(prog="cloe").format_help().startswith("usage: cloe ")


def test_cli_default_refusal_retains_its_safe_code(defaults, capsys) -> None:
    from common_lore_index.cli.main import main
    current, _legacy = defaults
    populate(current, "foreign")
    assert main(["local", "setup", "--json"]) == 1
    captured = capsys.readouterr()
    assert not captured.out and "default-home-unrecognized" in captured.err
    assert str(current.parent) not in captured.err and "opaque foreign" not in captured.err


def test_mcp_explicit_config_environment_does_not_inspect_default_home(defaults, monkeypatch) -> None:
    from common_lore_index.cli.main import _home_selection_notice
    from common_lore_index.cli.parser import build_parser
    current, _legacy = defaults
    populate(current, "foreign")
    args = build_parser().parse_args(["mcp", "serve"])
    monkeypatch.setenv("REPOMAP_OPS_CONFIG", "explicit-config.toml")
    _home_selection_notice(args)
    monkeypatch.setenv("REPOMAP_OPS_CONFIG", "")
    with pytest.raises(OpsConfigError):
        _home_selection_notice(args)


@pytest.mark.parametrize("operation", ["up_local_runtime", "down_local_runtime", "query_local_runtime_status"])
def test_runtime_api_preserves_its_safe_error_family(defaults, operation: str) -> None:
    from common_lore_index.runtime import local
    current, _legacy = defaults
    populate(current, "foreign")
    with pytest.raises(local.LocalRuntimeError) as raised:
        getattr(local, operation)()
    assert raised.value.diagnostics[0].code == "default-home-unrecognized"
    assert str(current.parent) not in str(raised.value)


def test_legacy_resolver_facades_keep_one_path_returning_function(defaults) -> None:
    from common_lore_index.ops import config, config_loading
    from common_lore_index.runtime import local
    current, legacy = defaults
    populate(legacy, "sqlite")
    assert local.resolve_repo_map_home is config.resolve_repo_map_home is config_loading.resolve_repo_map_home
    assert local.resolve_repo_map_home() == legacy
    assert local.resolve_repo_map_home(current) == current
    assert not current.exists()
