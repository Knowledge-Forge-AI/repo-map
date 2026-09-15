from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from repomap_kg.storage.readback_driver import (
    PsycopgJsonReadbackConnector,
    _resolve_diagnostic_options,
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


@pytest.mark.parametrize(
    ("row_val", "expected_presence"),
    (
        ((False,), "absent"),
        ((True,), "present"),
        ([False], "absent"),
        ([True], "present"),
        (False, "malformed"),
        (7, "malformed"),
        ({"exists": False}, "malformed"),
        ({0: False}, "malformed"),
        ((False, True), "malformed"),
        ((1,), "malformed"),
        (("False",), "malformed"),
        (None, "malformed"),
    ),
)
def test_psycopg_diagnose_database_presence_row_shape_validation(
    monkeypatch: pytest.MonkeyPatch,
    row_val: Any,
    expected_presence: str,
) -> None:
    import psycopg

    fake_cursor = _FakeCursor(row=row_val)
    fake_conn = _FakeConnection(fake_cursor)
    monkeypatch.setattr(psycopg, "connect", lambda **kwargs: fake_conn)

    connector = PsycopgJsonReadbackConnector()
    presence = connector.diagnose_database_presence(
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
        target_database="target_db",
    )
    assert presence == expected_presence
    assert fake_cursor.closed is True
    assert fake_conn.closed is True
    assert fake_conn.read_only is True


@pytest.mark.parametrize(
    "invalid_budget",
    (
        0,
        0.0,
        -1.0,
        0.0001,
        0.5,
        1.5,
        1.999,
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
    ),
)
def test_psycopg_diagnose_timeout_inputs_rejected_without_connect(
    invalid_budget: Any,
) -> None:
    connector = PsycopgJsonReadbackConnector()
    assert (
        connector.diagnose_database_presence(
            psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
            target_database="target_db",
            timeout_seconds=invalid_budget,
        )
        == "unavailable"
    )


def test_psycopg_diagnose_pgconnect_timeout_env_handling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psycopg

    connector = PsycopgJsonReadbackConnector()

    # Values below driver minimum 2.0 safely decline without connect
    monkeypatch.setenv("PGCONNECT_TIMEOUT", "1")
    assert (
        connector.diagnose_database_presence(
            psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
            target_database="target_db",
        )
        == "unavailable"
    )

    # Invalid non-numeric env values safely decline without connect
    monkeypatch.setenv("PGCONNECT_TIMEOUT", "invalid")
    assert (
        connector.diagnose_database_presence(
            psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
            target_database="target_db",
        )
        == "unavailable"
    )

    # Valid value >= 2.0 is respected
    monkeypatch.setenv("PGCONNECT_TIMEOUT", "2")
    captured: dict[str, Any] = {}
    fake_cursor = _FakeCursor(row=(False,))
    fake_conn = _FakeConnection(fake_cursor)

    def recording_connect(**kwargs: Any):
        captured.update(kwargs)
        return fake_conn

    monkeypatch.setattr(psycopg, "connect", recording_connect)
    assert (
        connector.diagnose_database_presence(
            psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
            target_database="target_db",
        )
        == "absent"
    )
    assert captured["connect_timeout"] == "2"


@pytest.mark.parametrize(
    ("existing", "target_ms", "expected_snippet", "expected_effective_ms", "expected_none"),
    (
        ("", 3000, "-c default_transaction_read_only=on -c statement_timeout=3000", 3000, False),
        (
            "-c statement_timeout=100 -c application_name=private_value",
            3000,
            "-c statement_timeout=100 -c application_name=private_value -c default_transaction_read_only=on",
            100,
            False,
        ),
        (
            "-c statement_timeout=0",
            3000,
            "-c statement_timeout=3000 -c default_transaction_read_only=on",
            3000,
            False,
        ),
        (
            "-c statement_timeout=5000",
            3000,
            "-c statement_timeout=3000 -c default_transaction_read_only=on",
            3000,
            False,
        ),
        (
            "-c statement_timeout=2s",
            3000,
            "-c statement_timeout=2000 -c default_transaction_read_only=on",
            2000,
            False,
        ),
        (
            "-cstatement_timeout=100",
            3000,
            "-cstatement_timeout=100 -c default_transaction_read_only=on",
            100,
            False,
        ),
        (
            "-cstatement_timeout=0",
            3000,
            "-cstatement_timeout=3000 -c default_transaction_read_only=on",
            3000,
            False,
        ),
        (
            "-c STATEMENT_TIMEOUT=100",
            3000,
            "-c statement_timeout=100 -c default_transaction_read_only=on",
            100,
            False,
        ),
        (
            "-cSTATEMENT_TIMEOUT=100",
            3000,
            "-cstatement_timeout=100 -c default_transaction_read_only=on",
            100,
            False,
        ),
        (
            "-c Statement_Timeout=100",
            3000,
            "-c statement_timeout=100 -c default_transaction_read_only=on",
            100,
            False,
        ),
        (
            "-c APPLICATION_NAME=MyApp",
            3000,
            "-c application_name=MyApp -c default_transaction_read_only=on -c statement_timeout=3000",
            3000,
            False,
        ),
        ("-c statement_timeout=100 -c STATEMENT_TIMEOUT=200", 3000, "", 0, True),
        ("-c app=foo -c APP=bar", 3000, "", 0, True),
        (
            "-c DEFAULT_TRANSACTION_READ_ONLY=on -c default_transaction_read_only=on",
            3000,
            "",
            0,
            True,
        ),
        ("-c statement_timeout=invalid", 3000, "", 0, True),
        ('unclosed quote "', 3000, "", 0, True),
        ("-c application_name='quoted'", 3000, "", 0, True),
        ('-c application_name="quoted"', 3000, "", 0, True),
        (r"-c application_name=escaped\ space", 3000, "", 0, True),
        ("--statement_timeout=100", 3000, "", 0, True),
        ("-c statement_timeout=100 -c statement_timeout=200", 3000, "", 0, True),
        ("-c app=foo -c app=bar", 3000, "", 0, True),
        ("-x", 3000, "", 0, True),
        ("-c", 3000, "", 0, True),
        ("-c foo", 3000, "", 0, True),
    ),
)
def test_resolve_diagnostic_options_precedence_and_refusal(
    existing: str,
    target_ms: int,
    expected_snippet: str,
    expected_effective_ms: int,
    expected_none: bool,
) -> None:
    res = _resolve_diagnostic_options(existing, target_ms)
    if expected_none:
        assert res is None
    else:
        assert res is not None
        assert res.options == expected_snippet
        assert res.effective_timeout_ms == expected_effective_ms
