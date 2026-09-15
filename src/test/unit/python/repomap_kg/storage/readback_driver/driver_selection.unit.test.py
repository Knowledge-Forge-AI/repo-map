from __future__ import annotations

import builtins
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


def test_psycopg2_readback_driver_uses_existing_psql_path_without_psycopg_import(
    monkeypatch,
) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psql")
    sql = "SELECT json_build_object('ok', true);"
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("psycopg"):
            raise AssertionError(f"unexpected psycopg import: {name}")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=guarded_import):
        with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
            run_psql.return_value = _completed('{"ok": true}\n')

            payload = execute_json_readback(
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
def test_psycopg24_unset_driver_uses_psycopg_connector(monkeypatch) -> None:
    monkeypatch.delenv(READBACK_DRIVER_ENV, raising=False)
    fake_psycopg = _FakePsycopg(row=({"ok": True},))

    with patch(
        "repomap_kg.storage.readback_driver._import_psycopg",
        return_value=fake_psycopg,
    ):
        with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
            run_psql.side_effect = AssertionError("unexpected psql connector")
            payload = execute_json_readback(
                "SELECT json_build_object('ok', true);",
                psql_args=("-d", "postgres"),
                label="storage summary",
                expected_shape="object",
            )

    assert payload == {"ok": True}
    assert fake_psycopg.connect_calls == [{"dbname": "postgres"}]
    assert fake_psycopg.cursor.executed_sql == "SELECT json_build_object('ok', true);"
    run_psql.assert_not_called()
def test_psycopg7_psql_driver_uses_psql_without_psycopg_import(monkeypatch) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psql")
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
def test_psycopg7_unsupported_driver_value_is_sanitized(monkeypatch) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "postgres://private-user@private-host/db")

    with pytest.raises(StorageSchemaError, match="unsupported storage readback driver"):
        execute_json_readback(
            "SELECT summary;",
            psql_args=("-d", "private-db"),
            label="storage summary",
            expected_shape="object",
        )
def test_psycopg7_explicit_psycopg_uses_psycopg_path(monkeypatch) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psycopg")
    fake_psycopg = _FakePsycopg(row=({"ok": True},))

    with patch(
        "repomap_kg.storage.readback_driver._import_psycopg",
        return_value=fake_psycopg,
    ):
        with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
            payload = execute_json_readback(
                "SELECT json_build_object('ok', true);",
                psql_args=("-h", "localhost", "-p", "5432", "-U", "tester", "-d", "db"),
                label="storage summary",
                expected_shape="object",
            )

    assert payload == {"ok": True}
    assert fake_psycopg.connect_calls == [
        {"host": "localhost", "port": "5432", "user": "tester", "dbname": "db"}
    ]
    assert fake_psycopg.cursor.executed_sql == "SELECT json_build_object('ok', true);"
    run_psql.assert_not_called()
def test_psycopg7_explicit_psycopg_unavailable_is_sanitized(monkeypatch) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psycopg")

    with patch(
        "repomap_kg.storage.readback_driver._import_psycopg",
        side_effect=StorageSchemaError("Psycopg readback driver is unavailable"),
    ):
        with pytest.raises(StorageSchemaError, match="Psycopg readback driver"):
            execute_json_readback(
                "SELECT summary;",
                psql_args=("-d", "private-db"),
                label="storage summary",
                expected_shape="object",
            )
def test_psycopg7_explicit_psycopg_unsupported_psql_args_are_sanitized(
    monkeypatch,
) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psycopg")

    with patch(
        "repomap_kg.storage.readback_driver._import_psycopg",
        return_value=_FakePsycopg(row=({"ok": True},)),
    ):
        with pytest.raises(StorageSchemaError) as error:
            execute_json_readback(
                "SELECT summary;",
                psql_args=("--password=private-secret", "-d", "private-db"),
                label="storage summary",
                expected_shape="object",
            )

    message = str(error.value)
    assert "unsupported psql connection argument" in message
    assert "private-secret" not in message
    assert "private-db" not in message
def test_psycopg7_no_fallback_after_psycopg_execution_failure(monkeypatch) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psycopg")
    fake_psycopg = _FakePsycopg(execute_error=RuntimeError("private-db failed"))

    with patch(
        "repomap_kg.storage.readback_driver._import_psycopg",
        return_value=fake_psycopg,
    ):
        with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
            with pytest.raises(StorageSchemaError) as error:
                execute_json_readback(
                    "SELECT summary;",
                    psql_args=("-d", "private-db"),
                    label="storage summary",
                    expected_shape="object",
                )

    assert "psycopg readback failed for storage summary" in str(error.value)
    assert "private-db" not in str(error.value)
    run_psql.assert_not_called()
def test_psycopg7_no_fallback_after_psycopg_shape_mismatch(monkeypatch) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psycopg")
    fake_psycopg = _FakePsycopg(row=([],))

    with patch(
        "repomap_kg.storage.readback_driver._import_psycopg",
        return_value=fake_psycopg,
    ):
        with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
            with pytest.raises(StorageSchemaError, match="JSON object"):
                execute_json_readback(
                    "SELECT summary;",
                    psql_args=("-d", "postgres"),
                    label="storage summary",
                    expected_shape="object",
                )

    run_psql.assert_not_called()
def test_psycopg7_no_fallback_after_psycopg_malformed_json(monkeypatch) -> None:
    monkeypatch.setenv(READBACK_DRIVER_ENV, "psycopg")
    fake_psycopg = _FakePsycopg(row=("not-json-for-private-db",))

    with patch(
        "repomap_kg.storage.readback_driver._import_psycopg",
        return_value=fake_psycopg,
    ):
        with patch("repomap_kg.storage.readback_driver.run_psql") as run_psql:
            with pytest.raises(StorageSchemaError) as error:
                execute_json_readback(
                    "SELECT summary;",
                    psql_args=("-d", "private-db"),
                    label="storage summary",
                    expected_shape="object",
                )

    message = str(error.value)
    assert "psycopg did not return storage summary as JSON" in message
    assert "private-db" not in message
    run_psql.assert_not_called()
