from __future__ import annotations

import argparse
import inspect
from pathlib import Path
from typing import Any

import pytest

from repomap_kg.cli.parser import build_parser
from repomap_kg.ops.config import (
    build_postgres_status_sql,
    check_ops_graph_storage_status,
    check_ops_postgres_status,
    load_ops_config,
)
from repomap_kg.storage import StorageSchemaError


CONFIG = """\
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

[[graphs]]
id = "first-graph"
name = "First Graph"
root_path = "/public/first"
repository_name = "first-repository"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[[graphs]]
id = "second-graph"
name = "Second Graph"
root_path = "/public/second"
repository_name = "second-repository"
database = "second_database"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"

[server_memory]
enabled = false
path = "./public-server-memory"
mode = "read_only"
"""


def _config(tmp_path: Path):
    path = tmp_path / "repomap.local.toml"
    path.write_text(CONFIG, encoding="utf-8")
    return load_ops_config(path)


def _patch_adapter(monkeypatch: pytest.MonkeyPatch, implementation) -> None:
    import repomap_kg.ops.config as module
    monkeypatch.setattr(
        module,
        "execute_ops_json_readback",
        implementation,
        raising=False,
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


def test_psycopg98_readiness_uses_exact_host_only_adapter_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    calls: list[dict[str, Any]] = []

    def execute(config_arg, **kwargs):
        calls.append({"config": config_arg, **kwargs})
        return {
            "connected": True,
            "schema_available": True,
            "required_tables": {"repositories": True},
        }

    _patch_adapter(monkeypatch, execute)
    default_status = check_ops_postgres_status(config)
    override_status = check_ops_postgres_status(
        config,
        database="override_database",
        psql_command="/opt/bin/psql-wrapper",
    )

    assert inspect.signature(check_ops_postgres_status).parameters[
        "psql_command"
    ].default is None
    assert calls == [
        {
            "config": config,
            "database": "repomap_test",
            "sql": build_postgres_status_sql(),
            "label": "operations postgres status",
            "expected_shape": "object",
            "mode": "host_only",
            "psql_command": None,
        },
        {
            "config": config,
            "database": "override_database",
            "sql": build_postgres_status_sql(),
            "label": "operations postgres status",
            "expected_shape": "object",
            "mode": "host_only",
            "psql_command": "/opt/bin/psql-wrapper",
        },
    ]
    assert default_status.to_jsonable() == override_status.to_jsonable()


@pytest.mark.parametrize(
    "message",
    (
        "psql command unavailable",
        "psycopg connection failed for operations postgres status",
        "database does not exist",
        "psycopg authentication failed for operations postgres status",
        "psycopg readback failed for operations postgres status",
        "invalid JSON for operations postgres status",
        "operations postgres status must return a JSON object",
        "conflicting PostgreSQL readback selectors",
        "unsupported PostgreSQL readback selector",
    ),
)
def test_psycopg98_adapter_failures_fold_into_typed_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    message: str,
) -> None:
    config = _config(tmp_path)

    def fail(*args, **kwargs):
        raise StorageSchemaError(message)

    _patch_adapter(monkeypatch, fail)

    status = check_ops_postgres_status(config)

    assert status.to_jsonable() == {
        "db_checked": True,
        "connected": False,
        "schema_available": False,
        "required_tables": {},
        "error": message,
    }


@pytest.mark.parametrize(
    ("payload", "expected_connected", "expected_schema", "expected_tables"),
    (
        ({}, False, False, {}),
        (
            {
                "connected": "truthy",
                "schema_available": [],
                "required_tables": {
                    "repositories": "yes",
                    "extra_table": 1,
                    "zero": 0,
                    "empty": [],
                },
                "ignored": "extra",
            },
            True,
            False,
            {
                "repositories": True,
                "extra_table": True,
                "zero": False,
                "empty": False,
            },
        ),
        (
            {
                "connected": 0,
                "schema_available": {"truthy": True},
                "required_tables": ["not", "an", "object"],
            },
            False,
            True,
            {},
        ),
    ),
)
def test_psycopg98_permissive_conversion_and_projection_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: dict[str, object],
    expected_connected: bool,
    expected_schema: bool,
    expected_tables: dict[str, bool],
) -> None:
    config = _config(tmp_path)
    _patch_adapter(monkeypatch, lambda *args, **kwargs: payload)

    status = check_ops_postgres_status(config)

    assert status.connected is expected_connected
    assert status.schema_available is expected_schema
    assert status.required_tables == expected_tables
    assert status.to_jsonable() == {
        "db_checked": True,
        "connected": expected_connected,
        "schema_available": expected_schema,
        "required_tables": expected_tables,
        "error": None,
    }


def test_psycopg101_config_and_graphs_use_nullable_command_defaults() -> None:
    parser = build_parser()
    config_args = parser.parse_args(["ops", "config-check", "--check-db"])
    graphs_args = parser.parse_args(["ops", "graphs", "--check-db"])
    explicit_args = parser.parse_args(
        [
            "ops",
            "config-check",
            "--check-db",
            "--psql-command",
            "/opt/bin/psql-wrapper",
        ]
    )
    config_parser = _subparser(parser, "ops", "config-check")
    config_command_action = next(
        action for action in config_parser._actions if action.dest == "psql_command"
    )
    graphs_parser = _subparser(parser, "ops", "graphs")
    graphs_command_action = next(
        action for action in graphs_parser._actions if action.dest == "psql_command"
    )
    config_help_text = config_command_action.help or ""
    graphs_help_text = graphs_command_action.help or ""

    assert config_args.psql_command is None
    assert graphs_args.psql_command is None
    assert explicit_args.psql_command == "/opt/bin/psql-wrapper"
    assert "defaults to Psycopg" in config_help_text
    assert "forces" in config_help_text
    assert "defaults to Psycopg" in graphs_help_text
    assert "forces" in graphs_help_text


@pytest.mark.parametrize("psql_command", (None, "/opt/bin/psql-wrapper"))
def test_psycopg98_readiness_failures_never_plan_topology(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    psql_command: str | None,
) -> None:
    config = _config(tmp_path)
    import repomap_kg.ops.readback as readback
    calls: list[dict[str, Any]] = []

    def select_driver():
        if psql_command is not None:
            pytest.fail("explicit readiness command resolved selectors")
        return "psql"

    def execute(*args, **kwargs):
        calls.append(kwargs)
        raise OSError("public-safe unavailable command")

    def fail_topology(*args, **kwargs):
        pytest.fail("host-only readiness inspected operational topology")

    monkeypatch.setattr(readback, "selected_json_readback_driver", select_driver)
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", execute)
    monkeypatch.setattr(readback, "_runtime_plan", fail_topology)
    monkeypatch.setattr(readback, "_container_psql_execution", fail_topology)
    monkeypatch.setattr(readback, "_resolve_container_readback_plan", fail_topology)

    status = check_ops_postgres_status(config, psql_command=psql_command)

    assert status.db_checked is True
    assert status.connected is False
    assert status.schema_available is False
    assert status.required_tables == {}
    assert status.error is not None
    assert len(calls) == 1
    assert calls[0]["driver"] == "psql"
    assert calls[0]["psql_command"] == (psql_command or "psql")


def test_psycopg98_graph_storage_short_circuits_and_continues_later_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    adapter_calls: list[dict[str, Any]] = []

    def execute(config_arg, **kwargs):
        adapter_calls.append(kwargs)
        if (
            kwargs["label"] == "operations postgres status"
            and kwargs["database"] == "repomap_test"
        ):
            raise StorageSchemaError("first database unavailable")
        if kwargs["label"] == "operations graph storage status":
            return {
                "graphs": [
                    {
                        "repository_name": "second-repository",
                        "repository_exists": True,
                    }
                ]
            }
        return {
            "connected": True,
            "schema_available": True,
            "required_tables": {"repositories": True},
        }

    _patch_adapter(monkeypatch, execute)

    statuses = check_ops_graph_storage_status(
        config,
        psql_command="/opt/bin/psql-wrapper",
    )

    assert statuses["first-graph"].error == "first database unavailable"
    assert statuses["first-graph"].repository_exists is False
    assert statuses["second-graph"].repository_exists is True
    assert [call["database"] for call in adapter_calls] == [
        "repomap_test",
        "second_database",
        "second_database",
    ]
    assert all(
        call["psql_command"] == "/opt/bin/psql-wrapper" for call in adapter_calls
    )
    assert adapter_calls[-1]["label"] == "operations graph storage status"


def test_psycopg98_readiness_moves_without_other_operational_owners() -> None:
    import repomap_kg.ops.config as module
    readiness_source = inspect.getsource(module.check_ops_postgres_status)
    graph_source = inspect.getsource(module.check_ops_graph_storage_status)

    assert "execute_ops_json_readback" in readiness_source
    assert "run_psql" not in readiness_source
    assert "parse_psql_json" not in readiness_source
    assert "execute_ops_json_readback" in graph_source
    assert "run_psql" not in graph_source
    assert "parse_psql_json" not in graph_source
