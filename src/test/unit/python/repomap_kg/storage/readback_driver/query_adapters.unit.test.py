from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.storage.readback_driver import (
    PG_CONNECTOR_ENV,
    READBACK_DRIVER_ENV,
    execute_json_readback_with_driver,
)
from repomap_kg.storage.canonical import (
    query_canonical_edge_explanation,
    query_canonical_edge_records,
    query_canonical_node_records,
    query_canonical_storage_summary,
)
from repomap_kg.storage.sql import (
    build_canonical_edge_query_sql,
    build_canonical_node_query_sql,
    build_canonical_storage_summary_query_sql,
    build_explain_canonical_edge_query_sql,
)


def _completed(stdout: str) -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout)


def test_psql_readback_uses_private_child_password_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import repomap_kg.storage.readback_driver as readback_driver

    captured: dict[str, object] = {}

    def fake_run_psql(command, *, input_text, env):
        captured.update(command=command, input_text=input_text, env=env)
        return _completed('{"ok": true}\n')

    monkeypatch.setenv("PGPASSWORD", "ambient-admin")
    monkeypatch.setenv("REPOMAP_PG_PASSWORD", "ambient-admin")
    monkeypatch.setattr(readback_driver, "run_psql", fake_run_psql)

    payload = execute_json_readback_with_driver(
        "SELECT 1",
        driver="psql",
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "reader", "-d", "graph"],
        psql_command="psql",
        label="synthetic readback",
        expected_shape="object",
        password="read-status-secret",
    )

    child_env = captured["env"]
    assert payload == {"ok": True}
    assert isinstance(child_env, dict)
    assert child_env["PGPASSWORD"] == "read-status-secret"
    assert "REPOMAP_PG_PASSWORD" not in child_env
    assert os.environ["PGPASSWORD"] == "ambient-admin"


def test_psycopg_readback_passes_password_only_to_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg

    fake = _FakePsycopg(row=('{"ok": true}',))
    monkeypatch.setattr(psycopg, "connect", fake.connect)

    payload = execute_json_readback_with_driver(
        "SELECT 1",
        driver="psycopg",
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "reader", "-d", "graph"],
        psql_command="psql",
        label="synthetic readback",
        expected_shape="object",
        password="read-status-secret",
    )

    assert payload == {"ok": True}
    assert fake.connect_calls == [
        {
            "host": "127.0.0.1",
            "port": "5432",
            "user": "reader",
            "dbname": "graph",
            "password": "read-status-secret",
        }
    ]


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


def test_psycopg3_query_canonical_storage_summary_uses_readback_driver_without_changing_record() -> None:
    payload = {
        "root_path": "/tmp/fixture",
        "repository_name": "fixture",
        "latest_run_id": 2,
        "runs": 3,
        "files": 5,
        "raw_observations": 17,
        "raw_observations_total": 19,
        "latest_run_raw_observations": 23,
        "canonical_nodes": 29,
        "canonical_edges": 31,
        "canonical_evidence": 37,
    }

    with patch("repomap_kg.storage.canonical.execute_json_readback") as execute:
        execute.return_value = payload

        summary = query_canonical_storage_summary(
            ["-d", "postgres"],
            root_path="/tmp/fixture",
            psql_command="/bin/psql",
        )

    assert summary.root_path == "/tmp/fixture"
    assert summary.repository_name == "fixture"
    assert summary.runs == 3
    assert summary.files == 5
    assert summary.latest_run_id == 2
    assert summary.raw_observations == 17
    assert summary.raw_observations_total == 19
    assert summary.latest_run_raw_observations == 23
    assert summary.canonical_nodes == 29
    assert summary.canonical_edges == 31
    assert summary.canonical_evidence == 37
    execute.assert_called_once_with(
        build_canonical_storage_summary_query_sql("/tmp/fixture"),
        psql_args=["-d", "postgres"],
        psql_command="/bin/psql",
        label="canonical storage summary",
        expected_shape="object",
    )
def test_psycopg11_query_canonical_node_records_uses_readback_driver_without_changing_record() -> None:
    payload = [
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
    ]

    with patch("repomap_kg.storage.canonical.execute_json_readback") as execute:
        execute.return_value = payload

        records = query_canonical_node_records(
            ["-d", "postgres"],
            root_path="/tmp/fixture",
            kind="file",
            canonical_key="file:bin/tool",
            path_prefix="bin/",
            graph_key_version=1,
            psql_command="/bin/psql",
        )

    assert len(records) == 1
    assert records[0].canonical_key == "file:bin/tool"
    assert records[0].graph_key_version == 1
    assert records[0].kind == "file"
    assert records[0].display_name == "bin/tool"
    assert records[0].metadata == {"role": "entrypoint"}
    execute.assert_called_once_with(
        build_canonical_node_query_sql(
            "/tmp/fixture",
            kind="file",
            canonical_key="file:bin/tool",
            path_prefix="bin/",
            graph_key_version=1,
        ),
        psql_args=["-d", "postgres"],
        psql_command="/bin/psql",
        label="canonical node records",
        expected_shape="array",
    )
def test_psycopg13_query_canonical_edge_records_uses_readback_driver_without_changing_record() -> None:
    payload = [
        {
            "source_key": "file:bin/tool",
            "edge_kind": "executes",
            "target_key": "tool:nix",
            "graph_key_version": 1,
            "identity_metadata": {"argv": ["nix", "build"]},
            "identity_metadata_hash": "a" * 64,
            "metadata": {"line": 7},
            "confidence": "extracted",
            "conflict": False,
            "first_seen_run_id": 10,
            "last_seen_run_id": 12,
        }
    ]

    with patch("repomap_kg.storage.canonical.execute_json_readback") as execute:
        execute.return_value = payload

        records = query_canonical_edge_records(
            ["-d", "postgres"],
            root_path="/tmp/fixture",
            kind="executes",
            source_key="file:bin/tool",
            target_key="tool:nix",
            graph_key_version=1,
            psql_command="/bin/psql",
        )

    assert len(records) == 1
    assert records[0].source_key == "file:bin/tool"
    assert records[0].edge_kind == "executes"
    assert records[0].target_key == "tool:nix"
    assert records[0].graph_key_version == 1
    assert records[0].identity_metadata == {"argv": ["nix", "build"]}
    assert records[0].identity_metadata_hash == "a" * 64
    assert records[0].metadata == {"line": 7}
    assert records[0].confidence == "extracted"
    assert records[0].conflict is False
    assert records[0].first_seen_run_id == 10
    assert records[0].last_seen_run_id == 12
    execute.assert_called_once_with(
        build_canonical_edge_query_sql(
            "/tmp/fixture",
            kind="executes",
            source_key="file:bin/tool",
            target_key="tool:nix",
            graph_key_version=1,
        ),
        psql_args=["-d", "postgres"],
        psql_command="/bin/psql",
        label="canonical edge records",
        expected_shape="array",
    )
def test_psycopg15_query_canonical_edge_explanation_uses_readback_driver_without_changing_record() -> None:
    identity_hash = "b" * 64
    payload = {
        "edge": {
            "source_key": "file:bin/tool",
            "edge_kind": "executes",
            "target_key": "tool:nix",
            "graph_key_version": 1,
            "identity_metadata": {"argv": ["nix", "build"]},
            "identity_metadata_hash": identity_hash,
            "metadata": {"line": 7},
            "confidence": "extracted",
            "conflict": False,
            "first_seen_run_id": 10,
            "last_seen_run_id": 12,
        },
        "evidence": [
            {
                "evidence_key": "evidence:bin/tool:1",
                "link_kind": "supports",
                "raw_observation": {
                    "run_id": 10,
                    "ordinal": 0,
                    "payload_hash": "c" * 64,
                    "kind": "shell.command",
                    "source_id": "bin/tool#call:nix",
                },
                "path": "bin/tool",
                "start_line": 1,
                "end_line": 1,
                "extractor": "repo-shell",
                "extractor_version": "0.1.0",
                "confidence": "extracted",
                "metadata": {"argv": ["nix", "build"]},
            }
        ],
    }

    with patch("repomap_kg.storage.canonical.execute_json_readback") as execute:
        execute.return_value = payload

        record = query_canonical_edge_explanation(
            ["-d", "postgres"],
            root_path="/tmp/fixture",
            source_key="file:bin/tool",
            kind="executes",
            target_key="tool:nix",
            identity_metadata_hash=identity_hash,
            graph_key_version=1,
            psql_command="/bin/psql",
        )

    assert record.edge is not None
    assert record.edge.source_key == "file:bin/tool"
    assert record.edge.edge_kind == "executes"
    assert record.edge.target_key == "tool:nix"
    assert record.edge.identity_metadata_hash == identity_hash
    assert record.edge.identity_metadata == {"argv": ["nix", "build"]}
    assert len(record.evidence) == 1
    assert record.evidence[0].evidence_key == "evidence:bin/tool:1"
    assert record.evidence[0].raw_observation["run_id"] == 10
    assert record.evidence[0].raw_observation["ordinal"] == 0
    assert record.evidence[0].metadata == {"argv": ["nix", "build"]}
    execute.assert_called_once_with(
        build_explain_canonical_edge_query_sql(
            "/tmp/fixture",
            source_key="file:bin/tool",
            kind="executes",
            target_key="tool:nix",
            identity_metadata_hash=identity_hash,
            graph_key_version=1,
        ),
        psql_args=["-d", "postgres"],
        psql_command="/bin/psql",
        label="canonical edge explanation",
        expected_shape="object",
    )
