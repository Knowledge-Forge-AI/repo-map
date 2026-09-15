from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from repomap_kg.storage.readback_driver import (
    PsycopgJsonReadbackConnector,
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


def test_psycopg_diagnose_tightens_safely_or_declines_when_sub_inherited_budget_remains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression 3: Less than 100 ms remains after an inherited 100 ms limit: tighten safely or decline.
    # Submillisecond/exhausted allowance never becomes zero/disabled and releases no catalog SELECT.
    # Account for elapsed adjustment time as applicable.
    import psycopg

    connector = PsycopgJsonReadbackConnector()

    # Subcase 3a: 50 ms remaining (< 100 ms) tightens safely
    fake_cursor_a = _FakeCursor(row=(False,))
    fake_conn_a = _FakeConnection(fake_cursor_a)
    cur_time_a = 0.0

    def connect_a(**kwargs: Any):
        nonlocal cur_time_a
        cur_time_a += 2.45
        return fake_conn_a

    monkeypatch.setattr(psycopg, "connect", connect_a)
    monkeypatch.setenv("PGOPTIONS", "-c statement_timeout=100")

    presence_a = connector.diagnose_database_presence(
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
        target_database="target_db",
        timeout_seconds=2.5,
        clock=lambda: cur_time_a,
    )
    assert presence_a == "absent"
    assert len(fake_cursor_a.executed) == 2
    stmt_a, params_a = fake_cursor_a.executed[0]
    assert stmt_a.startswith("SET statement_timeout = ")
    assert params_a is None
    assert 0 < int(stmt_a.split("=")[1]) < 100
    assert fake_cursor_a.executed[1][0].startswith("SELECT EXISTS")

    # Subcase 3b: 0 ms remaining declines without emitting statement_timeout=0 or running SELECT
    fake_cursor_b = _FakeCursor(row=(False,))
    fake_conn_b = _FakeConnection(fake_cursor_b)
    cur_time_b = 0.0

    def connect_b(**kwargs: Any):
        nonlocal cur_time_b
        cur_time_b += 2.5
        return fake_conn_b

    monkeypatch.setattr(psycopg, "connect", connect_b)
    presence_b = connector.diagnose_database_presence(
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
        target_database="target_db",
        timeout_seconds=2.5,
        clock=lambda: cur_time_b,
    )
    assert presence_b == "unavailable"
    assert len(fake_cursor_b.executed) == 0

    # Subcase 3c: Submillisecond remaining (< 1 ms, e.g. 0.4 ms) declines cleanly
    fake_cursor_c = _FakeCursor(row=(False,))
    fake_conn_c = _FakeConnection(fake_cursor_c)
    cur_time_c = 0.0

    def connect_c(**kwargs: Any):
        nonlocal cur_time_c
        cur_time_c += 2.4996
        return fake_conn_c

    monkeypatch.setattr(psycopg, "connect", connect_c)
    presence_c = connector.diagnose_database_presence(
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
        target_database="target_db",
        timeout_seconds=2.5,
        clock=lambda: cur_time_c,
    )
    assert presence_c == "unavailable"
    assert len(fake_cursor_c.executed) == 0

    # Subcase 3d: Elapsed adjustment time exhausts allowance before SELECT
    cur_time_d = 0.0

    class _SlowSetCursor(_FakeCursor):
        def execute(self, sql: str, params: Any = None) -> None:
            super().execute(sql, params)
            if "SET statement_timeout" in sql:
                nonlocal cur_time_d
                cur_time_d += 0.06

    fake_cursor_d = _SlowSetCursor(row=(False,))
    fake_conn_d = _FakeConnection(fake_cursor_d)

    def connect_d(**kwargs: Any):
        nonlocal cur_time_d
        cur_time_d += 2.45
        return fake_conn_d

    monkeypatch.setattr(psycopg, "connect", connect_d)
    presence_d = connector.diagnose_database_presence(
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
        target_database="target_db",
        timeout_seconds=2.5,
        clock=lambda: cur_time_d,
    )
    assert presence_d == "unavailable"
    assert len(fake_cursor_d.executed) == 1
    stmt_d, _ = fake_cursor_d.executed[0]
    assert stmt_d.startswith("SET statement_timeout = ")
    assert 0 < int(stmt_d.split("=")[1]) < 100

def test_psycopg_diagnose_no_caller_budget_retains_independent_finite_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression 4: No caller budget: retain independent finite caps, normal empty options,
    # shorter supported inherited settings, and finite replacement of inherited zero.
    import psycopg

    connector = PsycopgJsonReadbackConnector()

    for opts, expected_to in (
        ("", "statement_timeout=3000"),
        ("-c statement_timeout=100", "statement_timeout=100"),
        ("-c statement_timeout=0", "statement_timeout=3000"),
    ):
        captured_kwargs: dict[str, Any] = {}
        fake_cursor = _FakeCursor(row=(False,))
        fake_conn = _FakeConnection(fake_cursor)

        def recording_connect(**kwargs: Any):
            captured_kwargs.update(kwargs)
            return fake_conn

        monkeypatch.setattr(psycopg, "connect", recording_connect)
        if opts:
            monkeypatch.setenv("PGOPTIONS", opts)
        else:
            monkeypatch.delenv("PGOPTIONS", raising=False)

        presence = connector.diagnose_database_presence(
            psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
            target_database="target_db",
            timeout_seconds=None,
        )
        assert presence == "absent"
        assert captured_kwargs["connect_timeout"] == "3"
        assert expected_to in captured_kwargs["options"]
        assert "-c default_transaction_read_only=on" in captured_kwargs["options"]
        # No SET statement_timeout query executed
        assert len(fake_cursor.executed) == 1
        assert fake_cursor.executed[0][0].startswith("SELECT EXISTS")

def test_psycopg_diagnose_partial_adjustment_delay_declines_without_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Item 3: 20 ms partial adjustment delay in the 2.5 s/2.45 s/100 ms example:
    # no catalog SELECT and 'unavailable', without a zero timeout; connection/cursor settled.
    import psycopg

    connector = PsycopgJsonReadbackConnector()
    cur_time = 0.0

    class _DelaySetCursor(_FakeCursor):
        def execute(self, sql: str, params: Any = None) -> None:
            super().execute(sql, params)
            if "SET statement_timeout" in sql:
                nonlocal cur_time
                cur_time += 0.020

    fake_cursor = _DelaySetCursor(row=(False,))
    fake_conn = _FakeConnection(fake_cursor)

    def connect_delay(**kwargs: Any):
        nonlocal cur_time
        cur_time += 2.45
        return fake_conn

    monkeypatch.setattr(psycopg, "connect", connect_delay)
    monkeypatch.setenv("PGOPTIONS", "-c statement_timeout=100")

    presence = connector.diagnose_database_presence(
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
        target_database="target_db",
        timeout_seconds=2.5,
        clock=lambda: cur_time,
    )
    assert presence == "unavailable"
    assert len(fake_cursor.executed) == 1
    stmt, _ = fake_cursor.executed[0]
    assert stmt == "SET statement_timeout = 49"
    assert fake_cursor.closed is True
    assert fake_conn.closed is True

def test_psycopg_diagnose_tighter_inherited_cap_with_ample_remainder_no_widening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Item 4: A much tighter inherited cap with ample remainder still allows one
    # parameterized catalog SELECT without widening.
    import psycopg

    connector = PsycopgJsonReadbackConnector()
    captured_kwargs: dict[str, Any] = {}
    fake_cursor = _FakeCursor(row=(True,))
    fake_conn = _FakeConnection(fake_cursor)
    cur_time = 0.0

    def connect_rec(**kwargs: Any):
        nonlocal cur_time
        captured_kwargs.update(kwargs)
        cur_time += 0.5
        return fake_conn

    monkeypatch.setattr(psycopg, "connect", connect_rec)
    monkeypatch.setenv("PGOPTIONS", "-c statement_timeout=25")

    presence = connector.diagnose_database_presence(
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
        target_database="target_db",
        timeout_seconds=5.0,
        clock=lambda: cur_time,
    )
    assert presence == "present"
    assert "-c statement_timeout=25" in captured_kwargs["options"]
    assert len(fake_cursor.executed) == 1
    assert fake_cursor.executed[0] == (
        "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s)",
        ("target_db",),
    )
    assert fake_cursor.closed is True
    assert fake_conn.closed is True
