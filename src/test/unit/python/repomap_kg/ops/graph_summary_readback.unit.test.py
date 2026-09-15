from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

import repomap_kg.ops.refresh as refresh
from repomap_kg.ops.config import load_ops_config
from repomap_kg.ops.refresh import (
    MISSING_DATABASE_DIAGNOSTIC_CODE,
    OpsRefreshError,
    build_graph_summary_sql,
    build_postgres_status_sql,
    graph_summary_to_jsonable,
    query_drift_check,
    query_graph_summary,
)
from repomap_kg.ops.readback import MissingDatabaseReadbackError
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
id = "private"
name = "Private"
root_path = "/private/repository"
repository_name = "private-repository"
database = "private_database"
privacy = "private-ops"
enabled = true
mcp_visible = false
extractor_profile = "private-ops"
refresh_policy = "manual"
[[graphs]]
id = "disabled"
name = "Disabled"
root_path = "/public/disabled"
repository_name = "disabled-repository"
database = "disabled_database"
privacy = "public-dev"
enabled = false
mcp_visible = false
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


def _summary_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "repository_exists": True,
        "latest_run_id": 7,
        "latest_run_status": "complete",
        "latest_run_started_at": "2026-07-12T00:00:00Z",
        "latest_run_finished_at": "2026-07-12T00:01:00Z",
        "files": "3",
        "raw_observations": 5,
        "latest_run_raw_observations": True,
        "canonical_nodes": -2,
        "canonical_edges": 4,
        "language_counts": {"python": 2, "bad": True, 9: 1},
        "observation_kind_counts": {"symbol": 3, "file": 2},
        "latest_run_observation_kind_counts": {"symbol": 1},
        "canonical_node_kind_counts": {"symbol": 2},
        "canonical_edge_kind_counts": {"defines": 4},
    }
    payload.update(overrides)
    return payload


def test_psycopg104_exact_two_stage_adapter_wiring_and_private_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    calls: list[dict[str, Any]] = []

    def readback(config_arg, **kwargs):
        calls.append({"config": config_arg, **kwargs})
        if kwargs["label"] == "operations graph summary postgres status":
            return {"connected": True, "schema_available": True}
        return _summary_payload(raw_observations_total=6)

    monkeypatch.setattr(refresh, "execute_ops_json_readback", readback)
    monkeypatch.setattr(
        refresh,
        "_run_ops_psql",
        lambda *args, **kwargs: pytest.fail("legacy graph-summary transport used"),
    )
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, *args, **kwargs: pytest.fail("graph root was read"),
    )
    monkeypatch.setattr(
        Path,
        "iterdir",
        lambda self: pytest.fail("graph root was enumerated"),
    )

    summary = query_graph_summary(
        config,
        "private",
        psql_command="/opt/public-psql-wrapper",
    )
    payload = graph_summary_to_jsonable(config, summary)

    assert calls == [
        {
            "config": config,
            "database": "private_database",
            "sql": build_postgres_status_sql(),
            "label": "operations graph summary postgres status",
            "expected_shape": "object",
            "mode": "host_then_container",
            "psql_command": "/opt/public-psql-wrapper",
        },
        {
            "config": config,
            "database": "private_database",
            "sql": build_graph_summary_sql("private-repository"),
            "label": "operations graph summary",
            "expected_shape": "object",
            "mode": "host_then_container",
            "psql_command": "/opt/public-psql-wrapper",
        },
    ]
    assert summary.result == "success"
    assert summary.latest_run_id == 7
    assert "run_authority" not in payload["graph"]
    assert summary.files == 3
    assert summary.raw_observations_total == 6
    assert summary.latest_run_raw_observations == 1
    assert summary.canonical_nodes == -2
    assert summary.language_counts == {"python": 2}
    assert list(summary.observation_kind_counts or {}) == ["file", "symbol"]
    assert payload["graph"]["root_path_display"] == "[private-root]"
    assert payload["graph"]["root_path_expanded"] == "[private-root]"
    assert payload["safety"]["graph_root_read"] is False
    assert payload["safety"]["storage_written"] is False
    assert payload["graph"]["warnings"][0]["code"] == "private-graph-readback"


@pytest.mark.parametrize(
    ("first_payload", "error_code", "expected_calls"),
    (
        (StorageSchemaError("readiness unavailable"), "storage-status-unavailable", 1),
        ({"connected": True, "schema_available": False}, "storage-schema-unavailable", 1),
        (None, "graph-summary-failed", 2),
    ),
)
def test_psycopg104_stage_failures_fold_and_short_circuit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    first_payload: object,
    error_code: str,
    expected_calls: int,
) -> None:
    config = _config(tmp_path)
    calls: list[str] = []

    def readback(config_arg, **kwargs):
        calls.append(kwargs["label"])
        if first_payload is None:
            if len(calls) == 1:
                return {"connected": True, "schema_available": True}
            raise StorageSchemaError("summary unavailable")
        if isinstance(first_payload, Exception):
            raise first_payload
        return first_payload

    monkeypatch.setattr(refresh, "execute_ops_json_readback", readback)
    monkeypatch.setattr(
        refresh,
        "_run_ops_psql",
        lambda *args, **kwargs: pytest.fail("legacy graph-summary transport used"),
    )

    summary = query_graph_summary(config, "public")

    assert summary.result == "failure"
    assert summary.db_checked is True
    assert summary.repository_exists is False
    assert summary.diagnostics[0]["code"] == error_code
    assert len(calls) == expected_calls


def test_missing_database_has_a_distinct_public_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(
        refresh,
        "execute_ops_json_readback",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MissingDatabaseReadbackError("public missing database diagnostic")
        ),
    )

    summary = query_graph_summary(config, "public")

    assert summary.result == "failure"
    assert summary.diagnostics[0]["code"] == MISSING_DATABASE_DIAGNOSTIC_CODE
    assert summary.diagnostics[0]["message"] == "public missing database diagnostic"


def test_psycopg104_repository_missing_and_conversion_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    results = iter(
        (
            {"connected": "yes", "schema_available": 1},
            {"repository_exists": False},
        )
    )
    monkeypatch.setattr(
        refresh,
        "execute_ops_json_readback",
        lambda *args, **kwargs: next(results),
    )

    summary = query_graph_summary(config, "public")

    assert summary.result == "success"
    assert summary.repository_exists is False
    assert summary.latest_run_id is None
    assert summary.latest_run_status is None
    assert summary.files == 0
    assert summary.raw_observations == 0
    assert summary.raw_observations_total == 0
    assert summary.latest_run_raw_observations == 0
    assert summary.language_counts == {}
    assert summary.diagnostics == ()
    assert summary.error is None

    jsonable = summary.to_jsonable()
    assert tuple(summary.__dataclass_fields__) == (
        "graph_id",
        "repository_name",
        "database",
        "privacy",
        "enabled",
        "mcp_visible",
        "root_path_display",
        "root_path_expanded",
        "result",
        "db_checked",
        "repository_exists",
        "latest_run_id",
        "latest_run_status",
        "latest_run_started_at",
        "latest_run_finished_at",
        "files",
        "raw_observations",
        "raw_observations_total",
        "latest_run_raw_observations",
        "canonical_nodes",
        "canonical_edges",
        "language_counts",
        "observation_kind_counts",
        "latest_run_observation_kind_counts",
        "canonical_node_kind_counts",
        "canonical_edge_kind_counts",
        "warnings",
        "diagnostics",
        "error",
    )
    assert "latest_run_consistency" in jsonable


def test_psycopg104_malformed_scalar_remains_caller_owned(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    results = iter(
        (
            {"connected": True, "schema_available": True},
            _summary_payload(files="not-an-integer"),
        )
    )
    monkeypatch.setattr(
        refresh,
        "execute_ops_json_readback",
        lambda *args, **kwargs: next(results),
    )

    with pytest.raises(ValueError):
        query_graph_summary(config, "public")


def test_psycopg104_drift_propagates_current_summary_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    def fail_readback(*args, **kwargs):
        raise StorageSchemaError("current summary unavailable")

    monkeypatch.setattr(
        refresh,
        "execute_ops_json_readback",
        fail_readback,
    )

    result = query_drift_check(
        config,
        "public",
        baseline={"graph_id": "public"},
    )

    assert result.result == "failure"
    assert result.drift_detected is False
    assert result.current.error == "current summary unavailable"
    assert result.diagnostics[0]["code"] == "storage-status-unavailable"


@pytest.mark.parametrize("graph_id", ("missing", "disabled"))
def test_psycopg104_graph_validation_precedes_database_and_root_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    graph_id: str,
) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(
        refresh,
        "execute_ops_json_readback",
        lambda *args, **kwargs: pytest.fail("database accessed"),
    )
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda self, *args, **kwargs: pytest.fail("graph root was read"),
    )
    monkeypatch.setattr(
        Path,
        "iterdir",
        lambda self: pytest.fail("graph root was enumerated"),
    )

    with pytest.raises(OpsRefreshError):
        query_graph_summary(config, graph_id)


def test_psycopg104_moves_no_other_operational_owner() -> None:
    import repomap_kg.ops.config as config
    import repomap_kg.server.ops as server
    source = inspect.getsource(refresh.query_graph_summary)

    assert source.count("execute_ops_json_readback") == 2
    assert "_run_ops_psql" not in source
    assert "parse_psql_json" not in source
    assert "execute_ops_json_readback" in inspect.getsource(
        config.check_ops_postgres_status
    )
    assert "execute_ops_json_readback" in inspect.getsource(
        config.check_ops_graph_storage_status
    )
    search_fn = getattr(server, "_ops_search_impl", server).query_mcp_search
    search_source = inspect.getsource(search_fn)
    assert "execute_ops_json_readback" in search_source
    assert "run_psql" not in search_source
