from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.readback_driver import (
    PG_CONNECTOR_ENV,
    READBACK_DRIVER_ENV,
    _psycopg_connection_params_from_psql_args,
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


def test_psycopg7_psycopg_connection_params_from_short_psql_args() -> None:
    assert _psycopg_connection_params_from_psql_args(
        ("-h", "localhost", "-p", "55433", "-U", "repo_map_test", "-d", "postgres")
    ) == {
        "host": "localhost",
        "port": "55433",
        "user": "repo_map_test",
        "dbname": "postgres",
    }

def test_psycopg7_psycopg_connection_params_from_long_psql_args() -> None:
    assert _psycopg_connection_params_from_psql_args(
        (
            "--host",
            "localhost",
            "--port",
            "55433",
            "--username",
            "repo_map_test",
            "--dbname",
            "postgres",
        )
    ) == {
        "host": "localhost",
        "port": "55433",
        "user": "repo_map_test",
        "dbname": "postgres",
    }

def test_psycopg7_psycopg_connection_params_reject_missing_values() -> None:
    with pytest.raises(StorageSchemaError, match="requires a value"):
        _psycopg_connection_params_from_psql_args(("-h", "-d", "postgres"))

def test_psycopg7_psycopg_connection_params_reject_unsupported_flags() -> None:
    with pytest.raises(StorageSchemaError) as error:
        _psycopg_connection_params_from_psql_args(
            ("--set", "private-token=secret", "-d", "private-db")
        )

    message = str(error.value)
    assert "unsupported psql connection argument" in message
    assert "private-token" not in message
    assert "secret" not in message
    assert "private-db" not in message

def test_psycopg7_psycopg_helper_returns_decoded_object(monkeypatch) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psycopg")
    fake_psycopg = _FakePsycopg(row=({"ok": True},))

    with patch(
        "repomap_kg.storage.readback_driver._import_psycopg",
        return_value=fake_psycopg,
    ):
        payload = execute_json_readback(
            "SELECT json_build_object('ok', true);",
            psql_args=("-d", "postgres"),
            label="storage summary",
            expected_shape="object",
        )

    assert payload == {"ok": True}

def test_psycopg7_psycopg_helper_returns_decoded_array(monkeypatch) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psycopg")
    fake_psycopg = _FakePsycopg(row=([{"node_key": "file:README.md"}],))

    with patch(
        "repomap_kg.storage.readback_driver._import_psycopg",
        return_value=fake_psycopg,
    ):
        payload = execute_json_readback(
            "SELECT nodes;",
            psql_args=("-d", "postgres"),
            label="canonical node records",
            expected_shape="array",
        )

    assert payload == [{"node_key": "file:README.md"}]

def test_psycopg7_psycopg_helper_handles_json_text(monkeypatch) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psycopg")
    fake_psycopg = _FakePsycopg(row=(json.dumps({"ok": True}),))

    with patch(
        "repomap_kg.storage.readback_driver._import_psycopg",
        return_value=fake_psycopg,
    ):
        payload = execute_json_readback(
            "SELECT json_build_object('ok', true);",
            psql_args=("-d", "postgres"),
            label="storage summary",
            expected_shape="object",
        )

    assert payload == {"ok": True}

def test_psycopg7_psycopg_helper_rejects_unexpected_result_shape(monkeypatch) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psycopg")
    fake_psycopg = _FakePsycopg(row=({"ok": True},))

    with patch(
        "repomap_kg.storage.readback_driver._import_psycopg",
        return_value=fake_psycopg,
    ):
        with pytest.raises(StorageSchemaError, match="JSON array"):
            execute_json_readback(
                "SELECT json_build_object('ok', true);",
                psql_args=("-d", "postgres"),
                label="canonical node records",
                expected_shape="array",
            )
