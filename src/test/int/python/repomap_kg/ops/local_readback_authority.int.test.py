"""Disposable local-home readback and least-privilege role integration proof."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys

import psycopg
import pytest

from repomap_kg.observations.raw import read_observations_jsonl
from repomap_kg.ops.config import load_ops_config_home
from repomap_kg.ops.direct_publication import publish_observation_generation
from repomap_kg.ops.readback import execute_ops_json_readback
from repomap_kg.runtime.database_roles import (
    READ_STATUS_ROLE,
    RoleSecrets,
    render_database_role_sql,
)
from repomap_kg.runtime.local import setup_local_runtime
from repomap_kg.storage import apply_migrations, default_rdbms_root, run_psql
from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
from repomap_test_support.storage_integration import canonicalization_fixture


GRAPH_ID = "local-readback"
REPOSITORY_NAME = "local-readback"
ROOT_PATH = "/public/local-readback"
READBACK_DRIVER_ENV = "REPOMAP_STORAGE_READBACK_DRIVER"
READBACK_ENV_NAMES = (
    "PGPASSWORD",
    "REPOMAP_PG_PASSWORD",
    "REPOMAP_READ_STATUS_PASSWORD",
)


def test_setup_owned_local_readback_uses_read_role_without_password_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All supported local readbacks use the setup-owned read/status role."""

    require_postgres_binaries()
    with temporary_postgres() as postgres:
        apply_migrations(
            default_rdbms_root(),
            postgres.psql_args,
            psql_command=postgres.psql_command,
        )
        home = tmp_path / "repo-map-home"
        setup_local_runtime(home)
        env_file = home / "runtime" / ".env"
        env_text = env_file.read_text(encoding="utf-8")
        env_values = _env_values(env_text)
        role_secrets = RoleSecrets(
            read_status=_required_env_value(env_values, "REPOMAP_READ_STATUS_PASSWORD"),
            refresh_publication=_required_env_value(
                env_values, "REPOMAP_REFRESH_PUBLICATION_PASSWORD"
            ),
            coordinator_control=_required_env_value(
                env_values, "REPOMAP_COORDINATOR_CONTROL_PASSWORD"
            ),
        )
        credentials = tuple(v for k, v in env_values.items() if "PASSWORD" in k) + (postgres.password,)
        _emit_credential_fingerprints(credentials)
        _write_local_config(home, postgres.port, postgres.database)
        env_before = env_file.read_bytes()
        mode_before = stat.S_IMODE(env_file.stat().st_mode)
        captured: list[str] = []
        _load_public_fixture(postgres)
        _provision_graph_roles(postgres, role_secrets)

        for name in READBACK_ENV_NAMES:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv("REPOMAP_STORAGE_PG_CONNECTOR", raising=False)
        monkeypatch.setenv(READBACK_DRIVER_ENV, "psycopg")

        def invoke(*args: str) -> dict[str, object]:
            exit_code, stdout, stderr = run_repo_map_in_process(*args)
            captured.extend((stdout, stderr))
            if exit_code != 0:
                raise AssertionError("local readback command failed")
            return json.loads(stdout)

        status = invoke(
            "ops",
            "refresh-status",
            "--repo-map-home",
            str(home),
            "--graph",
            GRAPH_ID,
            "--json",
        )
        summary = invoke(
            "ops",
            "graph-summary",
            "--repo-map-home",
            str(home),
            "--graph",
            GRAPH_ID,
            "--json",
        )
        files = invoke(
            "ops",
            "graph-files",
            "--repo-map-home",
            str(home),
            "--graph",
            GRAPH_ID,
            "--json",
        )
        edges = invoke(
            "storage",
            "edges",
            "--repo-map-home",
            str(home),
            "--graph",
            GRAPH_ID,
            "--kind",
            "sources",
            "--json",
        )
        edge = _one_edge(edges)
        explanation = invoke(
            "storage",
            "explain-canonical-edge",
            "--repo-map-home",
            str(home),
            "--graph",
            GRAPH_ID,
            "--source-key",
            str(edge["source_key"]),
            "--kind",
            "sources",
            "--target-key",
            str(edge["target_key"]),
            "--identity-metadata-json",
            json.dumps(edge["identity_metadata"], sort_keys=True),
            "--json",
        )

        _assert_readback_shapes(status, summary, files, edge, explanation)
        identity = execute_ops_json_readback(
            load_ops_config_home(home), database=postgres.database,
            sql="SELECT json_build_object('role', current_user)",
            label="readback role", expected_shape="object", mode="host_only",
        )
        assert identity == {"role": READ_STATUS_ROLE}
        _assert_read_role_can_read_but_not_write(postgres, role_secrets.read_status)
        assert env_file.read_bytes() == env_before
        assert stat.S_IMODE(env_file.stat().st_mode) == mode_before
        assert all(name not in os.environ for name in READBACK_ENV_NAMES)
        _assert_credentials_absent(captured, credentials)


def _write_local_config(home: Path, host_port: int, database: str) -> None:
    (home / "repomap.rpl.toml").write_text(
        f'''schema_version = 1
[service]
mode = "local"
mcp_transport = "stdio"
log_level = "info"
[runtime]
coordinator_mode = "native"
container_runtime = "docker"
server_host_port = 18080
bind_host = "127.0.0.1"
[runtime.postgres]
direct_host_port_enabled = true
host_port = {host_port}
bind_host = "127.0.0.1"
[postgres]
host = "postgres"
port = 5432
database = "{database}"
user = "repomap"
password_env = "REPOMAP_PG_PASSWORD"
[[graphs]]
id = "{GRAPH_ID}"
name = "Local Readback"
root_path = "{ROOT_PATH}"
repository_name = "{REPOSITORY_NAME}"
privacy = "public-dev"
enabled = true
mcp_visible = false
extractor_profile = "default"
refresh_policy = "manual"
exclude_paths = []
[server_memory]
enabled = false
path = "./server-memory"
mode = "read_only"
''',
        encoding="utf-8",
    )


def _load_public_fixture(postgres):
    fixture = canonicalization_fixture("shell_source_static", "raw_observations.jsonl")
    publish_observation_generation(
        postgres.psql_args,
        read_observations_jsonl(fixture),
        repository_name=REPOSITORY_NAME,
        root_path=f"graph:{GRAPH_ID}",
        repository_identity=f"repo1:{GRAPH_ID}",
        psql_command=postgres.psql_command,
    )



def _provision_graph_roles(postgres, secrets: RoleSecrets) -> None:
    sql = render_database_role_sql(
        database=postgres.database,
        owner_role=postgres.user,
        database_kind="graph",
        secrets=secrets,
    )
    run_psql(
        [
            postgres.psql_command,
            *postgres.psql_args,
            "-qAt",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input_text=sql,
    )


def _assert_readback_shapes(
    status: dict[str, object],
    summary: dict[str, object],
    files: dict[str, object],
    edge: dict[str, object],
    explanation: dict[str, object],
) -> None:
    graphs = status.get("graphs")
    if (
        not isinstance(graphs, list)
        or len(graphs) != 1
        or not isinstance(graphs[0], dict)
    ):
        raise AssertionError("refresh-status did not return one graph")
    if graphs[0].get("latest_run_status") != "complete":
        raise AssertionError("refresh-status did not return the published run")
    graph_summary = summary.get("graph")
    canonical_edges = graph_summary.get("canonical_edges") if isinstance(graph_summary, dict) else None
    if (
        summary.get("result") != "success"
        or not isinstance(canonical_edges, int)
        or canonical_edges < 1
    ):
        raise AssertionError("graph-summary did not read the published graph")
    if files.get("result") != "success" or not files.get("files"):
        raise AssertionError("graph-files did not read canonical file rows")
    if edge.get("edge_kind") != "sources":
        raise AssertionError("source edge readback returned the wrong kind")
    result = explanation.get("result")
    edge_payload = result.get("edge") if isinstance(result, dict) else None
    if not isinstance(edge_payload, dict) or edge_payload.get("edge_kind") != "sources":
        raise AssertionError("canonical edge explanation did not read the source edge")


def _one_edge(payload: dict[str, object]) -> dict[str, object]:
    items = payload.get("items")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise AssertionError("expected exactly one synthetic source edge")
    return items[0]


def _assert_read_role_can_read_but_not_write(postgres, password: str) -> None:
    with psycopg.connect(
        host=postgres.host,
        port=postgres.port,
        dbname=postgres.database,
        user=READ_STATUS_ROLE,
        password=password,
    ) as connection:
        current_user = connection.execute("SELECT current_user").fetchone()
        if current_user != (READ_STATUS_ROLE,):
            raise AssertionError("readback did not connect as the read/status role")
        count = connection.execute("SELECT count(*) FROM canonical_nodes").fetchone()
        if count is None or int(count[0]) < 2:
            raise AssertionError("read/status role could not read the published graph")
        for statement in (
            "INSERT INTO repositories(name, root_path) VALUES ('readback-probe', '/public/probe')",
            "INSERT INTO runs(repository_id, status) VALUES (1, 'complete')",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement)
            connection.rollback()


def _env_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def _required_env_value(values: dict[str, str], name: str) -> str:
    value = values.get(name)
    if not value:
        raise AssertionError("setup did not create the required role secret")
    return value


def _assert_credentials_absent(output: list[str], values: tuple[str | None, ...]) -> None:
    combined = "\n".join(output)
    for value in values:
        if value and value in combined:
            raise AssertionError("readback output contained protected credential")


def _emit_credential_fingerprints(values: tuple[str | None, ...]) -> None:
    fingerprints = sorted(
        {
            (len(value), hashlib.sha256(value.encode("utf-8")).hexdigest())
            for value in values
            if value
        }
    )
    payload = [
        {"length": length, "sha256": digest}
        for length, digest in fingerprints
    ]
    stream = getattr(sys, "__stdout__", None)
    if stream is not None:
        stream.write(
            "CREDENTIAL_SCAN_FINGERPRINTS="
            + json.dumps(payload, sort_keys=True)
            + "\n"
        )
        stream.flush()
