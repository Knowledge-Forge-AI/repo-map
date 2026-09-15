from __future__ import annotations

import builtins
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import repomap_kg.storage.readback_driver as readback_driver
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


def test_psycopg17_connector_registry_contains_official_connectors() -> None:
    assert set(readback_driver.CONNECTORS) == {"psql", "psycopg"}
    assert isinstance(
        readback_driver.CONNECTORS["psql"],
        readback_driver.PsqlJsonReadbackConnector,
    )
    assert isinstance(
        readback_driver.CONNECTORS["psycopg"],
        readback_driver.PsycopgJsonReadbackConnector,
    )
def test_psycopg17_official_connectors_advertise_json_readback() -> None:
    assert readback_driver.JSON_READBACK_CAPABILITY == "json_readback"
    for connector in readback_driver.CONNECTORS.values():
        assert connector.capabilities == frozenset({"json_readback"})
def test_psycopg26_pg_connector_env_constant_is_additive() -> None:
    assert PG_CONNECTOR_ENV == "REPOMAP_STORAGE_PG_CONNECTOR"
    assert READBACK_DRIVER_ENV == "REPOMAP_STORAGE_READBACK_DRIVER"


@pytest.mark.parametrize(
    ("pg_connector", "readback_driver_value", "expected_connector"),
    (
        (None, None, "psycopg"),
        ("psycopg", None, "psycopg"),
        ("psql", None, "psql"),
        (None, "psycopg", "psycopg"),
        (None, "psql", "psql"),
        ("psycopg", "psycopg", "psycopg"),
        ("psql", "psql", "psql"),
    ),
)
def test_psycopg26_connector_selector_precedence(
    monkeypatch,
    pg_connector: str | None,
    readback_driver_value: str | None,
    expected_connector: str,
) -> None:
    if pg_connector is not None:
        monkeypatch.setenv(PG_CONNECTOR_ENV, pg_connector)
    if readback_driver_value is not None:
        monkeypatch.setenv(READBACK_DRIVER_ENV, readback_driver_value)
    psql_connector = _RecordingConnector("psql")
    psycopg_connector = _RecordingConnector("psycopg")
    monkeypatch.setattr(
        readback_driver,
        "CONNECTORS",
        {"psql": psql_connector, "psycopg": psycopg_connector},
    )

    payload = execute_json_readback(
        "SELECT json_build_object('ok', true);",
        psql_args=("-d", "postgres"),
        psql_command="/bin/psql",
        label="storage summary",
        expected_shape="object",
    )

    assert payload == {"connector": expected_connector}
    selected_connector = (
        psql_connector if expected_connector == "psql" else psycopg_connector
    )
    other_connector = (
        psycopg_connector if expected_connector == "psql" else psql_connector
    )
    assert selected_connector.calls == [
        {
            "sql": "SELECT json_build_object('ok', true);",
            "psql_args": ("-d", "postgres"),
            "psql_command": "/bin/psql",
            "label": "storage summary",
            "expected_shape": "object",
        }
    ]
    assert other_connector.calls == []
def test_psycopg26_conflicting_connector_selectors_are_sanitized(monkeypatch) -> None:
    monkeypatch.setenv(PG_CONNECTOR_ENV, "psql")
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psycopg")

    with pytest.raises(StorageSchemaError) as error:
        execute_json_readback(
            "SELECT summary;",
            psql_args=("-d", "private-db"),
            label="storage summary",
            expected_shape="object",
        )

    message = str(error.value)
    assert "conflicting PostgreSQL connector selectors" in message
    assert PG_CONNECTOR_ENV in message
    assert READBACK_DRIVER_ENV in message
    assert "psql" not in message
    assert "psycopg" not in message
    assert "private-db" not in message
def test_psycopg26_pg_connector_unsupported_value_is_sanitized(monkeypatch) -> None:
    monkeypatch.setenv(PG_CONNECTOR_ENV, "postgres://private-user@private-host/db")

    with pytest.raises(StorageSchemaError) as error:
        execute_json_readback(
            "SELECT summary;",
            psql_args=("-d", "private-db"),
            label="storage summary",
            expected_shape="object",
        )

    message = str(error.value)
    assert "unsupported storage readback driver" in message
    assert "private-user" not in message
    assert "private-host" not in message
    assert "private-db" not in message
def test_psycopg26_pg_connector_psql_attempts_no_psycopg_import(monkeypatch) -> None:
    monkeypatch.setenv(PG_CONNECTOR_ENV, "psql")
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("psycopg"):
            raise AssertionError(f"unexpected psycopg import: {name}")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=guarded_import):
        with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
            run_psql.return_value = _completed('{"ok": true}\n')

            payload = execute_json_readback(
                "SELECT json_build_object('ok', true);",
                psql_args=("-d", "postgres"),
                label="storage summary",
                expected_shape="object",
            )

    assert payload == {"ok": True}
    assert run_psql.call_count == 1


@pytest.mark.parametrize(
    ("env_value", "expected_connector"),
    (
        (None, "psycopg"),
        ("psql", "psql"),
        ("psycopg", "psycopg"),
    ),
)
def test_psycopg17_execute_json_readback_delegates_to_selected_connector(
    monkeypatch,
    env_value,
    expected_connector: str,
) -> None:
    if env_value is None:
        monkeypatch.delenv(READBACK_DRIVER_ENV, raising=False)
    else:
        monkeypatch.setenv(READBACK_DRIVER_ENV, env_value)
    psql_connector = _RecordingConnector("psql")
    psycopg_connector = _RecordingConnector("psycopg")
    monkeypatch.setattr(
        readback_driver,
        "CONNECTORS",
        {"psql": psql_connector, "psycopg": psycopg_connector},
    )

    payload = execute_json_readback(
        "SELECT json_build_object('ok', true);",
        psql_args=("-d", "postgres"),
        psql_command="/bin/psql",
        label="storage summary",
        expected_shape="object",
    )

    assert payload == {"connector": expected_connector}
    selected_connector = (
        psql_connector if expected_connector == "psql" else psycopg_connector
    )
    other_connector = (
        psycopg_connector if expected_connector == "psql" else psql_connector
    )
    assert selected_connector.calls == [
        {
            "sql": "SELECT json_build_object('ok', true);",
            "psql_args": ("-d", "postgres"),
            "psql_command": "/bin/psql",
            "label": "storage summary",
            "expected_shape": "object",
        }
    ]
    assert other_connector.calls == []
def test_psycopg17_psql_connector_preserves_psql_process_path() -> None:
    connector = readback_driver.PsqlJsonReadbackConnector()
    sql = "SELECT json_build_object('ok', true);"

    with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
        run_psql.return_value = _completed('{"ok": true}\n')

        payload = connector.execute_json(
            sql,
            psql_args=("--dbname", "postgres"),
            psql_command="/bin/psql",
            label="storage summary",
            expected_shape="object",
        )

    assert payload == {"ok": True}
    run_psql.assert_called_once_with(
        [
            "/bin/psql",
            "--dbname",
            "postgres",
            "-qAt",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        input_text=sql,
    )
def test_psycopg17_psycopg_connector_preserves_psycopg_path() -> None:
    connector = readback_driver.PsycopgJsonReadbackConnector()
    fake_psycopg = _FakePsycopg(row=({"ok": True},))

    with patch(
        "repomap_kg.storage.readback_driver._import_psycopg",
        return_value=fake_psycopg,
    ):
        with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
            payload = connector.execute_json(
                "SELECT json_build_object('ok', true);",
                psql_args=(
                    "-h",
                    "localhost",
                    "-p",
                    "5432",
                    "-U",
                    "tester",
                    "-d",
                    "db",
                ),
                psql_command="/bin/psql",
                label="storage summary",
                expected_shape="object",
            )

    assert payload == {"ok": True}
    assert fake_psycopg.connect_calls == [
        {"host": "localhost", "port": "5432", "user": "tester", "dbname": "db"}
    ]
    assert fake_psycopg.cursor.executed_sql == "SELECT json_build_object('ok', true);"
    run_psql.assert_not_called()
