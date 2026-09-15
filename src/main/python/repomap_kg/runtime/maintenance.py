"""Cross-process maintenance exclusion over one PostgreSQL authority database."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Protocol

import psycopg


MAINTENANCE_LOCK_KEY = 0x5245504F


class ConnectionFactory(Protocol):
    def __call__(self) -> psycopg.Connection[Any]: ...


class MaintenanceUnavailableError(RuntimeError):
    """Raised when ordinary work is refused by requested or active maintenance."""


@contextmanager
def maintenance_activity(connect: ConnectionFactory) -> Iterator[None]:
    """Hold shared maintenance ownership for one complete ordinary operation."""

    connection = connect()
    try:
        acquired = _query_bool(
            connection,
            "SELECT pg_try_advisory_lock_shared(%s)",
        )
        if not acquired:
            raise MaintenanceUnavailableError("schema maintenance is active")
        yield
    finally:
        connection.close()


@contextmanager
def maintenance_window(connect: ConnectionFactory) -> Iterator[None]:
    """Wait for existing work to drain and hold exclusive maintenance ownership."""

    connection = connect()
    try:
        _execute_lock(connection, "SELECT pg_advisory_lock(%s)")
        yield
    finally:
        connection.close()


def maintenance_ready(connect: ConnectionFactory) -> bool:
    """Return whether new work can enter without waiting."""

    try:
        with maintenance_activity(connect):
            return True
    except MaintenanceUnavailableError:
        return False


def require_transaction_admission(connection: psycopg.Connection[Any]) -> None:
    """Require shared maintenance ownership until the current transaction ends."""

    acquired = _query_bool(
        connection,
        "SELECT pg_try_advisory_xact_lock_shared(%s)",
    )
    if not acquired:
        raise MaintenanceUnavailableError("schema maintenance is active")


def _execute_lock(connection: psycopg.Connection[Any], statement: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(statement, (MAINTENANCE_LOCK_KEY,))


def _query_bool(connection: psycopg.Connection[Any], statement: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(statement, (MAINTENANCE_LOCK_KEY,))
        row = cursor.fetchone()
    if row is None or not isinstance(row[0], bool):
        raise RuntimeError("maintenance lock result is invalid")
    return row[0]


__all__ = [
    "MAINTENANCE_LOCK_KEY",
    "MaintenanceUnavailableError",
    "maintenance_activity",
    "maintenance_ready",
    "maintenance_window",
    "require_transaction_admission",
]
