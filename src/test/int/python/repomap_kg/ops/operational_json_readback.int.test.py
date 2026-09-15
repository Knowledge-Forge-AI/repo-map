from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.readback import execute_ops_json_readback
from repomap_kg.ops.refresh import query_refresh_status, refresh_status_to_jsonable
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV
from repomap_kg.storage.sql_core import sql_literal


def test_psycopg94_operational_refresh_status_connector_cli_and_mcp_parity() -> None:
    require_postgres_binaries()
    invalid_psql = "/bin/psql-not-used-by-psycopg94"
    selectors = (PG_CONNECTOR_ENV, READBACK_DRIVER_ENV)
    previous = {
        name: (name in os.environ, os.environ.get(name))
        for name in (*selectors, "PGPASSWORD", "REPOMAP_OPS_CONFIG", "REPOMAP_PSQL_COMMAND")
    }
    try:
        with temporary_postgres() as postgres, tempfile.TemporaryDirectory() as tmpdir:
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            root_path = "/tmp/psycopg94-public-root"
            repository_name = "psycopg94-public-repository"
            _seed_repository(postgres, root_path=root_path, name=repository_name)
            config_path = _write_config(
                Path(tmpdir),
                postgres=postgres,
                root_path=root_path,
                repository_name=repository_name,
            )
            config = load_ops_config(config_path)

            modes = (
                ("default", None, None, None),
                ("connector-psql", "psql", None, None),
                ("connector-psycopg", "psycopg", None, None),
                ("driver-psql", None, "psql", None),
                ("driver-psycopg", None, "psycopg", None),
            )
            payloads = {}
            arrays = {}
            for name, connector, driver, command in modes:
                _select(connector, driver, postgres=postgres)
                statuses = query_refresh_status(
                    config,
                    graph_ids=["public-graph"],
                    psql_command=command,
                )
                payloads[name] = refresh_status_to_jsonable(
                    config,
                    statuses,
                    graph_ids=["public-graph"],
                )
                arrays[name] = execute_ops_json_readback(
                    config,
                    database="postgres",
                    sql="SELECT json_build_array(1, 2, 3);",
                    label="operations array",
                    expected_shape="array",
                    mode="host_only",
                    psql_command=command,
                )

            expected = payloads["connector-psql"]
            assert all(payload == expected for payload in payloads.values())
            assert all(payload == [1, 2, 3] for payload in arrays.values())
            graph = expected["graphs"][0]
            assert graph["graph_id"] == "public-graph"
            assert graph["repository_exists"] is True
            assert graph["latest_run_status"] == "complete"
            assert graph["raw_observations"] == 1

            _select("psycopg", "psycopg", postgres=postgres)
            dual = refresh_status_to_jsonable(
                config,
                query_refresh_status(config, graph_ids=["public-graph"]),
                graph_ids=["public-graph"],
            )
            assert dual == expected

            os.environ[PG_CONNECTOR_ENV] = "conflict-a"
            os.environ[READBACK_DRIVER_ENV] = "conflict-b"
            explicit = refresh_status_to_jsonable(
                config,
                query_refresh_status(
                    config,
                    graph_ids=["public-graph"],
                    psql_command=postgres.psql_command,
                ),
                graph_ids=["public-graph"],
            )
            assert explicit == expected

            _select("psql", None, postgres=postgres)
            psql_cli, psql_raw = _run_cli(config_path, postgres.psql_command)
            _select(None, None, postgres=postgres)
            default_cli, default_raw = _run_cli(config_path, invalid_psql)
            assert psql_cli == default_cli == expected
            assert psql_raw == default_raw == json.dumps(expected, sort_keys=True) + "\n"

            from repomap_kg.server.mcp import repomap_graph_status, repomap_refresh_status

            _select(None, None, postgres=postgres)
            with patch.dict(
                os.environ,
                {"REPOMAP_OPS_CONFIG": str(config_path)},
                clear=False,
            ):
                os.environ.pop("REPOMAP_PSQL_COMMAND", None)
                graph_status = repomap_graph_status(graph_id="public-graph")
                refresh_status = repomap_refresh_status(graph_id="public-graph")
            serialized = json.dumps(
                {
                    "direct": payloads,
                    "dual": dual,
                    "explicit": explicit,
                    "cli": default_cli,
                    "graph_status": graph_status,
                    "refresh_status": refresh_status,
                },
                sort_keys=True,
            )
            for forbidden in (
                str(postgres.socket_dir),
                "password=private",
                "PRIVATE_TOKEN",
                "private-request-body",
            ):
                assert forbidden not in serialized
    finally:
        for name, (present, value) in previous.items():
            if present and value is not None:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)


def _seed_repository(postgres, *, root_path: str, name: str) -> None:
    root = sql_literal(root_path)
    postgres.psql_scalar(
        "INSERT INTO repositories(name, root_path, repository_identity) VALUES "
        f"({sql_literal(name)}, {root}, 'repo1:public-graph'); "
        "INSERT INTO runs(repository_id, status, finished_at) SELECT id, "
        "'complete', CURRENT_TIMESTAMP FROM repositories "
        f"WHERE root_path = {root}; "
        "INSERT INTO raw_observations(repository_id, run_id, ordinal, "
        "schema_version, kind, source_id, path, payload_json, payload_hash) "
        "SELECT r.id, ru.id, 0, 1, 'file', 'public-source', 'README.md', "
        "'{\"kind\":\"file\"}'::jsonb, repeat('1', 64) FROM repositories r "
        "JOIN runs ru ON ru.repository_id = r.id "
        f"WHERE r.root_path = {root}; SELECT COUNT(*)::text FROM repositories;"
    )


def _write_config(base: Path, *, postgres, root_path: str, repository_name: str) -> Path:
    path = base / "repomap.local.toml"
    path.write_text(
        f'''schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
[postgres]
host = "{postgres.socket_dir}"
port = {postgres.port}
database = "repomap_test"
user = "{postgres.user}"
[[graphs]]
id = "public-graph"
name = "Public Graph"
root_path = "{root_path}"
repository_name = "{repository_name}"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[server_memory]
enabled = false
path = "~/.codex/server-memory"
mode = "read_only"
''',
        encoding="utf-8",
    )
    return path


def _select(connector: str | None, driver: str | None, *, postgres) -> None:
    for name, value in ((PG_CONNECTOR_ENV, connector), (READBACK_DRIVER_ENV, driver)):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    if postgres.password:
        os.environ["PGPASSWORD"] = postgres.password


def _run_cli(config_path: Path, psql_command: str) -> tuple[dict[str, object], str]:
    command_env = os.environ.get("REPOMAP_PSQL_COMMAND")
    try:
        if "not-used" in psql_command:
            os.environ.pop("REPOMAP_PSQL_COMMAND", None)
        else:
            os.environ["REPOMAP_PSQL_COMMAND"] = psql_command
        exit_code, stdout, stderr = run_repo_map_in_process(
            "ops",
            "refresh-status",
            "--config",
            str(config_path),
            "--graph",
            "public-graph",
            "--json",
        )
    finally:
        if command_env is None:
            os.environ.pop("REPOMAP_PSQL_COMMAND", None)
        else:
            os.environ["REPOMAP_PSQL_COMMAND"] = command_env
    assert exit_code == 0, stderr
    return json.loads(stdout), stdout
