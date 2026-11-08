"""Closed CLI dispatch and Local refusal for one retained Server attempt."""

from __future__ import annotations

import builtins
import json
from pathlib import Path
from types import ModuleType

import pytest

from common_lore_index.cli.main import main
from common_lore_index.cli.parser import build_parser
from common_lore_index.cli import ops_retained_attempt_commands as commands
from common_lore_index.ops import retained_attempt_recovery as recovery
from repomap_test_support.sqlite_local_fixtures import graph_toml, write_sqlite_home

_KEYS = {
    "operation", "result", "reason", "retention_state", "artifact_proof",
    "publication_proof", "metadata_write_state",
}


def _args(action: str = "inspect"):
    return build_parser().parse_args([
        "ops", "retained-attempt", action, "--repo-map-home", "/synthetic/owned-home",
        "--graph", "owned-graph", "--operation-id", "owned-operation", "--attempt", "2", "--json",
    ])


@pytest.mark.parametrize("action", ["inspect", "settle"])
def test_cli_forwards_exact_selection_and_projects_only_the_result(action, monkeypatch, capsys):
    config = object()
    expected = recovery.RetainedAttemptRecovery(
        action, "ready", "accepted-proof", "publication-reconciliation", "matched", "matched", "not-attempted",
    )
    calls = []

    def recover(*args, **kwargs):
        calls.append((args, kwargs))
        return expected

    monkeypatch.setattr(commands, "load_graph_registry_config_home", lambda _home: config)
    monkeypatch.setattr(recovery, "recover_server_retained_attempt", recover)
    assert commands.dispatch_ops_retained_attempt_command(_args(action), ModuleType("test"), print) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == expected.to_jsonable()
    assert set(json.loads(output)) == _KEYS
    assert calls == [((config, "owned-graph", "owned-operation", 2), {"settle": action == "settle", "psql_command": None})]
    assert all(value not in output for value in ("owned-graph", "owned-operation", "/synthetic/owned-home"))


@pytest.mark.parametrize("fault_at", ["config", "recovery"])
def test_cli_expected_failure_is_categorical_and_interrupt_identity_survives(fault_at, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise RuntimeError("private diagnostic must never be serialized")

    monkeypatch.setattr(commands, "load_graph_registry_config_home", lambda _home: object())
    if fault_at == "config":
        monkeypatch.setattr(commands, "load_graph_registry_config_home", fail)
    else:
        monkeypatch.setattr(recovery, "recover_server_retained_attempt", fail)
    assert commands.dispatch_ops_retained_attempt_command(_args(), ModuleType("test"), print) == 1
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == _KEYS and payload["result"] == "refused"
    assert "private diagnostic" not in json.dumps(payload)

    primary = KeyboardInterrupt("owned interrupt")

    def interrupt(*args, **kwargs):
        raise primary

    monkeypatch.setattr(commands, "load_graph_registry_config_home", interrupt)
    with pytest.raises(KeyboardInterrupt) as caught:
        commands.dispatch_ops_retained_attempt_command(_args(), ModuleType("test"), print)
    assert caught.value is primary


def test_local_refuses_before_any_postgresql_import_or_state_creation(tmp_path: Path, monkeypatch, capsys):
    source = tmp_path / "source"
    source.mkdir()
    home = write_sqlite_home(tmp_path / "home", graph_toml("local-test", source), name="recovery.cloe.toml")
    before = {str(path.relative_to(home)) for path in home.rglob("*")}
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.startswith("psycopg"):
            raise AssertionError("Local refusal attempted a PostgreSQL import")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    assert main([
        "ops", "retained-attempt", "settle", "--repo-map-home", str(home),
        "--graph", "local-test", "--operation-id", "local-op", "--attempt", "1", "--json",
    ]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == _KEYS and payload["reason"] == "sqlite-backend"
    assert {str(path.relative_to(home)) for path in home.rglob("*")} == before


@pytest.mark.parametrize("attempt", ["0", "-1", "2147483648", "no"])
def test_cli_rejects_invalid_attempt_before_config(attempt):
    with pytest.raises(SystemExit) as caught:
        build_parser().parse_args([
            "ops", "retained-attempt", "inspect", "--graph", "demo", "--operation-id", "op", "--attempt", attempt,
        ])
    assert caught.value.code == 2
