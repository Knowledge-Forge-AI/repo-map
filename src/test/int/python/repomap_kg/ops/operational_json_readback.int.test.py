from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from repomap_test_support.cli_in_process import run_repo_map_in_process
from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)

from repomap_kg.ops.baselines import (
    _atomic_write_text,
    _baseline_kinds,
    _baseline_path_segment,
    _bool_or_false,
    _build_drift_payload,
    _drift_payload_detected,
    _ensure_path_under_baseline_root,
    _int_or_zero,
    _normalize_baseline_payload,
    _normalize_preflight_baseline_payload,
)
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.ingestion.github_api_config import validate_source_identity
from repomap_kg.ops.ingestion.github_api_helpers import GitHubApiPolicyError
from repomap_kg.ops.ingestion.source_common import (
    SourcePolicyError,
    _mapping,
    _optional_bool,
    _required_positive_int,
    _required_text,
    _validate_source_id,
)
from repomap_kg.ops.readback import execute_ops_json_readback
from repomap_kg.ops.refresh import query_refresh_status, refresh_status_to_jsonable
from repomap_kg.ops.reports import OpsGraphSummary, OpsRefreshError
from repomap_kg.storage import apply_migrations, default_rdbms_root
from repomap_kg.storage.authority import RefreshResult
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


def test_ops_baselines_normalization_and_drift_calculation() -> None:
    assert _normalize_baseline_payload({"baseline": {"files": 5}}) == {"files": 5}
    assert _normalize_baseline_payload({"graph": {"files": 8}}) == {"files": 8}
    assert _normalize_baseline_payload({"files": 10}) == {"files": 10}

    pre1 = _normalize_preflight_baseline_payload({"graph": {"files": 1}, "safety": {"strict": True}})
    assert pre1["safety"] == {"strict": True}
    pre2 = _normalize_preflight_baseline_payload({"graph": {"files": 1, "safety": {"strict": False}}})
    assert pre2["safety"] == {"strict": False}
    pre3 = _normalize_preflight_baseline_payload({"graph": {"files": 1}})
    assert pre3["safety"] == {}

    assert _int_or_zero(10) == 10
    assert _int_or_zero(True) == 1
    assert _int_or_zero(None) == 0
    assert _int_or_zero("42") == 42
    assert _int_or_zero("invalid") == 0

    assert _bool_or_false(True) is True
    assert _bool_or_false(False) is False
    assert _bool_or_false("true") is False

    summary = OpsGraphSummary(
        graph_id="g1",
        repository_name="repo1",
        database="db1",
        privacy="public-dev",
        enabled=True,
        mcp_visible=False,
        root_path_display=".",
        root_path_expanded=".",
        result=RefreshResult.SUCCESS,
        files=10,
        canonical_nodes=25,
        canonical_edges=20,
    )
    drift = _build_drift_payload(summary, {"files": 8, "canonical_nodes": 20})
    assert drift["files"]["current"] == 10
    assert drift["files"]["baseline"] == 8
    assert _drift_payload_detected(drift) is True

    assert _baseline_path_segment("valid_id", "id") == "valid_id"
    assert _baseline_kinds("stored") == ("stored",)
    assert _baseline_kinds("preflight") == ("preflight",)
    assert _baseline_kinds("both") == ("stored", "preflight")
    with pytest.raises(OpsRefreshError):
        _baseline_kinds("unsupported")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        file_p = root / "sample.txt"
        _atomic_write_text(file_p, "content", replace_existing=True)
        assert file_p.read_text(encoding="utf-8") == "content"
        _ensure_path_under_baseline_root(file_p, root)


def test_ops_ingestion_source_common_and_github_api_config_branches() -> None:
    with pytest.raises(SourcePolicyError):
        _mapping({"key": "not_map"}, "key")
    with pytest.raises(SourcePolicyError):
        _required_text({"t": "  "}, "t", "title")
    with pytest.raises(SourcePolicyError):
        _required_positive_int({"n": -1}, "n", "count")
    with pytest.raises(SourcePolicyError):
        _required_positive_int({"n": True}, "n", "count")
    with pytest.raises(SourcePolicyError):
        _optional_bool("not_bool", "flag", default=False)
    with pytest.raises(SourcePolicyError):
        _validate_source_id("https://bad.source")

    _validate_source_id("valid-source_1")

    with pytest.raises(GitHubApiPolicyError):
        validate_source_identity(
            source_type="invalid_type",
            api_source_class="public_anonymous_read_only",
            provider_name="GitHub",
            provider_product="GitHub REST API",
            policy_status="allowed",
            owner="octocat",
            repository="Hello-World",
            repository_visibility="public",
            read_only=True,
            mutation_allowed=False,
            credential_mode="anonymous",
        )
