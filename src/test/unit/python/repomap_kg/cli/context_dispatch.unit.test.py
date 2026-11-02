"""Central CLI dispatch preserves lazy PostgreSQL release implementation loading."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
from types import ModuleType

import pytest

from common_lore_index.cli import dispatch
from common_lore_index.cli.main import main as cli_entry


def _decline_earlier_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "dispatch_coordinator_service_command", "dispatch_observation_commands",
        "dispatch_ops_graph_file_command", "dispatch_source_acquisition_command",
        "dispatch_coordinator_runtime_command", "dispatch_ops_control_command",
        "dispatch_ops_refresh_command",
    ):
        monkeypatch.setattr(dispatch, name, lambda *args, **kwargs: None)


class _ReleaseFacade(ModuleType):
    initialize_release_cluster: Callable[[str], dict[str, object]]
    release_cluster_status: Callable[[str], dict[str, object]]
    ReleaseClusterError: type[Exception]

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"unrelated command resolved release facade: {name}")


@pytest.mark.parametrize("command", ("context-select", "context-pack"))
def test_context_entry_does_not_resolve_release_facade(
    command: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = argparse.Namespace(command="ops", ops_command=command, version=False)
    class Parser:
        def parse_args(self, _argv):
            return args

    scope = cli_entry.__globals__
    monkeypatch.setitem(scope, "build_parser", Parser)
    monkeypatch.setitem(scope, "_home_selection_notice", lambda _args: None)
    monkeypatch.setitem(scope, "dispatch_config_migration", lambda *args: None)
    monkeypatch.setitem(scope, "dispatch_ops_sqlite_command", lambda *args: None)
    monkeypatch.setitem(scope, "_commands_module", lambda: _ReleaseFacade("cli"))
    monkeypatch.setitem(scope, "dispatch_ops_context_command", lambda *args: 0)

    def legacy_dispatch(*_args):
        raise AssertionError("context must route before the PostgreSQL dispatcher")

    monkeypatch.setitem(scope, "dispatch_command", legacy_dispatch)
    assert cli_entry([]) == 0


@pytest.mark.parametrize("command", ("release-cluster-init", "release-cluster-status"))
def test_release_dispatch_preserves_selected_callback_without_live_runtime(
    command: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _decline_earlier_routes(monkeypatch)
    called: list[tuple[str, str]] = []
    facade = _ReleaseFacade("cli")

    def callback(operation: str):
        def invoke(home: str) -> dict[str, object]:
            called.append((operation, home))
            return {"result": "ready", "graph_database_count": 2}
        return invoke

    facade.initialize_release_cluster = callback("init")
    facade.release_cluster_status = callback("status")
    facade.ReleaseClusterError = RuntimeError
    args = argparse.Namespace(
        command="ops", ops_command=command, version=False,
        repo_map_home="controlled-home", json=True,
    )
    assert dispatch.dispatch_command(args, argparse.ArgumentParser(), facade) == 0
    assert called == [("init" if command.endswith("-init") else "status", "controlled-home")]
    assert json.loads(capsys.readouterr().out) == {"result": "ready", "graph_database_count": 2}
