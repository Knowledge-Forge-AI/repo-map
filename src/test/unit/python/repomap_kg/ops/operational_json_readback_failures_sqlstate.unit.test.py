from __future__ import annotations

from collections.abc import Iterator, Sequence
import json
from pathlib import Path
import subprocess
from typing import TypedDict
import psycopg
import pytest
import repomap_kg.ops.readback as readback
from repomap_kg.ops.config import OpsConfig, load_ops_config_home
from repomap_kg.ops.refresh import (
    MISSING_DATABASE_DIAGNOSTIC_CODE,
    graph_summary_to_jsonable,
    query_graph_summary,
)
from repomap_kg.storage import StorageSchemaError
import repomap_kg.storage.readback_driver as storage_readback
from repomap_test_support.ops_refresh import VALID_REFRESH_CONFIG
from smoke.lifecycle import validate_target_database_absent

_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

@pytest.fixture(autouse=True)
def _clear_connector_selectors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(storage_readback.PG_CONNECTOR_ENV, raising=False)
    monkeypatch.delenv(storage_readback.READBACK_DRIVER_ENV, raising=False)

def _loopback_config(
    tmp_path: Path,
    *,
    host: str = "127.0.0.1",
    direct_host_port_enabled: bool,
) -> OpsConfig:
    home = tmp_path / "home"
    root = tmp_path / "repo"
    home.mkdir(parents=True)
    root.mkdir()
    direct_host_port = "true" if direct_host_port_enabled else "false"
    (home / "repomap.rpl.toml").write_text(
        VALID_REFRESH_CONFIG.format(repo_root=root, private_root=root / "private").replace(
            'host = "127.0.0.1"',
            f'host = "{host}"',
        )
        + "\n[runtime]\n"
        + 'container_runtime = "docker"\n'
        + "server_host_port = 55880\n"
        + "\n[runtime.postgres]\n"
        + f"direct_host_port_enabled = {direct_host_port}\n",
        encoding="utf-8",
    )
    return load_ops_config_home(home)

class OperationalError(Exception):
    __module__ = "psycopg.errors"
    sqlstate: str | None = None

class DatabaseError(Exception):
    __module__ = "psycopg.errors"
    sqlstate: str | None = None

def _psycopg_storage_error(
    sqlstate: str | None,
    *,
    operational: bool = False,
) -> StorageSchemaError:
    cause_cls = OperationalError if operational else DatabaseError
    cause = cause_cls("private dsn password=secret")
    cause.sqlstate = sqlstate
    try:
        raise cause
    except Exception as error:
        try:
            raise StorageSchemaError("psycopg readback failed for operations status") from error
        except StorageSchemaError as wrapped:
            return wrapped

class _FakeCursor:
    def __init__(self, row: tuple[bool, ...] | None = (False,)) -> None:
        self.row = row
        self.executed: list[tuple[str, tuple[str, ...] | None]] = []
        self.closed = False
    def execute(self, sql: str, params: tuple[str, ...] | None = None) -> None:
        self.executed.append((sql, params))
    def fetchone(self) -> tuple[bool, ...] | None:
        return self.row
    def close(self) -> None:
        self.closed = True
    def __enter__(self) -> _FakeCursor:
        return self
    def __exit__(self, exc_type: object = None, exc_val: object = None, exc_tb: object = None) -> None:
        self.close()

class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self.cursor_instance = cursor
        self.closed = False
        self.read_only = False
    def cursor(self) -> _FakeCursor:
        return self.cursor_instance
    def close(self) -> None:
        self.closed = True
    def __enter__(self) -> _FakeConnection:
        return self
    def __exit__(self, exc_type: object = None, exc_val: object = None, exc_tb: object = None) -> None:
        self.close()

class _ConnectAttempt(TypedDict):
    args: tuple[object, ...]
    kwargs: dict[str, object]

class _ConnectGuard:
    def __init__(self) -> None:
        self.attempts: list[_ConnectAttempt] = []
    def record(self, *args: object, **kwargs: object) -> None:
        self.attempts.append({"args": args, "kwargs": dict(kwargs)})

@pytest.fixture(autouse=True)
def guard_lower_psycopg_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[_ConnectGuard]:
    guard = _ConnectGuard()
    def forbidden_connect(*args: object, **kwargs: object) -> _FakeConnection:
        guard.record(*args, **kwargs)
        raise AssertionError(
            "guard_lower_psycopg_connect: unexpected psycopg.connect attempt in unit test; "
            "install an explicit test double if this test exercises connection"
        )
    monkeypatch.setattr(psycopg, "connect", forbidden_connect)
    yield guard
    assert not guard.attempts, (
        f"unexpected psycopg.connect attempt escaped to lower boundary: {guard.attempts}"
    )

def test_sqlstate_3d000_produces_missing_without_maintenance_query(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    maintenance_called = False
    def fake_diagnose(*, psql_args: Sequence[str], target_database: str) -> storage_readback.CatalogPresence:
        nonlocal maintenance_called
        maintenance_called = True
        return "absent"
    monkeypatch.setattr(readback, "diagnose_psycopg_database_presence", fake_diagnose)
    def execute_fail(sql: str, *, driver: storage_readback.JsonReadbackDriver, psql_args: Sequence[str], psql_command: str, label: str, expected_shape: storage_readback.ExpectedJsonShape) -> storage_readback.JsonReadbackPayload:
        raise _psycopg_storage_error("3D000")
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", execute_fail)
    with pytest.raises(readback.MissingDatabaseReadbackError):
        readback.execute_ops_json_readback(
            _loopback_config(tmp_path, direct_host_port_enabled=True),
            database="repomap_repo_map",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_only",
        )
    assert not maintenance_called

def test_sqlstate_less_target_absence_with_positive_catalog_evidence_produces_missing_and_satisfies_smoke(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config = _loopback_config(tmp_path, direct_host_port_enabled=True)
    connect_calls: list[dict[str, str]] = []
    fake_cursor = _FakeCursor(row=(False,))
    def fake_connect(*args: object, **kwargs: object) -> _FakeConnection:
        connect_calls.append({str(k): str(v) for k, v in kwargs.items()})
        if kwargs.get("dbname") == "repomap_repo_map":
            err = psycopg.OperationalError('connection failed: FATAL: database "repomap_repo_map" does not exist\n')
            assert err.sqlstate is None
            raise err
        if kwargs.get("dbname") == "postgres":
            return _FakeConnection(fake_cursor)
        raise AssertionError(f"unexpected connection dbname: {kwargs.get('dbname')}")
    monkeypatch.setattr(psycopg, "connect", fake_connect)
    summary = query_graph_summary(config, "repo-map")
    assert summary.result == "failure"
    assert summary.db_checked is True
    assert summary.repository_exists is False
    assert len(summary.diagnostics) == 1
    assert summary.diagnostics[0]["code"] == MISSING_DATABASE_DIAGNOSTIC_CODE
    assert summary.diagnostics[0]["message"] == readback.MISSING_DATABASE_MESSAGE
    payload = graph_summary_to_jsonable(config, summary)
    completed = subprocess.CompletedProcess(("python", "-m", "repomap_kg"), 1, json.dumps(payload), "")
    validated = validate_target_database_absent(completed)
    assert validated["graph"]["diagnostics"][0]["code"] == MISSING_DATABASE_DIAGNOSTIC_CODE
    assert len(connect_calls) >= 2
    maintenance_conn = [c for c in connect_calls if c.get("dbname") == "postgres"]
    assert len(maintenance_conn) == 1
    assert maintenance_conn[0]["host"] == "127.0.0.1"
    assert maintenance_conn[0]["user"] == "admin"
    assert maintenance_conn[0]["connect_timeout"] == "3"
    assert "-c default_transaction_read_only=on" in maintenance_conn[0]["options"]
    assert "-c statement_timeout=3000" in maintenance_conn[0]["options"]
    assert fake_cursor.closed is True
    assert fake_cursor.executed == [
        ("SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s)", ("repomap_repo_map",))
    ]

@pytest.mark.parametrize(
    ("diagnostic_outcome", "expected_code"),
    (
        ("present", "storage-status-unavailable"),
        ("denied", "storage-status-unavailable"),
        ("unavailable", "storage-status-unavailable"),
        ("malformed", "storage-status-unavailable"),
    ),
)
def test_sqlstate_less_connect_failure_without_positive_absence_is_not_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    diagnostic_outcome: storage_readback.CatalogPresence,
    expected_code: str,
) -> None:
    config = _loopback_config(tmp_path, direct_host_port_enabled=True)
    monkeypatch.setattr(
        readback,
        "diagnose_psycopg_database_presence",
        lambda *, psql_args, target_database: diagnostic_outcome,
    )
    def fake_connect(*args: object, **kwargs: object) -> _FakeConnection:
        err = psycopg.OperationalError('connection failed: connection refused\n')
        assert err.sqlstate is None
        raise err
    monkeypatch.setattr(psycopg, "connect", fake_connect)
    with pytest.raises(StorageSchemaError) as exc_info:
        readback.execute_ops_json_readback(
            config,
            database="repomap_repo_map",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_only",
        )
    assert not isinstance(exc_info.value, readback.MissingDatabaseReadbackError)
    summary = query_graph_summary(config, "repo-map")
    assert summary.result == "failure"
    assert summary.diagnostics[0]["code"] == expected_code
    payload = graph_summary_to_jsonable(config, summary)
    completed = subprocess.CompletedProcess(("python", "-m", "repomap_kg"), 1, json.dumps(payload), "")
    with pytest.raises(RuntimeError, match="product command did not prove typed target absence"):
        validate_target_database_absent(completed)

def test_target_auth_failure_does_not_probe_maintenance_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    maintenance_called = False
    def fake_diagnose(*, psql_args: Sequence[str], target_database: str) -> storage_readback.CatalogPresence:
        nonlocal maintenance_called
        maintenance_called = True
        return "absent"
    monkeypatch.setattr(readback, "diagnose_psycopg_database_presence", fake_diagnose)
    def execute_fail(sql: str, *, driver: storage_readback.JsonReadbackDriver, psql_args: Sequence[str], psql_command: str, label: str, expected_shape: storage_readback.ExpectedJsonShape) -> storage_readback.JsonReadbackPayload:
        raise _psycopg_storage_error("28P01")
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", execute_fail)
    with pytest.raises(StorageSchemaError) as exc_info:
        readback.execute_ops_json_readback(
            _loopback_config(tmp_path, direct_host_port_enabled=True),
            database="repomap_repo_map",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_only",
        )
    assert not isinstance(exc_info.value, readback.MissingDatabaseReadbackError)
    assert "authentication failed" in str(exc_info.value)
    assert not maintenance_called

def test_maintenance_database_failure_does_not_query_itself(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    maintenance_called = False
    def fake_diagnose(*, psql_args: Sequence[str], target_database: str) -> storage_readback.CatalogPresence:
        nonlocal maintenance_called
        maintenance_called = True
        return "absent"
    monkeypatch.setattr(readback, "diagnose_psycopg_database_presence", fake_diagnose)
    def execute_fail(sql: str, *, driver: storage_readback.JsonReadbackDriver, psql_args: Sequence[str], psql_command: str, label: str, expected_shape: storage_readback.ExpectedJsonShape) -> storage_readback.JsonReadbackPayload:
        raise _psycopg_storage_error(None, operational=True)
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", execute_fail)
    with pytest.raises(StorageSchemaError):
        readback.execute_ops_json_readback(
            _loopback_config(tmp_path, direct_host_port_enabled=True),
            database="postgres",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_only",
        )
    assert not maintenance_called

@pytest.mark.parametrize(
    ("phase", "sqlstate", "host", "expected_snippet"),
    (
        ("connect", "08006", "127.0.0.1", "connection failed"),
        ("query", None, "127.0.0.1", "connection failed"),
        ("connect", None, "host1.example,host2.example", "connection failed"),
    ),
)
def test_ineligible_readback_failures_do_not_probe_maintenance_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    phase: str,
    sqlstate: str | None,
    host: str,
    expected_snippet: str,
) -> None:
    maintenance_called = False
    def fake_diagnose(*, psql_args: Sequence[str], target_database: str) -> storage_readback.CatalogPresence:
        nonlocal maintenance_called
        maintenance_called = True
        return "absent"
    monkeypatch.setattr(readback, "diagnose_psycopg_database_presence", fake_diagnose)
    err = _psycopg_storage_error(sqlstate, operational=True)
    setattr(err, "_readback_phase", phase)
    def fail_execute(sql: str, *, driver: storage_readback.JsonReadbackDriver, psql_args: Sequence[str], psql_command: str, label: str, expected_shape: storage_readback.ExpectedJsonShape) -> storage_readback.JsonReadbackPayload:
        raise err
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", fail_execute)
    config = _loopback_config(tmp_path, host=host, direct_host_port_enabled=True)
    with pytest.raises(StorageSchemaError) as exc_info:
        readback.execute_ops_json_readback(
            config,
            database="repomap_repo_map",
            sql="SELECT 1",
            label="operations status",
            expected_shape="object",
            mode="host_only",
        )
    assert not isinstance(exc_info.value, readback.MissingDatabaseReadbackError)
    assert expected_snippet in str(exc_info.value)
    assert not maintenance_called

def test_real_connector_path_without_explicit_double_cannot_escape_lower_guard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    guard_lower_psycopg_connect: _ConnectGuard,
) -> None:
    config = _loopback_config(tmp_path, direct_host_port_enabled=True)
    err = _psycopg_storage_error(None, operational=True)
    setattr(err, "_readback_phase", "connect")
    def fail_execute(sql: str, *, driver: storage_readback.JsonReadbackDriver, psql_args: Sequence[str], psql_command: str, label: str, expected_shape: storage_readback.ExpectedJsonShape) -> storage_readback.JsonReadbackPayload:
        raise err
    monkeypatch.setattr(readback, "execute_json_readback_with_driver", fail_execute)
    summary = query_graph_summary(config, "repo-map")
    assert summary.result == "failure"
    assert summary.diagnostics[0]["code"] == "storage-status-unavailable"
    assert len(guard_lower_psycopg_connect.attempts) == 1
    attempt = guard_lower_psycopg_connect.attempts[0]["kwargs"]
    assert attempt.get("dbname") == "postgres"
    assert attempt.get("host") == "127.0.0.1"
    guard_lower_psycopg_connect.attempts.clear()
