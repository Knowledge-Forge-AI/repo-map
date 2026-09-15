from __future__ import annotations

import argparse
import inspect
from pathlib import Path
from typing import Any

import pytest

import repomap_kg.ops.config as module
from repomap_kg.cli.parser import build_parser
from repomap_kg.ops.config_records import OpsPostgresStatus
from repomap_kg.storage import StorageSchemaError


BASE_CONFIG = """\
schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
[postgres]
host = "public-db.invalid"
port = 5432
database = "repomap_test"
user = "public_user"
password_env = "PUBLIC_SAFE_PASSWORD"
{graphs}
[server_memory]
enabled = false
path = "./public-server-memory"
mode = "read_only"
"""

MULTI_GRAPHS = """\
[[graphs]]
id = "default-a"
name = "Default A"
root_path = "/public/default-a"
repository_name = "repo-a"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[[graphs]]
id = "default-missing"
name = "Default Missing"
root_path = "/public/default-missing"
repository_name = "repo-missing"
database = "repomap_test_missing"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[[graphs]]
id = "second"
name = "Second"
root_path = "/public/second"
repository_name = "repo-b"
database = "second_db"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[[graphs]]
id = "third"
name = "Third"
root_path = "/public/third"
repository_name = "repo-c"
database = "third_db"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
"""

ONE_GRAPH = MULTI_GRAPHS.split("[[graphs]]", 2)[1]
ONE_GRAPH = "[[graphs]]" + ONE_GRAPH


def _config(tmp_path: Path, graphs: str = MULTI_GRAPHS):
    path = tmp_path / "repomap.local.toml"
    path.write_text(BASE_CONFIG.format(graphs=graphs), encoding="utf-8")
    return module.load_ops_config(path)


def _ready() -> OpsPostgresStatus:
    return OpsPostgresStatus(
        db_checked=True,
        connected=True,
        schema_available=True,
        required_tables={},
    )


def _subparser(parser: argparse.ArgumentParser, *names: str) -> argparse.ArgumentParser:
    current = parser
    for name in names:
        action = next(
            item
            for item in current._actions
            if isinstance(item, argparse._SubParsersAction)
        )
        current = action.choices[name]
    return current


def test_psycopg101_exact_two_stage_wiring_and_parser_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    readiness_calls: list[dict[str, Any]] = []
    graph_calls: list[dict[str, Any]] = []

    def readiness(config_arg, **kwargs):
        readiness_calls.append({"config": config_arg, **kwargs})
        return _ready()

    rows = {
        "repomap_test": [{"repository_name": "repo-a", "repository_exists": True}],
        "repomap_test_missing": [],
        "second_db": [{"repository_name": "repo-b", "repository_exists": True}],
        "third_db": [{"repository_name": "repo-c", "repository_exists": True}],
    }

    def readback(config_arg, **kwargs):
        graph_calls.append({"config": config_arg, **kwargs})
        return {"graphs": rows[kwargs["database"]]}

    monkeypatch.setattr(module, "check_ops_postgres_status", readiness)
    monkeypatch.setattr(module, "execute_ops_json_readback", readback)

    statuses = module.check_ops_graph_storage_status(config)

    assert inspect.signature(module.check_ops_graph_storage_status).parameters[
        "psql_command"
    ].default is None
    assert list(statuses) == ["default-a", "default-missing", "second", "third"]
    assert [call["database"] for call in readiness_calls] == [
        "repomap_test",
        "repomap_test_missing",
        "second_db",
        "third_db",
    ]
    assert all(call["psql_command"] is None for call in readiness_calls)
    assert graph_calls == [
        {
            "config": config,
            "database": database,
            "sql": module.build_graph_storage_status_sql(repository_names),
            "label": "operations graph storage status",
            "expected_shape": "object",
            "mode": "host_only",
            "psql_command": None,
        }
        for database, repository_names in (
            ("repomap_test", ["repo-a"]),
            ("repomap_test_missing", ["repo-missing"]),
            ("second_db", ["repo-b"]),
            ("third_db", ["repo-c"]),
        )
    ]

    parser = build_parser()
    graphs_args = parser.parse_args(["ops", "graphs", "--check-db"])
    config_args = parser.parse_args(["ops", "config-check", "--check-db"])
    explicit = parser.parse_args(
        ["ops", "graphs", "--check-db", "--psql-command", "/opt/psql-wrapper"]
    )
    graphs_parser = _subparser(parser, "ops", "graphs")
    command_action = next(
        action for action in graphs_parser._actions if action.dest == "psql_command"
    )
    assert graphs_args.psql_command is None
    assert config_args.psql_command is None
    assert explicit.psql_command == "/opt/psql-wrapper"
    assert "both" in (command_action.help or "")
    assert "defaults to Psycopg" in (command_action.help or "")


def test_psycopg101_normalization_conversion_and_missing_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, MULTI_GRAPHS.split("[[graphs]]", 3)[0] + ONE_GRAPH)
    monkeypatch.setattr(module, "check_ops_postgres_status", lambda *a, **k: _ready())
    monkeypatch.setattr(
        module,
        "execute_ops_json_readback",
        lambda *a, **k: {
            "ignored": "top-level",
            "graphs": [
                None,
                {"repository_name": 7},
                {"not_repository_name": "ignored"},
                {"repository_name": "repo-a", "raw_observations": 99},
                {
                    "repository_name": "repo-a",
                    "repository_exists": "yes",
                    "repository_id": True,
                    "raw_observations": "4",
                    "latest_run_raw_observations": True,
                    "canonical_nodes": -2,
                    "canonical_edges": False,
                    "ignored": "row-extra",
                },
            ],
        },
    )

    status = module.check_ops_graph_storage_status(config)["default-a"]

    assert tuple(status.to_jsonable()) == (
        "db_checked",
        "repository_name",
        "database",
        "schema_available",
        "repository_exists",
        "repository_id",
        "raw_observations",
        "raw_observations_total",
        "latest_run_raw_observations",
        "canonical_nodes",
        "canonical_edges",
        "error",
    )
    assert status.repository_exists is True
    assert status.repository_id is True
    assert status.raw_observations == 4
    assert status.raw_observations_total == 4
    assert status.latest_run_raw_observations == 1
    assert status.canonical_nodes == -2
    assert status.canonical_edges == 0


@pytest.mark.parametrize("payload", ({}, {"graphs": {}}, {"graphs": []}))
def test_psycopg101_missing_and_nonlist_graphs_use_missing_row_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    config = _config(tmp_path, ONE_GRAPH)
    monkeypatch.setattr(module, "check_ops_postgres_status", lambda *a, **k: _ready())
    monkeypatch.setattr(module, "execute_ops_json_readback", lambda *a, **k: payload)

    assert module.check_ops_graph_storage_status(config)["default-a"].to_jsonable() == {
        "db_checked": True,
        "repository_name": "repo-a",
        "database": "repomap_test",
        "schema_available": True,
        "repository_exists": False,
        "repository_id": None,
        "raw_observations": 0,
        "raw_observations_total": 0,
        "latest_run_raw_observations": 0,
        "canonical_nodes": 0,
        "canonical_edges": 0,
        "error": None,
    }


def test_psycopg101_database_failures_fold_and_later_groups_continue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    graph_calls: list[str] = []

    def readiness(config_arg, **kwargs):
        if kwargs["database"] in {"repomap_test", "repomap_test_missing"}:
            return OpsPostgresStatus(
                db_checked=True,
                connected=False,
                schema_available=False,
                required_tables={},
                error="readiness unavailable",
            )
        return _ready()

    def readback(config_arg, **kwargs):
        graph_calls.append(kwargs["database"])
        if kwargs["database"] == "second_db":
            raise StorageSchemaError("graph stage unavailable")
        return {"graphs": [{"repository_name": "repo-c", "repository_exists": True}]}

    monkeypatch.setattr(module, "check_ops_postgres_status", readiness)
    monkeypatch.setattr(module, "execute_ops_json_readback", readback)

    statuses = module.check_ops_graph_storage_status(
        config,
        psql_command="/opt/psql-wrapper",
    )

    assert graph_calls == ["second_db", "third_db"]
    assert statuses["default-a"].error == "readiness unavailable"
    assert statuses["default-missing"].error == "readiness unavailable"
    assert statuses["second"].schema_available is True
    assert statuses["second"].raw_observations is None
    assert statuses["second"].error == "graph stage unavailable"
    assert statuses["third"].repository_exists is True


def test_psycopg101_noncoercible_count_remains_caller_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(module, "check_ops_postgres_status", lambda *a, **k: _ready())

    def readback(config_arg, **kwargs):
        calls.append(kwargs["database"])
        return {
            "graphs": [
                {
                    "repository_name": "repo-a",
                    "raw_observations": "not-an-integer",
                }
            ]
        }

    monkeypatch.setattr(module, "execute_ops_json_readback", readback)

    with pytest.raises(ValueError):
        module.check_ops_graph_storage_status(config)
    assert calls == ["repomap_test"]


@pytest.mark.parametrize("psql_command", (None, "/opt/psql-wrapper"))
def test_psycopg101_both_real_adapter_stages_are_host_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    psql_command: str | None,
) -> None:
    config = _config(tmp_path, ONE_GRAPH)
    import repomap_kg.ops.readback as readback
    calls: list[dict[str, Any]] = []

    def select_driver():
        if psql_command is not None:
            pytest.fail("explicit graph command resolved selectors")
        return "psql"

    def execute(sql, **kwargs):
        calls.append(kwargs)
        if kwargs["label"] == "operations postgres status":
            return {
                "connected": True,
                "schema_available": True,
                "required_tables": {},
            }
        return {"graphs": [{"repository_name": "repo-a", "repository_exists": True}]}

    def fail_topology(*args, **kwargs):
        pytest.fail("host-only graph storage inspected topology")

    monkeypatch.setattr(readback, "selected_json_readback_driver", select_driver)
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", execute)
    monkeypatch.setattr(readback, "_runtime_plan", fail_topology)
    monkeypatch.setattr(readback, "_container_psql_execution", fail_topology)
    monkeypatch.setattr(readback, "_resolve_container_readback_plan", fail_topology)

    status = module.check_ops_graph_storage_status(
        config,
        psql_command=psql_command,
    )["default-a"]

    assert status.repository_exists is True
    assert [call["label"] for call in calls] == [
        "operations postgres status",
        "operations graph storage status",
    ]
    assert all(call["driver"] == "psql" for call in calls)
    assert all(
        call["psql_command"] == (psql_command or "psql") for call in calls
    )


def test_psycopg101_moves_no_other_operational_owner() -> None:
    import repomap_kg.ops.refresh as refresh_module
    import repomap_kg.server.ops as server_module
    source = inspect.getsource(module.check_ops_graph_storage_status)

    assert "execute_ops_json_readback" in source
    assert "run_psql" not in source
    assert "parse_psql_json" not in source
    graph_summary_source = inspect.getsource(refresh_module.query_graph_summary)
    assert graph_summary_source.count("execute_ops_json_readback") == 2
    assert "_run_ops_psql" not in graph_summary_source
    search_fn = getattr(server_module, "_ops_search_impl", server_module).query_mcp_search
    search_source = inspect.getsource(search_fn)
    assert "execute_ops_json_readback" in search_source
    assert "run_psql" not in search_source
