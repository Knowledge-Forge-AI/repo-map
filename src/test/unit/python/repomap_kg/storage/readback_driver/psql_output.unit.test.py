from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.readback_driver import (
    PG_CONNECTOR_ENV,
    READBACK_DRIVER_ENV,
    execute_json_readback,
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


def test_psycopg2_readback_driver_returns_last_nonblank_json_object(monkeypatch) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psql")
    with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
        run_psql.return_value = _completed('\nNOTICE: ignored\n{"files": 2}\n')

        payload = execute_json_readback(
            "SELECT summary;",
            psql_args=("-d", "postgres"),
            label="storage summary",
            expected_shape="object",
        )

    assert payload == {"files": 2}
def test_psycopg2_readback_driver_accepts_array_payloads(monkeypatch) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psql")
    with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
        run_psql.return_value = _completed('[{"node_key": "file:README.md"}]\n')

        payload = execute_json_readback(
            "SELECT nodes;",
            psql_args=("-d", "postgres"),
            label="canonical node records",
            expected_shape="array",
        )

    assert payload == [{"node_key": "file:README.md"}]
def test_psycopg2_readback_driver_rejects_empty_stdout(monkeypatch) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psql")
    with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
        run_psql.return_value = _completed("\n")

        with pytest.raises(
            StorageSchemaError,
            match="psql did not return storage summary as JSON",
        ):
            execute_json_readback(
                "SELECT summary;",
                psql_args=("-d", "postgres"),
                label="storage summary",
                expected_shape="object",
            )

    assert run_psql.call_count == 1
def test_psycopg2_readback_driver_rejects_malformed_json_without_retry(
    monkeypatch,
) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psql")
    with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
        run_psql.return_value = _completed("not-json\n")

        with pytest.raises(
            StorageSchemaError,
            match="psql did not return storage summary as JSON",
        ):
            execute_json_readback(
                "SELECT summary;",
                psql_args=("-d", "postgres"),
                label="storage summary",
                expected_shape="object",
            )

    assert run_psql.call_count == 1
def test_psycopg2_readback_driver_rejects_object_shape_mismatch_without_retry(
    monkeypatch,
) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psql")
    with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
        run_psql.return_value = _completed("[]\n")

        with pytest.raises(
            StorageSchemaError,
            match="psql did not return storage summary as a JSON object",
        ):
            execute_json_readback(
                "SELECT summary;",
                psql_args=("-d", "postgres"),
                label="storage summary",
                expected_shape="object",
            )

    assert run_psql.call_count == 1
def test_psycopg2_readback_driver_rejects_array_shape_mismatch_without_retry(
    monkeypatch,
) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psql")
    with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
        run_psql.return_value = _completed("{}\n")

        with pytest.raises(
            StorageSchemaError,
            match="psql did not return canonical node records as a JSON array",
        ):
            execute_json_readback(
                "SELECT nodes;",
                psql_args=("-d", "postgres"),
                label="canonical node records",
                expected_shape="array",
            )

    assert run_psql.call_count == 1
def test_psycopg2_readback_driver_preserves_psql_failures_as_storage_schema_error(
    monkeypatch,
) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psql")
    with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
        run_psql.side_effect = StorageSchemaError("psql failed: connection failed")

        with pytest.raises(StorageSchemaError, match="psql failed"):
            execute_json_readback(
                "SELECT summary;",
                psql_args=("-d", "postgres"),
                label="storage summary",
                expected_shape="object",
            )
