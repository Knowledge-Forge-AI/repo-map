from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.readback_driver import (
    PG_CONNECTOR_ENV,
    READBACK_DRIVER_ENV,
)
from repomap_kg.storage.canonical import (
    query_canonical_edge_explanation,
    query_canonical_neighborhood,
)
from repomap_kg.storage.sql import (
    build_canonical_neighborhood_query_sql,
    build_explain_canonical_edge_query_sql,
)


def _completed(stdout: str) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout)


@pytest.fixture(autouse=True)
def _clear_connector_selector_env(monkeypatch):
    monkeypatch.delenv(PG_CONNECTOR_ENV, raising=False)
    monkeypatch.delenv(READBACK_DRIVER_ENV, raising=False)


class _FakeCursor:
    def __init__(self, row=None, execute_error: Exception | None = None):
        self.row = row
        self.execute_error = execute_error
        self.executed_sql: str | None = None

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def execute(self, sql: str):
        self.executed_sql = sql
        if self.execute_error is not None:
            raise self.execute_error

    def fetchone(self):
        return self.row


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def cursor(self):
        return self._cursor


class _FakePsycopg:
    def __init__(self, row=None, execute_error: Exception | None = None):
        self.cursor = _FakeCursor(row=row, execute_error=execute_error)
        self.connect_calls: list[dict[str, str]] = []

    def connect(self, **kwargs):
        self.connect_calls.append(dict(kwargs))
        return _FakeConnection(self.cursor)


class _RecordingConnector:
    def __init__(self, name: str):
        self.name = name
        self.capabilities = frozenset({"json_readback"})
        self.calls: list[dict[str, object]] = []

    def execute_json(
        self,
        sql: str,
        *,
        psql_args,
        psql_command: str,
        label: str,
        expected_shape: str,
    ):
        self.calls.append(
            {
                "sql": sql,
                "psql_args": tuple(psql_args),
                "psql_command": psql_command,
                "label": label,
                "expected_shape": expected_shape,
            }
        )
        return {"connector": self.name}


def test_psycopg15_query_canonical_edge_explanation_preserves_missing_edge_object() -> None:
    with patch("repomap_kg.storage.canonical.execute_json_readback") as execute:
        execute.return_value = {"edge": None, "evidence": []}

        record = query_canonical_edge_explanation(
            ["-d", "postgres"],
            root_path="/tmp/fixture",
            source_key="file:bin/tool",
            kind="executes",
            target_key="tool:missing",
            identity_metadata_hash="d" * 64,
            graph_key_version=1,
            psql_command="/bin/psql",
        )

    assert record.edge is None
    assert record.evidence == ()
    execute.assert_called_once_with(
        build_explain_canonical_edge_query_sql(
            "/tmp/fixture",
            source_key="file:bin/tool",
            kind="executes",
            target_key="tool:missing",
            identity_metadata_hash="d" * 64,
            graph_key_version=1,
        ),
        psql_args=["-d", "postgres"],
        psql_command="/bin/psql",
        label="canonical edge explanation",
        expected_shape="object",
    )

def test_psycopg28_query_canonical_neighborhood_uses_readback_driver_without_changing_record() -> None:
    payload = {
        "center": {
            "canonical_key": "tool:nix",
            "graph_key_version": 1,
            "kind": "tool",
            "display_name": "nix",
            "confidence": "extracted",
            "conflict": False,
            "metadata": {"tool": "nix"},
            "first_seen_run_id": 10,
            "last_seen_run_id": 12,
        },
        "nodes": [
            {
                "canonical_key": "file:bin/tool",
                "graph_key_version": 1,
                "kind": "file",
                "display_name": "bin/tool",
                "confidence": "extracted",
                "conflict": False,
                "metadata": {"role": "entrypoint"},
                "first_seen_run_id": 10,
                "last_seen_run_id": 12,
            }
        ],
        "edges": [
            {
                "source_key": "file:bin/tool",
                "edge_kind": "executes",
                "target_key": "tool:nix",
                "graph_key_version": 1,
                "identity_metadata": {"argv": ["nix", "build"]},
                "identity_metadata_hash": "e" * 64,
                "metadata": {"line": 7},
                "confidence": "extracted",
                "conflict": False,
                "first_seen_run_id": 10,
                "last_seen_run_id": 12,
            }
        ],
    }

    with patch("repomap_kg.storage.canonical.execute_json_readback") as execute:
        execute.return_value = payload

        record = query_canonical_neighborhood(
            ["-d", "postgres"],
            root_path="/tmp/fixture",
            node="tool:nix",
            direction="in",
            depth=1,
            graph_key_version=1,
            psql_command="/bin/psql",
        )

    assert record.to_dict() == payload
    assert record.center is not None
    assert record.center.canonical_key == "tool:nix"
    assert [node.canonical_key for node in record.nodes] == ["file:bin/tool"]
    assert [edge.target_key for edge in record.edges] == ["tool:nix"]
    execute.assert_called_once_with(
        build_canonical_neighborhood_query_sql(
            "/tmp/fixture",
            node="tool:nix",
            direction="in",
            graph_key_version=1,
        ),
        psql_args=["-d", "postgres"],
        psql_command="/bin/psql",
        label="canonical neighborhood",
        expected_shape="object",
    )

def test_psycopg28_query_canonical_neighborhood_preserves_validation() -> None:
    with patch("repomap_kg.storage.canonical.execute_json_readback") as execute:
        with pytest.raises(
            StorageSchemaError,
            match="storage neighborhood only supports depth 1",
        ):
            query_canonical_neighborhood(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                node="tool:nix",
                depth=2,
                psql_command="/bin/psql",
            )

        with pytest.raises(
            StorageSchemaError,
            match="neighborhood direction must be one of both, in, out",
        ):
            query_canonical_neighborhood(
                ["-d", "postgres"],
                root_path="/tmp/fixture",
                node="tool:nix",
                direction="sideways",
                depth=1,
                psql_command="/bin/psql",
            )

    execute.assert_not_called()
