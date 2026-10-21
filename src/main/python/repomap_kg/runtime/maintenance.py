"""Cross-process maintenance exclusion over one PostgreSQL authority database."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path
import threading
from typing import Any, Iterator, Protocol

import psycopg


MAINTENANCE_LOCK_KEY = 0x5245504F
DDL_QUIESCENCE_ASSUMPTION = (
    "trusted-admin-ddl-quiescence-assumed; "
    "pre-post-fingerprints-detect-observed-catalog-drift-not-transient-ddl-absence"
)
VALID_MAINTENANCE_CUSTODY_MODES = frozenset(
    {
        "coordinator-maintenance-window",
        "direct-advisory-lock-window",
        "reused-outer-maintenance-window",
    }
)
_CUSTODY_STATE = threading.local()


@dataclass(frozen=True)
class MaintenanceCustody:
    """In-process record of active advisory-lock maintenance custody."""

    mode: str
    control_database: str | None
    databases: tuple[str, ...]
    lock_key: int = MAINTENANCE_LOCK_KEY
    authority_namespace: str | None = None


def runtime_maintenance_namespace(
    repo_map_home: Path | str, *, host: str, port: int
) -> str:
    """Derive a redacted runtime/endpoint namespace token for maintenance custody."""

    canonical_home = str(Path(repo_map_home).expanduser().resolve())
    digest = hashlib.sha256(
        f"{canonical_home}\0{host}:{int(port)}".encode("utf-8")
    ).hexdigest()[:16]
    return f"runtime-endpoint:{digest}"


def _valid_authority_namespace(namespace: object) -> bool:
    return (
        isinstance(namespace, str)
        and bool(namespace.strip())
        and namespace.strip() != "*"
    )


class ConnectionFactory(Protocol):
    def __call__(self) -> psycopg.Connection[Any]: ...


class MaintenanceUnavailableError(RuntimeError):
    """Raised when ordinary work is refused by requested or active maintenance."""


def _custody_stack() -> list[MaintenanceCustody]:
    stack = getattr(_CUSTODY_STATE, "stack", None)
    if stack is None:
        stack = []
        _CUSTODY_STATE.stack = stack
    return stack


def active_maintenance_custody() -> MaintenanceCustody | None:
    stack = _custody_stack()
    return stack[-1] if stack else None


def held_maintenance_custody_for(
    *databases: str,
    authority_namespace: str | None = None,
) -> MaintenanceCustody | None:
    if not _valid_authority_namespace(authority_namespace):
        return None
    required = {str(db) for db in databases if str(db)}
    for custody in reversed(_custody_stack()):
        if (
            _valid_authority_namespace(custody.authority_namespace)
            and custody.authority_namespace == authority_namespace
            and (not required or required.issubset(set(custody.databases)))
        ):
            return custody
    return None


@contextmanager
def bind_maintenance_custody(
    *,
    mode: str,
    databases: Iterable[str],
    control_database: str | None = None,
    lock_key: int = MAINTENANCE_LOCK_KEY,
    authority_namespace: str | None = None,
) -> Iterator[MaintenanceCustody]:
    if mode not in VALID_MAINTENANCE_CUSTODY_MODES:
        raise ValueError(f"unsupported maintenance custody mode: {mode!r}")
    normalized: list[str] = []
    if control_database is not None and str(control_database):
        normalized.append(str(control_database))
    for db in sorted({str(item) for item in databases if str(item)}):
        if db not in normalized:
            normalized.append(db)
    custody = MaintenanceCustody(
        mode=mode,
        control_database=control_database,
        databases=tuple(normalized),
        lock_key=lock_key,
        authority_namespace=authority_namespace,
    )
    stack = _custody_stack()
    stack.append(custody)
    try:
        yield custody
    finally:
        stack.pop()


def quiescence_record_for_databases(
    *databases: str,
    before_after_fingerprint_matched: bool,
    authority_namespace: str | None = None,
) -> dict[str, object]:
    custody = held_maintenance_custody_for(
        *databases,
        authority_namespace=authority_namespace,
    )
    held = custody is not None and custody.mode in VALID_MAINTENANCE_CUSTODY_MODES
    mode = custody.mode if held and custody is not None else "unheld"
    return {
        "advisory_lock_key": (
            custody.lock_key if held and custody is not None else MAINTENANCE_LOCK_KEY
        ),
        "before_after_fingerprint_matched": bool(before_after_fingerprint_matched),
        "control_database": custody.control_database if held and custody is not None else None,
        "ddl_quiescence_assumption": DDL_QUIESCENCE_ASSUMPTION,
        "locked_databases": list(custody.databases) if held and custody is not None else [],
        "maintenance_window_held": held,
        "maintenance_window_mode": mode,
        "mode": mode,
        "verified": held and bool(before_after_fingerprint_matched),
    }


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

    connection = None
    try:
        try:
            connection = connect()
            _execute_lock(connection, "SELECT pg_advisory_lock(%s)")
        except psycopg.Error as exc:
            raise MaintenanceUnavailableError("maintenance ownership could not be acquired") from exc
        yield
    finally:
        if connection is not None:
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
        # This dedicated ownership connection closes with the window. Do not
        # impose these limits on the separate connections executing its body.
        cursor.execute(
            "SELECT set_config('lock_timeout', %s, false), "
            "set_config('statement_timeout', %s, false)",
            ("30s", "30s"),
        )
        cursor.execute(statement, (MAINTENANCE_LOCK_KEY,))


def _query_bool(connection: psycopg.Connection[Any], statement: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(statement, (MAINTENANCE_LOCK_KEY,))
        row = cursor.fetchone()
    if row is None or not isinstance(row[0], bool):
        raise RuntimeError("maintenance lock result is invalid")
    return row[0]


__all__ = [
    "DDL_QUIESCENCE_ASSUMPTION",
    "MAINTENANCE_LOCK_KEY",
    "MaintenanceCustody",
    "MaintenanceUnavailableError",
    "active_maintenance_custody",
    "bind_maintenance_custody",
    "held_maintenance_custody_for",
    "maintenance_activity",
    "maintenance_ready",
    "maintenance_window",
    "quiescence_record_for_databases",
    "require_transaction_admission",
    "runtime_maintenance_namespace",
]
