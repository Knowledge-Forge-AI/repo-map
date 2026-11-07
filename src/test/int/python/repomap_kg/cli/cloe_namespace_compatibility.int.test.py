"""ADR 0123 clean-process canonical and legacy launches, stdout integrity and read-only MCP stdio."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from common_lore_index import PREFERRED_CLI, __version__
from common_lore_index.entrypoints import LEGACY_COMMAND_NOTICE
from common_lore_index.runtime.project_identity import PROJECT_IDENTITY
from common_lore_index.server.mcp_schemas import tool_definitions
from repomap_kg.server.mcp import LEGACY_MCP_NOTICE
from repomap_test_support.cli_in_process import REPO_ROOT, module_process_environment
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_sqlite_home
from repomap_test_support.sqlite_local_harness import initialize
from runner_coverage_observer import launch_observed_process

LEGACY_LINE = LEGACY_COMMAND_NOTICE + "\n"
MCP_LINE = LEGACY_MCP_NOTICE + "\n"
CANONICAL_MODULE = "python -m common_lore_index"


def console_script(entry: str) -> list[str]:
    """The installed wrapper's exact call shape, launched without an installer."""
    return [sys.executable, "-c", f"import sys\nfrom common_lore_index.entrypoints import {entry}\nsys.exit({entry}())"]


# label -> (argv, explicit brand, exact compatibility stderr prefix)
LAUNCHES: dict[str, tuple[list[str], str, str]] = {
    CANONICAL_MODULE: ([sys.executable, "-m", "common_lore_index"], PREFERRED_CLI, ""),
    "cloe": (console_script("cloe_main"), "cloe", ""),
    "common-lore-index": (console_script("long_main"), "common-lore-index", ""),
    "repomap-kg": (console_script("legacy_main"), "repomap-kg", LEGACY_LINE),
    "python -m repomap_kg": ([sys.executable, "-m", "repomap_kg"], "repomap-kg", LEGACY_LINE),
}
MCP_MODULES: dict[str, tuple[list[str], str]] = {
    "canonical": ([sys.executable, "-m", "common_lore_index.server.mcp"], ""),
    "legacy": ([sys.executable, "-m", "repomap_kg.server.mcp"], MCP_LINE),
}
MCP_REQUESTS = "".join(json.dumps(item) + "\n" for item in (
    initialize(1),
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
))
DRIVER_IMPORT_PROBE = """
import importlib, importlib.abc, json, sys
attempts = []
class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname.split('.')[0] in ('psycopg', 'psycopg_binary', 'psycopg_c', 'psycopg_pool'):
            attempts.append(fullname)
            raise ImportError('fixture blocks optional driver')
        return None
sys.meta_path.insert(0, Blocker())
hooks = (list(sys.meta_path), list(sys.path_hooks))
import repomap_kg
import repomap_kg.ops.config_migration as legacy_migration
import repomap_kg.server.mcp as legacy_mcp
import common_lore_index
import common_lore_index.entrypoints
import common_lore_index.ops.config_migration as canonical_migration
names = ('apply_cloe_config_migration', 'rollback_cloe_config_migration', 'finalize_cloe_config_migration')
watched = ('common_lore_index.cli', 'common_lore_index.cli.main', 'common_lore_index.server.mcp')
print(json.dumps({
    'attempts': attempts,
    'identical': [getattr(legacy_migration, name) is getattr(canonical_migration, name) for name in names],
    'constants': [getattr(repomap_kg, name) is getattr(common_lore_index, name)
                  for name in ('DISTRIBUTION_NAME', 'IMPORT_PACKAGE', 'PREFERRED_CLI', '__version__')],
    'hooks_unchanged': hooks == (list(sys.meta_path), list(sys.path_hooks)),
    'legacy_loaded': sorted(name for name in sys.modules if name.split('.')[0] == 'repomap_kg'),
    'aliases': sorted(name for name, module in sys.modules.items()
                      if name.split('.')[0] == 'repomap_kg' and getattr(module, '__name__', None) != name),
    'canonical_loaded': sorted(name for name in watched if name in sys.modules),
    'drivers_loaded': sorted(name for name in sys.modules if name.split('.')[0].startswith('psycopg')),
    'mcp_public': sorted(name for name in vars(legacy_mcp) if not name.startswith('_')),
}, sort_keys=True))
"""


def disposable_environment(user_home: Path) -> dict[str, str]:
    """A public-safe child environment whose only home is a disposable directory."""
    user_home.mkdir(mode=0o700)
    env = module_process_environment()
    for name in ("CLOE_HOME", "REPOMAP_HOME", "REPOMAP_OPS_CONFIG", "REPOMAP_MCP_CONFIG"):
        env.pop(name, None)
    env["HOME"] = str(user_home)
    return env


def launch(
    argv: list[str], env: dict[str, str], *args: str, input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return launch_observed_process(
        [*argv, *args], family="cli_module", cwd=REPO_ROOT, env=env, input_text=input_text,
        pid_namespace_relation="shared", timeout=120,
    )


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
            for path in sorted(root.rglob("*"))}


def mcp_responses(stdout: str) -> dict[int, dict[str, Any]]:
    responses = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    return {int(response["id"]): response for response in responses}


def assert_mcp_wire(stdout: str) -> None:
    responses = mcp_responses(stdout)
    assert sorted(responses) == [1, 2]
    initialized = responses[1]["result"]
    assert isinstance(initialized, dict) and initialized["serverInfo"]["name"] == "repomap-kg"
    listed = responses[2]["result"]
    assert isinstance(listed, dict)
    assert [tool["name"] for tool in listed["tools"]] == [tool["name"] for tool in tool_definitions()]


@pytest.mark.parametrize("label", sorted(LAUNCHES))
def test_clean_process_help_is_explicitly_branded_with_stderr_only_notice(tmp_path: Path, label: str) -> None:
    argv, prog, notice = LAUNCHES[label]
    env = disposable_environment(tmp_path / "user home")
    result = launch(argv, env, "--help")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"usage: {prog} ")
    assert result.stderr == notice
    assert "deprecated" not in result.stdout and snapshot(tmp_path / "user home") == {}


def test_clean_process_version_and_identity_stdout_are_identical_for_every_launch(tmp_path: Path) -> None:
    env = disposable_environment(tmp_path / "user home")
    observed: dict[str, dict[str, tuple[int, str, str]]] = {}
    for label, (argv, _prog, _notice) in LAUNCHES.items():
        observed[label] = {}
        for args in (("--version",), ("identity", "--json"), ("identity",)):
            result = launch(argv, env, *args)
            observed[label][" ".join(args)] = (result.returncode, result.stdout, result.stderr)
    canonical = observed[CANONICAL_MODULE]
    for label, (_argv, _prog, notice) in LAUNCHES.items():
        for command, (code, stdout, stderr) in observed[label].items():
            expected = (0, f"{_prog} {__version__}\n") if command == "--version" else canonical[command][:2]
            assert (code, stdout) == expected, (label, command, stderr)
            assert stderr == notice, (label, command)
    _code, version, _stderr = canonical["--version"]
    assert version.count("\n") == 1 and version.split()[-1] == __version__
    identity = json.loads(canonical["identity --json"][1])
    assert identity == PROJECT_IDENTITY.as_dict() and len(identity) == 6
    assert snapshot(tmp_path / "user home") == {}


def test_clean_process_legacy_imports_are_canonical_identities_without_drivers_or_hooks(tmp_path: Path) -> None:
    env = disposable_environment(tmp_path / "user home")
    result = launch([sys.executable, "-c", DRIVER_IMPORT_PROBE], env)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    value = json.loads(result.stdout)
    assert value == {
        "aliases": [],
        "attempts": [],
        "canonical_loaded": [],
        "constants": [True, True, True, True],
        "drivers_loaded": [],
        "hooks_unchanged": True,
        "identical": [True, True, True],
        "legacy_loaded": ["repomap_kg", "repomap_kg.ops", "repomap_kg.ops.config_migration",
                          "repomap_kg.server", "repomap_kg.server.mcp"],
        "mcp_public": ["LEGACY_MCP_NOTICE", "annotations", "main", "sys"],
    }


def test_mcp_module_launches_share_initialization_and_wire_tool_names(tmp_path: Path) -> None:
    env = disposable_environment(tmp_path / "user home")
    outputs: dict[str, str] = {}
    for label, (argv, notice) in MCP_MODULES.items():
        result = launch(argv, env, input_text=MCP_REQUESTS)
        assert result.returncode == 0, result.stderr
        assert result.stderr == notice
        assert_mcp_wire(result.stdout)
        outputs[label] = result.stdout
    assert outputs["legacy"] == outputs["canonical"]
    assert snapshot(tmp_path / "user home") == {}


def test_legacy_module_keeps_the_service_environment_boundary(tmp_path: Path) -> None:
    env = disposable_environment(tmp_path / "user home")
    code = """import json,os,runpy,sys
import common_lore_index.cli as cli
def record(argv=None, *, prog):
    print(json.dumps({'keys':sorted(os.environ), 'argv':argv, 'prog':prog}))
    return 0
cli.main=record
os.environ.clear()
os.environ.update(LANG='C.UTF-8', DATABASE_PASSWORD='synthetic-sentinel')
sys.argv=['repomap_kg','ops','coordinator-serve','--repo-map-home','/placeholder/home','--service-package-environment','--json']
runpy.run_module('repomap_kg',run_name='__main__')
"""
    result = launch([sys.executable, "-c", code], env)
    assert result.returncode == 0 and result.stderr == LEGACY_LINE
    assert json.loads(result.stdout) == {"keys": ["LANG"], "argv": None, "prog": "repomap-kg"}
    assert "synthetic-sentinel" not in result.stdout + result.stderr


def test_mcp_serve_through_canonical_and_legacy_commands_is_read_only_and_identical(tmp_path: Path) -> None:
    env = disposable_environment(tmp_path / "user home")
    home = tmp_path / "explicit home"
    write_sqlite_home(home, graph_toml("one", "/not-read/source"))
    home.chmod(0o700)
    before = snapshot(tmp_path)
    observed: dict[str, subprocess.CompletedProcess[str]] = {}
    for label in ("cloe", "repomap-kg", "python -m repomap_kg"):
        argv, _prog, _notice = LAUNCHES[label]
        observed[label] = launch(argv, env, "mcp", "serve", "--repo-map-home", str(home), input_text=MCP_REQUESTS)
    canonical = observed["cloe"]
    assert canonical.returncode == 0, canonical.stderr
    assert_mcp_wire(canonical.stdout)
    for label in ("repomap-kg", "python -m repomap_kg"):
        legacy = observed[label]
        assert (legacy.returncode, legacy.stdout) == (canonical.returncode, canonical.stdout), label
        assert legacy.stderr == LEGACY_LINE + canonical.stderr, label
    for result in observed.values():
        assert str(home) not in result.stdout + result.stderr
    assert snapshot(tmp_path) == before
