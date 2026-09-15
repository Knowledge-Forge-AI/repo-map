from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.ops.config import check_ops_graph_storage_status, load_ops_config
from repomap_kg.storage import (
    StorageSchemaError,
    apply_migrations,
    default_rdbms_root,
    run_psql,
    sql_literal,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV


SECOND_DATABASE = "public_second"
MISSING_DATABASE = "public_missing"


def test_psycopg101_graph_storage_connector_cli_failure_and_privacy_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    selectors = (PG_CONNECTOR_ENV, READBACK_DRIVER_ENV)
    previous = {
        name: (name in os.environ, os.environ.get(name))
        for name in (*selectors, "PGPASSWORD", "PATH", "PUBLIC_SAFE_PASSWORD")
    }
    try:
        with temporary_postgres() as postgres, tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            postgres.psql_scalar(f"CREATE DATABASE {SECOND_DATABASE};")
            postgres.psql_scalar(f"CREATE DATABASE {MISSING_DATABASE};")
            primary_args = postgres.psql_args
            second_args = _database_args(postgres.psql_args, SECOND_DATABASE)
            missing_args = _database_args(postgres.psql_args, MISSING_DATABASE)
            for args in (primary_args, missing_args, second_args):
                apply_migrations(
                    default_rdbms_root(),
                    args,
                    psql_command=postgres.psql_command,
                )
            _seed_repository(
                postgres,
                primary_args,
                repository_name="public-main",
                root_path="/public/main",
                repository_identity="repo1:main",
            )
            _seed_repository(
                postgres,
                second_args,
                repository_name="public-second",
                root_path="/public/second",
                repository_identity="repo1:second",
            )
            config_path = _write_config(base, postgres=postgres)
            config = load_ops_config(config_path)

            import repomap_kg.ops.readback as readback

            def fail_topology(*args, **kwargs):
                pytest.fail("host-only graph storage inspected topology")

            monkeypatch.setattr(readback, "_runtime_plan", fail_topology)
            monkeypatch.setattr(readback, "_container_psql_execution", fail_topology)
            monkeypatch.setattr(readback, "_resolve_container_readback_plan", fail_topology)

            modes = (
                ("default", None, None),
                ("connector-psql", "psql", None),
                ("connector-psycopg", "psycopg", None),
                ("driver-psql", None, "psql"),
                ("driver-psycopg", None, "psycopg"),
            )
            payloads: dict[str, dict[str, dict[str, Any]]] = {}
            original_path = os.environ["PATH"]
            empty_bin = base / "empty-bin"
            empty_bin.mkdir()
            for name, connector, driver in modes:
                _select(connector, driver, postgres=postgres)
                os.environ["PATH"] = (
                    str(empty_bin) if name == "default" else original_path
                )
                payloads[name] = _jsonable(check_ops_graph_storage_status(config))

            expected = payloads["connector-psql"]
            assert all(payload == expected for payload in payloads.values())
            assert list(expected) == ["main", "missing", "second"]
            assert expected["main"]["repository_exists"] is True
            assert expected["main"]["raw_observations"] == 1
            assert expected["main"]["raw_observations_total"] == 1
            assert expected["main"]["latest_run_raw_observations"] == 1
            assert expected["main"]["canonical_nodes"] == 2
            assert expected["main"]["canonical_edges"] == 1
            assert expected["missing"]["repository_exists"] is False
            assert expected["missing"]["raw_observations"] == 0
            assert expected["second"]["repository_exists"] is True

            os.environ["PATH"] = original_path
            _select("psycopg", "psycopg", postgres=postgres)
            assert _jsonable(check_ops_graph_storage_status(config)) == expected

            os.environ[PG_CONNECTOR_ENV] = "conflicting-value"
            os.environ[READBACK_DRIVER_ENV] = "unsupported-value"
            explicit = _jsonable(
                check_ops_graph_storage_status(
                    config,
                    psql_command=postgres.psql_command,
                )
            )
            assert explicit == expected

            psql_cli, psql_raw = _run_cli(
                config_path,
                psql_command=postgres.psql_command,
            )
            _select(None, None, postgres=postgres)
            os.environ["PATH"] = str(empty_bin)
            default_cli, default_raw = _run_cli(config_path)
            assert psql_cli == default_cli
            assert psql_raw == default_raw == json.dumps(default_cli, sort_keys=True) + "\n"

            os.environ["PATH"] = original_path
            _select(None, None, postgres=postgres)
            partial_config = load_ops_config(
                _write_partial_config(base, postgres=postgres)
            )
            readiness_partial = _jsonable(
                check_ops_graph_storage_status(partial_config)
            )
            assert readiness_partial["unavailable"]["repository_exists"] is False
            assert readiness_partial["unavailable"]["error"] is not None
            assert readiness_partial["after"]["repository_exists"] is True

            import repomap_kg.ops.config as config_module

            original_readback = config_module.execute_ops_json_readback

            def fail_first_graph_stage(config_arg, **kwargs):
                if (
                    kwargs["label"] == "operations graph storage status"
                    and kwargs["database"] == postgres.database
                ):
                    raise StorageSchemaError("public graph stage unavailable")
                return original_readback(config_arg, **kwargs)

            with patch(
                "repomap_kg.ops.config.execute_ops_json_readback",
                side_effect=fail_first_graph_stage,
            ):
                graph_partial = _jsonable(
                    check_ops_graph_storage_status(
                        config,
                        psql_command=postgres.psql_command,
                    )
                )
                assert graph_partial["main"]["error"] == "public graph stage unavailable"
                assert graph_partial["missing"]["error"] is None
                assert graph_partial["missing"]["repository_exists"] is False
            assert graph_partial["second"]["repository_exists"] is True

            os.environ[PG_CONNECTOR_ENV] = "conflict-a"
            os.environ[READBACK_DRIVER_ENV] = "conflict-b"
            conflict = _jsonable(check_ops_graph_storage_status(config))
            assert all(status["error"] for status in conflict.values())

            os.environ[PG_CONNECTOR_ENV] = "unsupported"
            os.environ.pop(READBACK_DRIVER_ENV, None)
            unsupported = _jsonable(check_ops_graph_storage_status(config))
            assert all(status["error"] for status in unsupported.values())

            unavailable = _jsonable(
                check_ops_graph_storage_status(
                    config,
                    psql_command="/public/missing/psql",
                )
            )
            assert all(status["error"] for status in unavailable.values())

            serialized = json.dumps(
                {
                    "direct": payloads,
                    "explicit": explicit,
                    "cli": default_cli,
                    "readiness_partial": readiness_partial,
                    "graph_partial": graph_partial,
                    "conflict": conflict,
                    "unsupported": unsupported,
                    "unavailable": unavailable,
                },
                sort_keys=True,
            )
            for forbidden in (
                "PUBLIC_SAFE_PASSWORD_VALUE",
                "password=private",
                "postgresql://",
                "PRIVATE_TOKEN",
                "raw psycopg cause",
                "private-source-content",
            ):
                assert forbidden not in serialized
    finally:
        for name, (present, value) in previous.items():
            if present and value is not None:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)


def _database_args(psql_args: list[str], database: str) -> list[str]:
    args = list(psql_args)
    args[args.index("-d") + 1] = database
    return args


def _execute(postgres, psql_args: list[str], sql: str) -> None:
    run_psql(
        [postgres.psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=sql,
    )


def _seed_repository(
    postgres,
    psql_args: list[str],
    *,
    repository_name: str,
    root_path: str,
    repository_identity: str,
) -> None:
    repository = sql_literal(repository_name)
    root = sql_literal(root_path)
    identity = sql_literal(repository_identity)
    node_a = sql_literal(f"public.node:{repository_name}:a")
    node_b = sql_literal(f"public.node:{repository_name}:b")
    _execute(
        postgres,
        psql_args,
        "INSERT INTO repositories(name, root_path, repository_identity) VALUES "
        f"({repository}, {root}, {identity}); "
        "INSERT INTO runs(repository_id, status, finished_at) SELECT id, "
        "'complete', CURRENT_TIMESTAMP FROM repositories "
        f"WHERE name = {repository}; "
        "INSERT INTO raw_observations(repository_id, run_id, ordinal, "
        "schema_version, kind, source_id, path, payload_json, payload_hash) "
        "SELECT r.id, ru.id, 0, 1, 'file', 'public-source', 'README.md', "
        "'{\"kind\":\"file\"}'::jsonb, repeat('1', 64) FROM repositories r "
        "JOIN runs ru ON ru.repository_id = r.id "
        f"WHERE r.name = {repository}; "
        "INSERT INTO canonical_nodes(repository_id, graph_key_version, "
        "canonical_key, kind, display_name, metadata_json, confidence) "
        "SELECT id, 1, key, 'file', key, '{}'::jsonb, 'extracted' "
        "FROM repositories CROSS JOIN "
        f"(VALUES ({node_a}), ({node_b})) AS keys(key) WHERE name = {repository}; "
        "INSERT INTO canonical_edges(repository_id, graph_key_version, "
        "source_canonical_key, edge_kind, target_canonical_key, "
        "identity_metadata_hash, confidence) SELECT id, 1, "
        f"{node_a}, 'references', {node_b}, repeat('0', 64), 'extracted' "
        f"FROM repositories WHERE name = {repository};",
    )


def _write_config(base: Path, *, postgres) -> Path:
    return _write_config_text(
        base / "repomap.local.toml",
        postgres=postgres,
        graphs=f'''\
[[graphs]]
id = "main"
name = "Public Main"
root_path = "/public/main"
repository_name = "public-main"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[[graphs]]
id = "missing"
name = "Public Missing"
root_path = "/public/missing"
repository_name = "public-missing"
database = "{MISSING_DATABASE}"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[[graphs]]
id = "second"
name = "Public Second"
root_path = "/public/second"
repository_name = "public-second"
database = "{SECOND_DATABASE}"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
''',
    )


def _write_partial_config(base: Path, *, postgres) -> Path:
    return _write_config_text(
        base / "repomap.partial.toml",
        postgres=postgres,
        graphs='''\
[[graphs]]
id = "unavailable"
name = "Public Unavailable"
root_path = "/public/unavailable"
repository_name = "public-unavailable"
database = "public_missing_database"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[[graphs]]
id = "after"
name = "Public After"
root_path = "/public/after"
repository_name = "public-main"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
''',
    )


def _write_config_text(path: Path, *, postgres, graphs: str) -> Path:
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
{graphs}
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
    os.environ["PUBLIC_SAFE_PASSWORD"] = "PUBLIC_SAFE_PASSWORD_VALUE"


def _jsonable(statuses) -> dict[str, dict[str, Any]]:
    return {graph_id: status.to_jsonable() for graph_id, status in statuses.items()}


def _run_cli(
    config_path: Path,
    *,
    psql_command: str | None = None,
) -> tuple[dict[str, Any], str]:
    args = ["ops", "graphs", "--config", str(config_path), "--check-db", "--json"]
    if psql_command is not None:
        args.extend(("--psql-command", psql_command))
    exit_code, stdout, stderr = run_repo_map_in_process(*args)
    assert exit_code == 0, stderr
    return json.loads(stdout), stdout
