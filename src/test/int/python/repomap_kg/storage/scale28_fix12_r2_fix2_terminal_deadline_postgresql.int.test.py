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
        params = readback._psycopg_connection_params_from_psql_args(postgres.psql_args)
        with psycopg.connect(
            host=params.get("host"),
            port=params.get("port"),
            user=params.get("user"),
            dbname=params.get("dbname"),
        ) as connection:
            other_before = 0
            settle_deadline = monotonic() + 2.0
            last_count = None
            while monotonic() < settle_deadline:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND pid <> pg_backend_pid();"
                    )
                    row = cursor.fetchone()
                    count = int(row[0]) if row else 0
                if last_count is not None and count == last_count:
                    other_before = count
                    break
                last_count = count
                sleep(0.01)
            else:
                other_before = last_count if last_count is not None else 0

            started = monotonic()
            summary = readback.read_terminal_backend_summary(postgres.psql_args)
            elapsed = monotonic() - started

            assert summary == {"observer": 1, "unknown": other_before + 1}
            assert elapsed <= 0.5

            deadline = monotonic() + 3.0
            settled = False
            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND pid <> pg_backend_pid();"
                    )
                    row = cursor.fetchone()
                    if row and int(row[0]) == other_before:
                        settled = True
                        break
                sleep(0.01)
            assert settled


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
            "WHERE datname = current_database() AND pid <> pg_backend_pid();"
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
