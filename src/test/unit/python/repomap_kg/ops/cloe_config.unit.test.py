"""CLOE home selection, exact configuration layering and inert filename plans."""
from pathlib import Path
import json

import pytest

from repomap_kg.ops.config_loading import (
    _read_ops_config_home_payload,
    resolve_repo_map_home,
)
from repomap_kg.ops.config_records import OpsConfigError


def test_cloe_home_precedence_without_creation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old, new, explicit = (tmp_path / name for name in ("old", "new", "explicit"))
    monkeypatch.setenv("REPOMAP_HOME", str(old))
    monkeypatch.setenv("CLOE_HOME", str(new))
    assert resolve_repo_map_home() == new
    assert resolve_repo_map_home(explicit) == explicit
    monkeypatch.setenv("CLOE_HOME", "")
    assert resolve_repo_map_home() == old
    monkeypatch.delenv("REPOMAP_HOME")
    monkeypatch.setenv("CLOE_PATH", str(new))
    assert resolve_repo_map_home() == Path("~/.repo-map").expanduser()
    assert not any(path.exists() for path in (old, new, explicit))


def test_cloe_layers_load_once_in_base_then_local_order(tmp_path: Path) -> None:
    for name, value in (("90-project.cloe.toml", "info"), ("00-machine.local.cloe.toml", "debug")):
        (tmp_path / name).write_text(f'schema_version = 1\n[service]\nlog_level = "{value}"\n')
    (tmp_path / "other.toml").write_text("ignored = true\n")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/00.cloe.toml").write_text("not valid TOML")
    _, payload, files, diagnostics = _read_ops_config_home_payload(tmp_path)
    assert files == ("90-project.cloe.toml", "00-machine.local.cloe.toml")
    assert payload["service"]["log_level"] == "debug"
    assert [d.path for d in diagnostics if d.code == "config-file-ignored"] == ["other.toml"]


def test_mixed_home_is_refused_before_parsing_values(tmp_path: Path) -> None:
    (tmp_path / "old.rp.toml").write_text("private malformed contents")
    (tmp_path / "new.cloe.toml").write_text("private malformed contents")
    with pytest.raises(OpsConfigError) as raised:
        _read_ops_config_home_payload(tmp_path)
    assert raised.value.diagnostics[0].code == "config-home-mixed-format"
    assert "private malformed" not in str(raised.value)


@pytest.mark.parametrize(
    ("names", "codes"),
    [
        (("x.local.rp.toml", "x.rpl.toml"), {"target-collision", "base-became-local"}),
        (("base.extra.rp.toml", "base.rp.toml"), {"layer-order-changed"}),
        (("x.local.rp.toml",), {"base-became-local"}),
    ],
)
def test_unsafe_filename_conversion_is_refused(names: tuple[str, ...], codes: set[str]) -> None:
    from repomap_kg.ops.config_layout import plan_cloe_config_filenames

    plan = plan_cloe_config_filenames(names)
    assert plan["filename_conversion_ready"] is False
    assert codes <= {item["code"] for item in plan["refusals"]}
    assert plan["writes_performed"] == 0
    assert plan["apply_supported"] is False


def test_safe_conversion_preserves_complete_layer_order() -> None:
    from repomap_kg.ops.config_layout import plan_cloe_config_filenames

    plan = plan_cloe_config_filenames(("00-project.rp.toml", "90-private.rpl.toml"))
    assert plan["filename_conversion_ready"] is True
    assert plan["conversion_required"] is True
    assert plan["source_order"] == ["00-project.rp.toml", "90-private.rpl.toml"]
    assert plan["proposed_order"] == ["00-project.cloe.toml", "90-private.local.cloe.toml"]
    assert plan["refusals"] == []


def test_cloe_plan_is_an_explicit_noop() -> None:
    from repomap_kg.ops.config_layout import plan_cloe_config_filenames

    names = ("00-project.cloe.toml", "90-private.local.cloe.toml")
    plan = plan_cloe_config_filenames(names)
    assert plan["filename_conversion_ready"] is True
    assert plan["conversion_required"] is False
    assert plan["changes"] == []
    assert plan["source_order"] == plan["proposed_order"] == list(names)


@pytest.mark.parametrize("names", [(), ("unknown.toml",), ("../unsafe.rp.toml",), ("a.rp.toml", "b.cloe.toml")])
def test_filename_planner_rejects_non_home_inputs(names: tuple[str, ...]) -> None:
    from repomap_kg.ops.config_layout import plan_cloe_config_filenames

    with pytest.raises(ValueError):
        plan_cloe_config_filenames(names)


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("unsafe", [False, True])
def test_cli_plan_output_exit_and_no_contents(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], as_json: bool, unsafe: bool,
) -> None:
    from repomap_kg.cli.main import main

    name = "x.local.rp.toml" if unsafe else "00-project.rp.toml"
    body = 'schema_version = 1\n[postgres]\npassword = "not-for-plan-output"\n'
    original = tmp_path / name
    original.write_text(body)
    args = ["ops", "config-migration-plan", "--repo-map-home", str(tmp_path)]
    code = main(args + (["--json"] if as_json else []))
    rendered = capsys.readouterr()
    assert code == (1 if unsafe else 0)
    assert rendered.err == ""
    assert "not-for-plan-output" not in rendered.out
    assert str(tmp_path) not in rendered.out
    if as_json:
        assert json.loads(rendered.out)["filename_conversion_ready"] is not unsafe
    else:
        assert ("refused" if unsafe else "ready") in rendered.out
        assert "Read-only plan" in rendered.out
    assert original.read_text() == body
    assert list(tmp_path.iterdir()) == [original]


def test_cli_refuses_a_file_instead_of_a_home(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from repomap_kg.cli.main import main

    source = tmp_path / "config.rp.toml"
    source.write_text("schema_version = 1\n")
    assert main(["ops", "config-migration-plan", "--config", str(source), "--json"]) == 1
    rendered = capsys.readouterr()
    assert rendered.out == "" and "directory" in rendered.err


@pytest.mark.parametrize("fails", [False, True])
def test_explicit_mcp_home_temporarily_overrides_ambient_cloe_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fails: bool,
) -> None:
    import argparse
    from types import ModuleType
    from repomap_kg.cli._observations_dispatch import dispatch_observation_commands
    from repomap_kg.server import mcp

    original, selected = str(tmp_path / "ambient"), str(tmp_path / "explicit")
    monkeypatch.setenv("CLOE_HOME", original)
    monkeypatch.setenv("REPOMAP_HOME", original)

    def serve() -> int:
        assert resolve_repo_map_home() == Path(selected)
        if fails:
            raise RuntimeError("serve failure")
        return 0

    monkeypatch.setattr(mcp, "serve_stdio", serve)
    args = argparse.Namespace(command="mcp", mcp_command="serve", repo_map_home=selected, config=None)
    if fails:
        with pytest.raises(RuntimeError, match="serve failure"):
            dispatch_observation_commands(args, ModuleType("cloe_test_commands"), lambda *_args, **_kwargs: None)
    else:
        assert dispatch_observation_commands(args, ModuleType("cloe_test_commands"), lambda *_args, **_kwargs: None) == 0
    assert resolve_repo_map_home() == Path(original)


def test_preexisting_target_name_refuses_conversion() -> None:
    from repomap_kg.ops.config_layout import plan_cloe_config_filenames

    plan = plan_cloe_config_filenames(("00-project.rp.toml",), occupied_names={"00-project.cloe.toml"})
    assert not plan["filename_conversion_ready"]
    assert plan["refusals"] == [{"code": "target-already-exists", "file": "00-project.cloe.toml"}]


@pytest.mark.parametrize("occupied", ["00-project.CLOE.toml", "00-project.cloe.toml"])
def test_portable_occupied_name_refuses_case_aliases(occupied: str) -> None:
    from repomap_kg.ops.config_layout import plan_cloe_config_filenames

    plan = plan_cloe_config_filenames(("00-project.rp.toml",), occupied_names={occupied})
    assert not plan["filename_conversion_ready"]
    assert plan["refusals"][0]["code"] == "target-already-exists"


def test_portable_occupied_name_refuses_unicode_normalization_alias() -> None:
    from repomap_kg.ops.config_layout import plan_cloe_config_filenames

    plan = plan_cloe_config_filenames(("caf\u00e9.rp.toml",), occupied_names={"cafe\u0301.cloe.toml"})
    assert not plan["filename_conversion_ready"]
    assert plan["refusals"][0]["code"] == "target-already-exists"


def test_legacy_runtime_setup_refuses_cloe_home_before_writes(tmp_path: Path) -> None:
    from repomap_kg.runtime.local import setup_local_runtime
    from repomap_kg.runtime.plan import LocalRuntimeError

    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    config = home / "00.cloe.toml"
    config.write_text("schema_version = 1\n")
    with pytest.raises(LocalRuntimeError) as raised:
        setup_local_runtime(home)
    assert raised.value.diagnostics[0].code == "cloe-runtime-setup-deferred"
    assert list(home.iterdir()) == [config]
