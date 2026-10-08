from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.ops.config import (
    check_ops_graph_storage_status,
    check_ops_postgres_status,
    load_ops_config,
)
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.readback_driver import (
    PG_CONNECTOR_ENV, READBACK_DRIVER_ENV, diagnose_psycopg_database_presence,
    execute_json_readback_with_driver,
)
import pytest


def test_psycopg98_postgres_readiness_connector_cli_and_graph_parity() -> None:
    require_postgres_binaries()
    selectors = (PG_CONNECTOR_ENV, READBACK_DRIVER_ENV)
    previous = {
        name: (name in os.environ, os.environ.get(name))
        for name in (*selectors, "PGPASSWORD", "PATH")
    }
    try:
        with temporary_postgres() as postgres, tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            config_path = _write_config(base, postgres=postgres)
            config = load_ops_config(config_path)

            _select(None, None, postgres=postgres)
            empty_schema = check_ops_postgres_status(
                config,
                psql_command=postgres.psql_command,
            )
            assert empty_schema.connected is True
            assert empty_schema.schema_available is False
            assert len(empty_schema.required_tables or {}) == 9
            assert not any((empty_schema.required_tables or {}).values())

            from repomap_kg.ops import config as ops_config

            original_readback = ops_config.execute_ops_json_readback

            def short_circuit_readback(*args, **kwargs):
                if kwargs["label"] == "operations graph storage status":
                    raise AssertionError("graph SQL must be short-circuited")
                return original_readback(*args, **kwargs)

            with patch(
                "repomap_kg.ops.config.execute_ops_json_readback",
                side_effect=short_circuit_readback,
            ):
                short_circuit = check_ops_graph_storage_status(
                    config,
                    psql_command=postgres.psql_command,
                )
            assert short_circuit["public-graph"].schema_available is False
            assert short_circuit["public-graph"].repository_exists is False

            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )

            modes = (
                ("default", None, None),
                ("connector-psql", "psql", None),
                ("connector-psycopg", "psycopg", None),
                ("driver-psql", None, "psql"),
                ("driver-psycopg", None, "psycopg"),
            )
            payloads: dict[str, dict[str, Any]] = {}
            original_path = os.environ["PATH"]
            empty_bin = base / "empty-bin"
            empty_bin.mkdir()
            for name, connector, driver in modes:
                _select(connector, driver, postgres=postgres)
                os.environ["PATH"] = (
                    str(empty_bin) if name == "default" else original_path
                )
                payloads[name] = check_ops_postgres_status(config).to_jsonable()

            expected = payloads["connector-psql"]
            assert all(payload == expected for payload in payloads.values())
            assert expected["db_checked"] is True
            assert expected["connected"] is True
            assert expected["schema_available"] is True
            assert len(expected["required_tables"]) == 9
            assert all(expected["required_tables"].values())

            os.environ["PATH"] = original_path
            _select("psycopg", "psycopg", postgres=postgres)
            assert check_ops_postgres_status(config).to_jsonable() == expected

            os.environ[PG_CONNECTOR_ENV] = "conflicting-value"
            os.environ[READBACK_DRIVER_ENV] = "unsupported-value"
            explicit = check_ops_postgres_status(
                config,
                psql_command=postgres.psql_command,
            ).to_jsonable()
            assert explicit == expected

            _select(None, None, postgres=postgres)
            missing_database = check_ops_postgres_status(
                config,
                database="public_missing_database",
            ).to_jsonable()
            assert missing_database["db_checked"] is True
            assert missing_database["connected"] is False
            assert missing_database["schema_available"] is False
            assert missing_database["required_tables"] == {}
            assert "requested graph database is missing or not initialized" in str(missing_database["error"])
            assert "public_missing_database" not in str(missing_database["error"])

            os.environ[PG_CONNECTOR_ENV] = "conflict-a"
            os.environ[READBACK_DRIVER_ENV] = "conflict-b"
            conflict = check_ops_postgres_status(config).to_jsonable()
            assert conflict["connected"] is False
            assert "conflicting" in str(conflict["error"])

            os.environ[PG_CONNECTOR_ENV] = "unsupported"
            os.environ.pop(READBACK_DRIVER_ENV, None)
            unsupported = check_ops_postgres_status(config).to_jsonable()
            assert unsupported["connected"] is False
            assert "unsupported" in str(unsupported["error"])

            os.environ["PATH"] = original_path
            os.environ[PG_CONNECTOR_ENV] = "conflict-a"
            os.environ[READBACK_DRIVER_ENV] = "conflict-b"
            psql_cli, psql_raw = _run_cli(
                config_path,
                psql_command=postgres.psql_command,
            )
            _select(None, None, postgres=postgres)
            os.environ["PATH"] = str(empty_bin)
            default_cli, default_raw = _run_cli(config_path)
            assert psql_cli == default_cli
            assert psql_raw == default_raw == json.dumps(default_cli, sort_keys=True) + "\n"
            assert default_cli["postgres_status"] == expected

            os.environ["PATH"] = original_path
            graph_status = check_ops_graph_storage_status(
                config,
                psql_command=postgres.psql_command,
            )["public-graph"]
            assert graph_status.schema_available is True
            assert graph_status.repository_exists is False

            serialized = json.dumps(
                {
                    "direct": payloads,
                    "explicit": explicit,
                    "missing": missing_database,
                    "conflict": conflict,
                    "unsupported": unsupported,
                    "cli": default_cli,
                },
                sort_keys=True,
            )
            for forbidden in (
                "PUBLIC_SAFE_PASSWORD_VALUE",
                "password=private",
                "postgresql://",
                "PRIVATE_TOKEN",
                "raw psycopg cause",
            ):
                assert forbidden not in serialized
    finally:
        for name, (present, value) in previous.items():
            if present and value is not None:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)


def _write_config(base: Path, *, postgres) -> Path:
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
password_env = "PUBLIC_SAFE_PASSWORD"
[[graphs]]
id = "public-graph"
name = "Public Graph"
root_path = "/public/psycopg98-root"
repository_name = "public-repository"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[server_memory]
enabled = false
path = "./public-server-memory"
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


def _run_cli(
    config_path: Path,
    *,
    psql_command: str | None = None,
) -> tuple[dict[str, Any], str]:
    args = [
        "ops",
        "config-check",
        "--config",
        str(config_path),
        "--check-db",
        "--json",
    ]
    if psql_command is not None:
        args.extend(("--psql-command", psql_command))
    exit_code, stdout, stderr = run_repo_map_in_process(*args)
    assert exit_code == 0, stderr
    return json.loads(stdout), stdout

@pytest.mark.parametrize("options", [
    "", "-c statement_timeout=1s", "-cstatement_timeout=0",
    "-c default_transaction_read_only=off -c application_name=fixture",
])
def test_catalog_diagnostics_and_json_readback_use_real_configured_database(options, monkeypatch):
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        monkeypatch.setenv("PGPASSWORD", postgres.password)
        monkeypatch.setenv("PGOPTIONS", options)
        monkeypatch.delenv("PGCONNECT_TIMEOUT", raising=False)
        assert diagnose_psycopg_database_presence(
            psql_args=postgres.psql_args, target_database=postgres.database,
        ) == "present"
        assert diagnose_psycopg_database_presence(
            psql_args=postgres.psql_args, target_database="absent_fixture_database",
            timeout_seconds=5,
        ) == "absent"
        for driver in ("psql", "psycopg"):
            args = dict(psql_args=postgres.psql_args, psql_command=postgres.psql_command,
                        label="fixture readback", driver=driver)
            assert execute_json_readback_with_driver(
                "SELECT json_build_object('state', 'ready', 'count', 2)",
                expected_shape="object", **args,
            ) == {"state": "ready", "count": 2}
            assert execute_json_readback_with_driver(
                "SELECT json_build_array('alpha', 'beta')", expected_shape="array", **args,
            ) == ["alpha", "beta"]
            with pytest.raises(StorageSchemaError, match="as a JSON object"):
                execute_json_readback_with_driver(
                    "SELECT json_build_array('alpha')", expected_shape="object", **args,
                )
        monkeypatch.setenv("PGOPTIONS", "-c statement_timeout=invalid")
        assert diagnose_psycopg_database_presence(
            psql_args=postgres.psql_args, target_database=postgres.database,
        ) == "unavailable"
        monkeypatch.setenv("PGOPTIONS", options)
        assert diagnose_psycopg_database_presence(
            psql_args=postgres.psql_args, target_database=postgres.database,
        ) == "present"
