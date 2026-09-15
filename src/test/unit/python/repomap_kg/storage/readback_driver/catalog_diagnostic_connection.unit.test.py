from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from repomap_kg.storage.readback_driver import (
    PsycopgJsonReadbackConnector,
    diagnose_psycopg_database_presence,
)


class _ConnectGuard:
    def __init__(self) -> None:
        self.attempts: list[dict[str, Any]] = []

    def record(self, *args: Any, **kwargs: Any) -> None:
        self.attempts.append({"args": args, "kwargs": kwargs})


@pytest.fixture(autouse=True)
def guard_lower_psycopg_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[_ConnectGuard]:
    import psycopg

    guard = _ConnectGuard()

    def forbidden_connect(*args: Any, **kwargs: Any) -> Any:
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


class _FakeCursor:
    def __init__(self, row: Any = (False,)) -> None:
        self.row = row
        self.executed: list[tuple[str, Any]] = []
        self.closed = False

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))

    def fetchone(self) -> Any:
        return self.row

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self.cursor_obj = cursor
        self.read_only: bool | None = None
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def test_psycopg_diagnose_connection_params_and_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg

    connector = PsycopgJsonReadbackConnector()
    captured_kwargs: dict[str, Any] = {}
    fake_cursor = _FakeCursor(row=(False,))
    fake_conn = _FakeConnection(fake_cursor)

    def recording_connect(**kwargs: Any):
        captured_kwargs.update(kwargs)
        return fake_conn

    monkeypatch.setattr(psycopg, "connect", recording_connect)
    presence = connector.diagnose_database_presence(
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
        target_database="target_db",
        timeout_seconds=2.0,
    )
    assert presence == "absent"
    assert captured_kwargs["host"] == "127.0.0.1"
    assert captured_kwargs["port"] == "5432"
    assert captured_kwargs["user"] == "admin"
    assert captured_kwargs["dbname"] == "postgres"
    assert captured_kwargs["connect_timeout"] == "2"
    assert "-c default_transaction_read_only=on" in captured_kwargs["options"]
    assert "-c statement_timeout=2000" in captured_kwargs["options"]
    assert fake_conn.read_only is True
    assert fake_cursor.closed is True
    assert fake_conn.closed is True

def test_psycopg_diagnose_elapsed_connection_budget_accounting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg

    connector = PsycopgJsonReadbackConnector()
    fake_cursor = _FakeCursor(row=(False,))
    fake_conn = _FakeConnection(fake_cursor)

    # Case A: Connection takes 2.6s of a 2.5s budget -> budget exhausted during connect
    current_time = 0.0

    def fake_clock() -> float:
        return current_time

    def slow_connect(**kwargs: Any):
        nonlocal current_time
        current_time += 2.6  # connection took 2.6s
        return fake_conn

    monkeypatch.setattr(psycopg, "connect", slow_connect)
    presence = connector.diagnose_database_presence(
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
        target_database="target_db",
        timeout_seconds=2.5,
        clock=fake_clock,
    )
    # Remaining budget is <= 0; query must NOT be executed!
    assert presence == "unavailable"
    assert len(fake_cursor.executed) == 0
    assert fake_conn.closed is True

    # Case B: Connection takes 1.0s of a 2.5s budget -> remaining 1.5s (1500ms)
    fake_cursor_b = _FakeCursor(row=(False,))
    fake_conn_b = _FakeConnection(fake_cursor_b)
    current_time_b = 0.0

    def fake_clock_b() -> float:
        return current_time_b

    def moderate_connect(**kwargs: Any):
        nonlocal current_time_b
        current_time_b += 1.0  # connection took 1.0s
        return fake_conn_b

    monkeypatch.setattr(psycopg, "connect", moderate_connect)
    presence_b = connector.diagnose_database_presence(
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
        target_database="target_db",
        timeout_seconds=2.5,
        clock=fake_clock_b,
    )
    assert presence_b == "absent"
    # Query executed with statement_timeout tightened to 1500ms
    assert len(fake_cursor_b.executed) == 2
    assert fake_cursor_b.executed[0] == ("SET statement_timeout = 1500", None)
    assert fake_cursor_b.executed[1][0].startswith("SELECT EXISTS")
    assert fake_conn_b.closed is True
    assert fake_cursor_b.closed is True

def test_psycopg_diagnose_failures_and_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg

    connector = PsycopgJsonReadbackConnector()

    # Multi-host refuses without calling connect
    assert (
        connector.diagnose_database_presence(
            psql_args=["-h", "h1,h2", "-p", "5432", "-U", "admin", "-d", "postgres"],
            target_database="target_db",
        )
        == "unavailable"
    )

    # Missing host refuses without calling connect
    assert (
        connector.diagnose_database_presence(
            psql_args=["-p", "5432", "-U", "admin", "-d", "postgres"],
            target_database="target_db",
        )
        == "unavailable"
    )

    # Auth error (OperationalError with password authentication failed) returns denied
    def auth_fail_connect(**kwargs: Any):
        raise psycopg.OperationalError("password authentication failed for user")

    monkeypatch.setattr(psycopg, "connect", auth_fail_connect)
    assert (
        connector.diagnose_database_presence(
            psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
            target_database="target_db",
        )
        == "denied"
    )

    # Server error during query returns unavailable and cleanly closes connection
    class _FailingCursor(_FakeCursor):
        def execute(self, sql: str, params: Any = None) -> None:
            raise psycopg.OperationalError("server dropped during query")

    fail_cursor = _FailingCursor(row=(False,))
    fail_conn = _FakeConnection(fail_cursor)
    monkeypatch.setattr(psycopg, "connect", lambda **kwargs: fail_conn)

    assert (
        connector.diagnose_database_presence(
            psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
            target_database="target_db",
        )
        == "unavailable"
    )
    assert fail_cursor.closed is True
    assert fail_conn.closed is True

def test_diagnose_psycopg_database_presence_top_level_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cursor = _FakeCursor(row=(True,))
    fake_conn = _FakeConnection(fake_cursor)
    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda **kwargs: fake_conn)
    presence = diagnose_psycopg_database_presence(
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
        target_database="target_db",
    )
    assert presence == "present"

@pytest.mark.parametrize(
    "options_val",
    ("-c statement_timeout=100", "-cstatement_timeout=100"),
)
def test_psycopg_diagnose_inherited_timeout_no_widening_after_connect(
    monkeypatch: pytest.MonkeyPatch,
    options_val: str,
) -> None:
    # Regression 1: Inherited 100 ms, budget 2.5 s, connection elapsed 1 s:
    # no subsequent assignment exceeds 100 ms; cover spaced and attached -c and parameterized target SQL.
    import psycopg

    connector = PsycopgJsonReadbackConnector()
    captured_kwargs: dict[str, Any] = {}
    fake_cursor = _FakeCursor(row=(False,))
    fake_conn = _FakeConnection(fake_cursor)
    current_time = 0.0

    def fake_clock() -> float:
        return current_time

    def recording_connect(**kwargs: Any):
        nonlocal current_time
        captured_kwargs.update(kwargs)
        current_time += 1.0
        return fake_conn

    monkeypatch.setattr(psycopg, "connect", recording_connect)
    monkeypatch.setenv("PGOPTIONS", options_val)

    presence = connector.diagnose_database_presence(
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
        target_database="target_db",
        timeout_seconds=2.5,
        clock=fake_clock,
    )
    assert presence == "absent"
    assert options_val in captured_kwargs["options"]
    assert "-c default_transaction_read_only=on" in captured_kwargs["options"]
    # No SET statement_timeout statement may be executed (effective cap 100ms is not widened to 1500ms)
    assert len(fake_cursor.executed) == 1
    assert fake_cursor.executed[0] == (
        "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s)",
        ("target_db",),
    )
    assert fake_cursor.closed is True
    assert fake_conn.closed is True

def test_psycopg_diagnose_inherited_timeout_tightened_after_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression 2: Inherited 2000 ms with that budget/elapsed combination:
    # reduce to 1500 ms or less; the effective cap is never increased.
    import psycopg

    connector = PsycopgJsonReadbackConnector()
    captured_kwargs: dict[str, Any] = {}
    fake_cursor = _FakeCursor(row=(False,))
    fake_conn = _FakeConnection(fake_cursor)
    current_time = 0.0

    def fake_clock() -> float:
        return current_time

    def recording_connect(**kwargs: Any):
        nonlocal current_time
        captured_kwargs.update(kwargs)
        current_time += 1.0
        return fake_conn

    monkeypatch.setattr(psycopg, "connect", recording_connect)
    monkeypatch.setenv("PGOPTIONS", "-c statement_timeout=2000")

    presence = connector.diagnose_database_presence(
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
        target_database="target_db",
        timeout_seconds=2.5,
        clock=fake_clock,
    )
    assert presence == "absent"
    assert "-c statement_timeout=2000" in captured_kwargs["options"]
    # Remaining budget is 1500 ms (< 2000 ms), tightened to 1500 ms
    assert len(fake_cursor.executed) == 2
    assert fake_cursor.executed[0] == ("SET statement_timeout = 1500", None)
    assert fake_cursor.executed[1] == (
        "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s)",
        ("target_db",),
    )
