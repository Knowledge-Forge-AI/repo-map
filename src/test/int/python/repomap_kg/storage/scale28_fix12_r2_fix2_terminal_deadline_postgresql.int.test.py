from __future__ import annotations

import socket
from collections.abc import Sequence
from time import monotonic, sleep

import psycopg
import pytest

from repomap_test_support.postgres_harness import (
    require_postgres_binaries,
    temporary_postgres,
)
import scale15_actual_path_readback as readback


def test_terminal_read_succeeds_once_and_settles_the_exact_connection() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        before = _backend_count(postgres)

        started = monotonic()
        summary = readback.read_terminal_backend_summary(postgres.psql_args)
        elapsed = monotonic() - started

        assert summary == {"observer": 1, "unknown": before - 1}
        assert elapsed <= 0.5
        assert _backend_count(postgres) == before


def test_terminal_query_is_bounded_by_the_single_terminal_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        before = _backend_count(postgres)
        monkeypatch.setattr(
            readback,
            "_TERMINAL_BACKEND_QUERY",
            b"SELECT count(*) FROM pg_sleep(2)",
        )

        started = monotonic()
        with pytest.raises(readback.TerminalBackendReadTimeout) as raised:
            readback.read_terminal_backend_summary(postgres.psql_args)
        elapsed = monotonic() - started

        assert raised.value.stage == "result_fetch"
        assert raised.value.backend_quiescent is False
        assert raised.value.read_count == 1
        assert elapsed <= 0.75
        assert _wait_for_backend_count(postgres, before)


def test_terminal_acquisition_transport_failure_keeps_its_category() -> None:
    require_postgres_binaries()
    with temporary_postgres() as postgres:
        unavailable_port = _closed_loopback_port()
        args = _replace_port(postgres.psql_args, unavailable_port)

        started = monotonic()
        with pytest.raises(psycopg.OperationalError):
            readback.read_terminal_backend_summary(args)

        assert monotonic() - started <= 0.5


def _backend_count(postgres) -> int:
    return int(
        postgres.psql_scalar(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE datname = current_database();"
        )
    )


def _wait_for_backend_count(postgres, expected: int) -> bool:
    deadline = monotonic() + 3.0
    while monotonic() < deadline:
        if _backend_count(postgres) == expected:
            return True
        sleep(0.02)
    return _backend_count(postgres) == expected


def _closed_loopback_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _replace_port(args: Sequence[str], port: int) -> tuple[str, ...]:
    replaced = list(args)
    replaced[replaced.index("-p") + 1] = str(port)
    return tuple(replaced)
