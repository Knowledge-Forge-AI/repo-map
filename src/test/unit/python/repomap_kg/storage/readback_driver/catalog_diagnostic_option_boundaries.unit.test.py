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


def test_psycopg_diagnose_long_form_statement_timeout_declined_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression 5: --statement_timeout=100: bounded correctly or declined before connection,
    # never passed through with a looser overriding assignment.
    connector = PsycopgJsonReadbackConnector()
    monkeypatch.setenv("PGOPTIONS", "--statement_timeout=100")
    # Declines before connection; lower guard ensures connect was never called
    assert (
        connector.diagnose_database_presence(
            psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
            target_database="target_db",
        )
        == "unavailable"
    )

@pytest.mark.parametrize(
    "invalid_opts",
    (
        "-x",
        "-c statement_timeout=100 -c statement_timeout=200",
        "-c app=foo -c app=bar",
        "-c app='foo bar'",
        '-c app="foo bar"',
        r"-c app=foo\ bar",
        "-c",
        "-c foo",
    ),
)
def test_psycopg_diagnose_conservative_syntax_boundary_refusal(
    monkeypatch: pytest.MonkeyPatch,
    invalid_opts: str,
) -> None:
    # Regression 6: Unknown options, duplicates, escaped/quoted unrelated values: preserve supported
    # semantics or decline before connection without leaking or silently rewriting their values.
    connector = PsycopgJsonReadbackConnector()
    monkeypatch.setenv("PGOPTIONS", invalid_opts)
    assert (
        connector.diagnose_database_presence(
            psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
            target_database="target_db",
        )
        == "unavailable"
    )

@pytest.mark.parametrize(
    "options_val",
    (
        "-c STATEMENT_TIMEOUT=100",
        "-cSTATEMENT_TIMEOUT=100",
        "-c Statement_Timeout=100",
        "-cStatement_Timeout=100",
    ),
)
@pytest.mark.parametrize("timeout_seconds", (2.5, None))
def test_psycopg_diagnose_casing_timeout_options_no_widening(
    monkeypatch: pytest.MonkeyPatch,
    options_val: str,
    timeout_seconds: float | None,
) -> None:
    # Item 1: Uppercase and mixed-case timeout keys in spaced and attached forms,
    # with and without a caller budget: emitted options / effective cap never exceed
    # the inherited nonzero limit.
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
        timeout_seconds=timeout_seconds,
        clock=fake_clock,
    )
    assert presence == "absent"
    is_att = options_val.startswith("-c") and not options_val.startswith("-c ")
    expected_snippet = "-cstatement_timeout=100" if is_att else "-c statement_timeout=100"
    assert expected_snippet in captured_kwargs["options"]
    assert "-c default_transaction_read_only=on" in captured_kwargs["options"]
    assert "statement_timeout=3000" not in captured_kwargs["options"]
    # No SET statement_timeout statement executed; cap is not widened
    assert len(fake_cursor.executed) == 1
    assert fake_cursor.executed[0] == (
        "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s)",
        ("target_db",),
    )
    assert fake_cursor.closed is True
    assert fake_conn.closed is True

@pytest.mark.parametrize(
    "dup_opts",
    (
        "-c statement_timeout=100 -c STATEMENT_TIMEOUT=200",
        "-c STATEMENT_TIMEOUT=100 -c statement_timeout=200",
        "-cStatement_Timeout=100 -cSTATEMENT_TIMEOUT=200",
        "-cSTATEMENT_TIMEOUT=100 -cStatement_Timeout=200",
        "-c app_name=foo -c APP_NAME=bar",
        "-c APP_NAME=bar -c app_name=foo",
        "-c default_transaction_read_only=on -c DEFAULT_TRANSACTION_READ_ONLY=on",
        "-c DEFAULT_TRANSACTION_READ_ONLY=off -c default_transaction_read_only=on",
    ),
)
def test_psycopg_diagnose_case_equivalent_duplicates_refused_before_connect(
    monkeypatch: pytest.MonkeyPatch,
    dup_opts: str,
) -> None:
    # Item 2: Case-equivalent duplicate timeout keys in both orders are refused before connection,
    # including unrelated keys and read-only keys.
    connector = PsycopgJsonReadbackConnector()
    monkeypatch.setenv("PGOPTIONS", dup_opts)
    assert (
        connector.diagnose_database_presence(
            psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
            target_database="target_db",
        )
        == "unavailable"
    )

def test_psycopg_diagnose_normalize_keys_preserve_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Item 2 (continued): Normalize names to lowercase, but preserve values exactly.
    import psycopg

    connector = PsycopgJsonReadbackConnector()
    captured_kwargs: dict[str, Any] = {}
    fake_cursor = _FakeCursor(row=(False,))
    fake_conn = _FakeConnection(fake_cursor)

    def recording_connect(**kwargs: Any):
        captured_kwargs.update(kwargs)
        return fake_conn

    monkeypatch.setattr(psycopg, "connect", recording_connect)
    monkeypatch.setenv("PGOPTIONS", "-c APPLICATION_NAME=PreserveMixedCaseValue")

    presence = connector.diagnose_database_presence(
        psql_args=["-h", "127.0.0.1", "-p", "5432", "-U", "admin", "-d", "postgres"],
        target_database="target_db",
    )
    assert presence == "absent"
    assert "-c application_name=PreserveMixedCaseValue" in captured_kwargs["options"]
