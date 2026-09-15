"""Pure regressions for the PR26 staging fixture seams."""

from __future__ import annotations

import ast
import subprocess
import tomllib
from pathlib import Path
from typing import cast

import psycopg
import pytest

from repomap_kg.runtime.local import LocalRuntimeIdentity, setup_local_runtime
from repomap_kg.ops.config_sections import parse_server_memory_section
from repomap_test_support import cli_integration
from repomap_test_support.local_db_backup import LocalDbBackupUnitTestCase
from scale28_observer_deadlines import ObserverConnectionSettings, ObserverDeadlinePolicy


_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
_NESTED_OWNING_AREA_NODE = (
    "src/test/unit/python/repomap_test_support/"
    "scale28_diag1_fix1_test_scratch_boundaries.unit.test.py::"
    "test_run_allocation_is_exclusive_and_short"
)


def test_mcp_domain_fixture_declares_disabled_read_only_memory() -> None:
    owner = _REPOSITORY_ROOT / (
        "src/test/int/python/repomap_kg/cli/mcp_domain_readback.int.test.py"
    )
    templates = [
        node for node in ast.walk(ast.parse(owner.read_text(encoding="utf-8")))
        if isinstance(node, ast.JoinedStr) and node.values
        and isinstance(node.values[0], ast.Constant)
        and str(node.values[0].value).startswith("schema_version = 1")
    ]
    assert len(templates) == 1
    parts = []
    for value in templates[0].values:
        if isinstance(value, ast.Constant):
            parts.append(str(value.value))
        else:
            assert isinstance(value, ast.FormattedValue)
            assert isinstance(value.value, ast.Attribute)
            parts.append("5432" if value.value.attr == "port" else "test")
    payload = tomllib.loads("".join(parts))
    memory, diagnostics = parse_server_memory_section(payload["server_memory"])
    assert diagnostics == []
    assert memory.enabled is False
    assert memory.mode == "read_only"


def test_in_process_cli_capture_does_not_invoke_module_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A patched product subprocess seam must still reach the CLI callable."""

    def forbidden_launcher(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("the module launcher must not run for this capture")

    monkeypatch.setattr(cli_integration, "run_cli_module", forbidden_launcher)
    monkeypatch.setattr(cli_integration.subprocess, "run", forbidden_launcher)

    result = cli_integration.CliIntegrationTestCase().run_repo_map_in_process(
        "--version"
    )

    assert result[0] == 0
    assert result[1].startswith("repomap-kg ")
    assert result[2] == ""


def test_in_process_cli_routes_dump_to_recording_runner_and_reports_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A local CLI failure reaches the exact product subprocess seam."""

    home = tmp_path / "repo-map-home"
    setup_local_runtime(home)
    identity = LocalRuntimeIdentity.from_home(home)
    expected_inspect = ["docker", "inspect", identity.postgres_container]
    expected_dump = [
        "docker",
        "exec",
        "-e",
        "PGPASSWORD",
        identity.postgres_container,
        "/usr/bin/pg_dump",
        "-Fc",
        "-U",
        "repomap",
        "-d",
        "repomap",
    ]
    calls: list[tuple[list[str], dict[str, object]]] = []

    def recording_runner(command, **kwargs):
        command = list(command)
        calls.append((command, kwargs))
        if command == expected_inspect:
            return LocalDbBackupUnitTestCase.owned_container_result(identity, command)
        if command == expected_dump:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout=b"",
                stderr=b"fixture pg_dump failure",
            )
        raise AssertionError(command)

    monkeypatch.setattr(
        "repomap_kg.runtime.backup.subprocess.run", recording_runner
    )
    exit_code, stdout, stderr = cli_integration.CliIntegrationTestCase().run_repo_map_in_process(
        "local",
        "db",
        "dump",
        "--repo-map-home",
        str(home),
        "--database",
        "repomap",
        "--reason",
        "unit-test",
        "--json",
    )

    assert exit_code == 1
    assert stdout == ""
    assert "ERROR: fixture pg_dump failure" in stderr
    assert [command for command, _kwargs in calls] == [expected_inspect, expected_dump]


@pytest.mark.parametrize(
    "parameters",
    [
        pytest.param(
            {
                "host": "fixture host",
                "port": 55433,
                "user": "observer role",
                "dbname": "observer db",
                "options": "-c statement_timeout=400ms -c search_path=public schema",
                "application_name": "observer 'quoted'",
            },
            id="spaces-and-quotes",
        ),
        pytest.param(
            {
                "host": "127.0.0.1",
                "port": "55433",
                "user": r"observer\\role",
                "dbname": "observer'db",
                "password": "fixture credential",
                "options": r"-c search_path=public\ schema",
            },
            id="backslashes-and-credential",
        ),
    ],
)
def test_conninfo_builder_round_trips_spaces_and_escaping(
    parameters: dict[str, str | int | None],
) -> None:
    """The supported builder preserves every selected libpq parameter."""

    conninfo = psycopg.conninfo.make_conninfo("", **parameters)
    parsed = psycopg.conninfo.conninfo_to_dict(conninfo)

    assert parsed == {key: str(value) for key, value in parameters.items()}


def test_observer_settings_apply_preserves_timeout_through_conninfo_roundtrip() -> None:
    """Applied observer policy stays intact through supported conninfo APIs."""

    parameters: dict[str, str | int | None] = {
        "host": "fixture host",
        "port": 55433,
        "user": r"observer\\role",
        "dbname": "observer'db",
        "password": "fixture credential",
        "options": r"-c search_path=public\ schema",
        "application_name": "observer 'quoted'",
    }
    policy = ObserverDeadlinePolicy(
        connection_timeout_seconds=4,
        server_statement_timeout_ms=400,
    )
    selected = ObserverConnectionSettings.from_policy(policy).apply(parameters)

    assert selected["connect_timeout"] == 4
    assert selected["options"] == (
        r"-c search_path=public\ schema -c statement_timeout=400ms"
    )
    conninfo = psycopg.conninfo.make_conninfo(
        "", **cast(dict[str, str | int | None], selected)
    )
    parsed = psycopg.conninfo.conninfo_to_dict(conninfo)

    assert parsed == {key: str(value) for key, value in selected.items()}


def test_nested_owning_area_selector_targets_a_current_test_function() -> None:
    """The owning-area child selector must remain an executable exact node."""

    relative_path, separator, function_name = _NESTED_OWNING_AREA_NODE.partition("::")
    assert separator == "::"
    path = _REPOSITORY_ROOT / relative_path
    assert path.is_file()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    assert function_name in function_names

    integration_path = (
        _REPOSITORY_ROOT
        / "src/test/int/python/repomap_test_support/"
        / "test_cov5k_r2_fix2_owning_areas.int.test.py"
    )
    integration_source = integration_path.read_text(encoding="utf-8")
    integration_tree = ast.parse(integration_source)
    owner = next(
        node for node in integration_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "test_nested_tmp_path_materializes_dedicated_owning_area_basetemp"
    )
    selectors = [
        ast.literal_eval(node.value)
        for node in ast.walk(owner)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "node" for target in node.targets)
    ]
    assert selectors == [_NESTED_OWNING_AREA_NODE]
