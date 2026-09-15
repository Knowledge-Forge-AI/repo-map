from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.server.mcp import (
    RepoMapMcpError,
    repomap_search_files,
    repomap_search_nodes,
    repomap_search_observations,
)
from repomap_kg.storage import (
    apply_migrations,
    default_rdbms_root,
    run_psql,
)
from repomap_kg.storage.readback_driver import PG_CONNECTOR_ENV, READBACK_DRIVER_ENV


def test_psycopg108_mcp_search_connector_pagination_raw_and_privacy_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    names = (
        PG_CONNECTOR_ENV,
        READBACK_DRIVER_ENV,
        "REPOMAP_OPS_CONFIG",
        "REPOMAP_PSQL_COMMAND",
        "PGPASSWORD",
        "PATH",
        "PUBLIC_SAFE_PASSWORD",
    )
    previous = {name: (name in os.environ, os.environ.get(name)) for name in names}
    try:
        with temporary_postgres() as postgres, tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            apply_migrations(
                default_rdbms_root(),
                postgres.psql_args,
                psql_command=postgres.psql_command,
            )
            _seed(postgres)
            private_postgres = postgres.create_database("repomap_test_private_search")
            apply_migrations(
                default_rdbms_root(),
                private_postgres.psql_args,
                psql_command=private_postgres.psql_command,
            )
            _seed(private_postgres)
            config_path = _write_config(base, postgres=postgres)
            os.environ["REPOMAP_OPS_CONFIG"] = str(config_path)

            import repomap_kg.ops.readback as readback

            def fail_topology(*args, **kwargs):
                pytest.fail("successful host MCP search inspected topology")

            monkeypatch.setattr(readback, "_runtime_plan", fail_topology)
            monkeypatch.setattr(readback, "_container_psql_execution", fail_topology)
            monkeypatch.setattr(readback, "_resolve_container_readback_plan", fail_topology)

            original_path = os.environ["PATH"]
            psql_path = (
                str(Path(postgres.psql_command).parent)
                + os.pathsep
                + original_path
            )
            empty_bin = base / "empty-bin"
            empty_bin.mkdir()
            modes = (
                ("default", None, None, None),
                ("connector-psql", "psql", None, None),
                ("connector-psycopg", "psycopg", None, None),
                ("driver-psql", None, "psql", None),
                ("driver-psycopg", None, "psycopg", None),
                ("dual-psycopg", "psycopg", "psycopg", None),
                ("explicit", "conflict-a", "unsupported-value", postgres.psql_command),
            )
            payloads: dict[str, dict[str, object]] = {}
            for name, connector, driver, command in modes:
                _select(connector, driver, command=command, postgres=postgres)
                os.environ["PATH"] = (
                    str(empty_bin) if name == "default" else psql_path
                )
                payloads[name] = _public_payloads()

            expected = payloads["connector-psql"]
            assert all(payload == expected for payload in payloads.values())
            files = expected["files"]
            assert isinstance(files, dict)
            assert files["result_count"] == 1
            assert files["has_more"] is True
            assert files["total"] == 1
            files_results = files["results"]
            assert isinstance(files_results, list)
            assert files_results[0]["path"] == "README.md"
            nodes = expected["nodes"]
            assert isinstance(nodes, dict)
            nodes_results = nodes["results"]
            assert isinstance(nodes_results, list)
            assert nodes_results[0]["canonical_key"] == "public:a"
            obs = expected["observations"]
            assert isinstance(obs, dict)
            obs_results = obs["results"]
            assert isinstance(obs_results, list)
            assert "payload" not in obs_results[0]
            raw_obs = expected["raw_observations"]
            assert isinstance(raw_obs, dict)
            raw_obs_results = raw_obs["results"]
            assert isinstance(raw_obs_results, list)
            assert raw_obs_results[0]["payload"] == {
                "detail": "public-safe",
                "metadata": {"category": "public"},
            }

            private_payload = repomap_search_files(
                graph_id="private-visible",
                query="README",
            )
            assert private_payload["graph"]["root_path_display"] == "[private-root]"
            assert private_payload["graph"]["database"] == "[private-database]"
            serialized = json.dumps(
                {"public": expected, "private": private_payload},
                sort_keys=True,
            )
            for forbidden in (
                "PUBLIC_SAFE_PASSWORD_VALUE",
                "postgresql://",
                "raw psycopg cause",
                "PRIVATE_TOKEN",
                str(config_path),
            ):
                assert forbidden not in serialized

            _select(
                "conflict-a",
                "unsupported-value",
                command=postgres.psql_command,
                postgres=postgres,
            )
            with pytest.raises(RepoMapMcpError, match="missing or not initialized"):
                repomap_search_files(graph_id="missing-database", query="README")
    finally:
        for name, (present, value) in previous.items():
            if present and value is not None:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)


def _public_payloads() -> dict[str, object]:
    return {
        "files": repomap_search_files(
            graph_id="public",
            query=".",
            limit=1,
        ),
        "nodes": repomap_search_nodes(
            graph_id="public",
            query="public:",
            kind="file",
            limit=2,
        ),
        "observations": repomap_search_observations(
            graph_id="public",
            query="file",
            kind="file",
            path="README.md",
            include_raw=False,
        ),
        "raw_observations": repomap_search_observations(
            graph_id="public",
            query="file",
            kind="file",
            path="README.md",
            include_raw=True,
        ),
    }


def _seed(postgres) -> None:
    run_psql(
        [
            postgres.psql_command,
            *postgres.psql_args,
            "-qAt",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input_text="""
INSERT INTO repositories(name, root_path)
VALUES ('public-repository', '/public/repository');
INSERT INTO runs(repository_id, status, finished_at)
SELECT id, 'complete', CURRENT_TIMESTAMP FROM repositories
WHERE name = 'public-repository';
INSERT INTO files(repository_id, path, language, role)
SELECT id, 'README.md', 'markdown', 'documentation' FROM repositories
WHERE name = 'public-repository';
INSERT INTO files(repository_id, path, language, role)
SELECT id, 'src/main.py', 'python', 'source' FROM repositories
WHERE name = 'public-repository';
INSERT INTO raw_observations(repository_id, run_id, ordinal, schema_version,
kind, source_id, path, payload_json, payload_hash)
SELECT r.id, ru.id, 0, 1, 'file', 'README.md', 'README.md',
       '{"metadata":{"category":"public"},"detail":"public-safe"}'::jsonb,
       repeat('1', 64)
FROM repositories r JOIN runs ru ON ru.repository_id = r.id
WHERE r.name = 'public-repository';
INSERT INTO canonical_nodes(repository_id, graph_key_version, canonical_key,
kind, display_name, metadata_json, confidence)
SELECT r.id, 1, key, 'file', key, '{}'::jsonb, 'extracted'
FROM repositories r CROSS JOIN (VALUES ('public:a'), ('public:b')) AS keys(key)
WHERE r.name = 'public-repository';
""",
    )


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
id = "public"
name = "Public"
root_path = "/public/repository"
repository_name = "public-repository"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
[[graphs]]
id = "private-visible"
name = "Private Visible"
root_path = "/public/repository"
repository_name = "public-repository"
database = "repomap_test_private_search"
privacy = "private-ops"
enabled = true
mcp_visible = true
extractor_profile = "private"
refresh_policy = "manual"
[[graphs]]
id = "missing-database"
name = "Missing Database"
root_path = "/public/repository"
repository_name = "public-repository"
privacy = "public-dev"
enabled = true
mcp_visible = true
extractor_profile = "default"
refresh_policy = "manual"
database = "public_missing_database"
[server_memory]
enabled = false
path = "./public-server-memory"
mode = "read_only"
''',
        encoding="utf-8",
    )
    return path


def _select(
    connector: str | None,
    driver: str | None,
    *,
    command: str | None,
    postgres,
) -> None:
    for name, value in (
        (PG_CONNECTOR_ENV, connector),
        (READBACK_DRIVER_ENV, driver),
        ("REPOMAP_PSQL_COMMAND", command),
    ):
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    if postgres.password:
        os.environ["PGPASSWORD"] = postgres.password
    os.environ["PUBLIC_SAFE_PASSWORD"] = "PUBLIC_SAFE_PASSWORD_VALUE"
