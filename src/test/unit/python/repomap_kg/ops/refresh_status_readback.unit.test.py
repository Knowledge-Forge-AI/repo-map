from __future__ import annotations

import inspect
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import repomap_kg.ops.refresh as refresh
from repomap_kg.ops.config import load_ops_config
from repomap_kg.storage import StorageSchemaError
from repomap_test_support.ops_refresh import VALID_REFRESH_CONFIG


def _config(tmp_path: Path, *, multiple_databases: bool = False):
    root = tmp_path / "repo"
    root.mkdir()
    config_path = tmp_path / "repomap.local.toml"
    config_path.write_text(
        VALID_REFRESH_CONFIG.format(repo_root=root, private_root=root / "private"),
        encoding="utf-8",
    )
    config = load_ops_config(config_path)
    if not multiple_databases:
        return config
    second = replace(
        config.graphs[1],
        id="second",
        enabled=True,
        database="repomap_second",
    )
    return replace(config, graphs=(config.graphs[0], second))


def _ready_payload() -> dict[str, Any]:
    return {"connected": True, "schema_available": True}


def test_psycopg94_refresh_status_uses_exact_two_operational_adapter_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    def execute(config, **kwargs: Any):
        calls.append(kwargs)
        return _ready_payload() if len(calls) == 1 else {"graphs": []}

    monkeypatch.setattr(refresh, "execute_ops_json_readback", execute)

    statuses = refresh.query_refresh_status(
        _config(tmp_path),
        graph_ids=["repo-map", "repo-map"],
        psql_command="/bin/psql",
    )

    assert tuple(statuses) == ("repo-map",)
    assert len(calls) == 2
    assert calls[0] == {
        "database": "repomap_repo_map",
        "sql": refresh.build_postgres_status_sql(),
        "label": "operations postgres status",
        "expected_shape": "object",
        "mode": "host_then_container",
        "psql_command": "/bin/psql",
    }
    assert calls[1] == {
        "database": "repomap_repo_map",
        "sql": refresh.build_refresh_status_sql((("repo-map", "repo-map"),)),
        "label": "operations refresh status",
        "expected_shape": "object",
        "mode": "host_then_container",
        "psql_command": "/bin/psql",
    }


def test_psycopg94_refresh_status_readiness_short_circuits_second_stage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []
    def execute(config, **kwargs: Any):
        calls.append(kwargs)
        return {"connected": True, "schema_available": False}

    monkeypatch.setattr(refresh, "execute_ops_json_readback", execute)

    statuses = refresh.query_refresh_status(_config(tmp_path), graph_ids=["repo-map"])

    assert len(calls) == 1
    assert statuses["repo-map"].error == "storage schema is unavailable"


def test_psycopg94_refresh_status_stage_failure_folds_and_later_database_continues(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[tuple[str, str]] = []

    def execute(config, **kwargs: Any):
        events.append((kwargs["database"], kwargs["label"]))
        if kwargs["label"] == "operations postgres status":
            return _ready_payload()
        if kwargs["database"] == "repomap_repo_map":
            raise StorageSchemaError("bounded status failure")
        return {"graphs": []}

    monkeypatch.setattr(refresh, "execute_ops_json_readback", execute)

    statuses = refresh.query_refresh_status(_config(tmp_path, multiple_databases=True))

    assert events == [
        ("repomap_repo_map", "operations postgres status"),
        ("repomap_repo_map", "operations refresh status"),
        ("repomap_second", "operations postgres status"),
        ("repomap_second", "operations refresh status"),
    ]
    assert statuses["repo-map"].error == "bounded status failure"
    assert statuses["second"].error is None


def test_psycopg94_only_refresh_status_is_migrated() -> None:
    inspect.getsource(refresh)
    refresh_source = inspect.getsource(refresh.query_refresh_status)

    assert "execute_ops_json_readback" in refresh_source
    assert "_run_ops_psql" not in refresh_source
    assert "parse_psql_json" not in refresh_source
    for owner in (
        refresh._run_ops_psql,
        refresh.run_storage_readback_with_ops_psql,
    ):
        assert "execute_ops_json_readback" not in inspect.getsource(owner)
    assert inspect.getsource(refresh.query_graph_summary).count(
        "execute_ops_json_readback"
    ) == 2
