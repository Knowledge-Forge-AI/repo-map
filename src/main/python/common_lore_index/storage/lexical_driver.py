"""Dedicated Psycopg 3 driver for PostgreSQL cloe_lexical build, query, and revoke."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import importlib
import re
from typing import Any

from common_lore_index.ops.config_records import OpsConfig, OpsPostgresConfig
from common_lore_index.runtime.database_role_contract import (
    COORDINATOR_CONTROL_ROLE,
    READ_STATUS_ROLE,
    REFRESH_PUBLICATION_ROLE,
    read_configured_postgres_password,
)
from common_lore_index.runtime.postgres_route import execution_postgres
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.readback_credentials import psycopg_connection_params

DENIED_LEXICAL_ROLES = frozenset({
    READ_STATUS_ROLE, REFRESH_PUBLICATION_ROLE, COORDINATOR_CONTROL_ROLE,
})
LIMITED_LEXICAL_ROLES = DENIED_LEXICAL_ROLES
_SQLSTATE_RE = re.compile(r"[0-9A-Z]{5}\Z")
DEFAULT_CONNECT_TIMEOUT_SECONDS = 5
DEFAULT_LOCK_TIMEOUT_MS = 500
DEFAULT_QUERY_STATEMENT_TIMEOUT_MS = 2000
DEFAULT_BUILD_STATEMENT_TIMEOUT_MS = 30000


class LexicalStorageError(StorageSchemaError):
    """Sanitized storage error raised by the PostgreSQL lexical driver."""

    def __init__(self, code: str, detail: str, *, sqlstate: str | None = None) -> None:
        self.code = code
        self.detail = detail
        self.sqlstate = sqlstate
        super().__init__(f"{code}: {detail}")


class LexicalRoleDeniedError(LexicalStorageError):
    """Raised when a limited PostgreSQL role attempts to access cloe_lexical."""

    def __init__(self, detail: str) -> None:
        super().__init__("lexical_role_denied", detail)


@dataclass(frozen=True)
class LexicalConnectionParameters:
    """Explicit owner PostgreSQL connection parameters for cloe_lexical."""

    host: str
    port: int
    database: str
    user: str
    password: str | None = field(repr=False, compare=False, default=None)
    connect_timeout_sec: int = DEFAULT_CONNECT_TIMEOUT_SECONDS
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS
    statement_timeout_ms: int = DEFAULT_QUERY_STATEMENT_TIMEOUT_MS
    read_only: bool = False

    def validate(self) -> LexicalConnectionParameters:
        clean_user = (self.user or "").strip()
        if not clean_user:
            raise LexicalStorageError("lexical_authority_missing_user", "PostgreSQL user is required for cloe_lexical access")
        if clean_user in DENIED_LEXICAL_ROLES:
            raise LexicalRoleDeniedError(f"limited database role {clean_user!r} is denied access to cloe_lexical")
        if not self.database or not self.database.strip():
            raise LexicalStorageError("lexical_authority_missing_database", "target graph database name is required")
        if isinstance(self.connect_timeout_sec, bool) or not isinstance(self.connect_timeout_sec, int) or not (1 <= self.connect_timeout_sec <= 10):
            raise LexicalStorageError("lexical_invalid_timeout", "connect_timeout_sec must be between 1 and 10 seconds")
        if isinstance(self.lock_timeout_ms, bool) or not isinstance(self.lock_timeout_ms, int) or not (50 <= self.lock_timeout_ms <= 5000):
            raise LexicalStorageError("lexical_invalid_timeout", "lock_timeout_ms must be between 50 and 5000 ms")
        if isinstance(self.statement_timeout_ms, bool) or not isinstance(self.statement_timeout_ms, int) or not (50 <= self.statement_timeout_ms <= 30000):
            raise LexicalStorageError("lexical_invalid_timeout", "statement_timeout_ms must be between 50 and 30000 ms")
        return self

    def connection_params(self) -> dict[str, Any]:
        self.validate()
        ro_flag = " -c default_transaction_read_only=on" if self.read_only else ""
        base: dict[str, str] = {
            "host": self.host, "port": str(self.port), "user": self.user, "dbname": self.database,
            "connect_timeout": str(self.connect_timeout_sec),
            "options": f"-c lock_timeout={self.lock_timeout_ms} -c statement_timeout={self.statement_timeout_ms}{ro_flag}",
        }
        return psycopg_connection_params(base, self.password)


LexicalConnectionFactory = Callable[[LexicalConnectionParameters], Any]


@dataclass(frozen=True)
class LexicalPostgresAuthority:
    """Explicit owner-role PostgreSQL connection authority for cloe_lexical."""

    postgres: OpsPostgresConfig
    database: str
    password: str | None = field(repr=False, compare=False, default=None)

    def validate_owner_principal(self) -> LexicalPostgresAuthority:
        user = (self.postgres.user or "").strip()
        if not user:
            raise LexicalStorageError(
                "lexical_authority_missing_user",
                "PostgreSQL user is required for cloe_lexical access",
            )
        if user in DENIED_LEXICAL_ROLES:
            raise LexicalStorageError(
                "lexical_role_denied",
                f"limited database role {user!r} is denied access to cloe_lexical",
            )
        if not self.database or not self.database.strip():
            raise LexicalStorageError(
                "lexical_authority_missing_database",
                "target graph database name is required",
            )
        return self

    def connection_params(self) -> dict[str, Any]:
        self.validate_owner_principal()
        base: dict[str, str] = {
            "host": self.postgres.host,
            "port": str(self.postgres.port),
            "user": self.postgres.user,
            "dbname": self.database,
        }
        return psycopg_connection_params(base, self.password)


def resolve_lexical_postgres_authority(
    config: OpsConfig,
    database: str,
) -> LexicalPostgresAuthority:
    """Resolve owner/admin PostgreSQL connection authority without role projection."""
    try:
        password = read_configured_postgres_password(config)
    except ValueError as error:
        raise LexicalStorageError(
            "lexical_credential_unavailable",
            str(error),
        ) from None
    routed = execution_postgres(config)
    return LexicalPostgresAuthority(
        postgres=routed,
        database=database,
        password=password,
    ).validate_owner_principal()


def _import_psycopg() -> Any:
    try:
        return importlib.import_module("psycopg")
    except ImportError as error:
        raise LexicalStorageError(
            "postgresql_driver_unavailable",
            "Psycopg 3 driver is required for PostgreSQL lexical operations",
        ) from error


def sanitize_driver_exception(
    error: BaseException,
    *,
    operation: str,
) -> LexicalStorageError:
    """Map a Psycopg or OS exception to a public-safe LexicalStorageError."""
    if isinstance(error, LexicalStorageError):
        return error
    sqlstate = getattr(error, "sqlstate", None)
    clean_state = (
        sqlstate
        if isinstance(sqlstate, str) and _SQLSTATE_RE.fullmatch(sqlstate)
        else None
    )
    if clean_state == "42501":
        return LexicalStorageError(
            "lexical_permission_denied",
            f"PostgreSQL permission denied during {operation}",
            sqlstate=clean_state,
        )
    if clean_state == "3D000":
        return LexicalStorageError(
            "lexical_database_missing",
            f"target graph database does not exist for {operation}",
            sqlstate=clean_state,
        )
    if clean_state and clean_state.startswith("28"):
        return LexicalStorageError(
            "lexical_authentication_failed",
            f"PostgreSQL authentication failed during {operation}",
            sqlstate=clean_state,
        )
    if clean_state and clean_state.startswith("08"):
        return LexicalStorageError(
            "lexical_connection_failed",
            f"PostgreSQL connection failed during {operation}",
            sqlstate=clean_state,
        )
    if clean_state == "57014" or "statement timeout" in str(error).lower():
        return LexicalStorageError(
            "lexical_statement_timeout",
            f"PostgreSQL statement timeout during {operation}",
            sqlstate=clean_state or "57014",
        )
    if clean_state == "55P03" or "lock timeout" in str(error).lower():
        return LexicalStorageError(
            "lexical_lock_not_available",
            f"PostgreSQL lock timeout during {operation}",
            sqlstate=clean_state or "55P03",
        )
    if clean_state == "25006" or "read-only transaction" in str(error).lower():
        return LexicalStorageError(
            "lexical_read_only_violation",
            f"PostgreSQL read-only transaction violation during {operation}",
            sqlstate=clean_state or "25006",
        )
    if clean_state in {"40001", "40P01"}:
        return LexicalStorageError(
            "lexical_serialization_conflict",
            f"PostgreSQL serialization or deadlock conflict during {operation}",
            sqlstate=clean_state,
        )
    msg = str(error)
    for marker in (
        "cloe_lexical_publication_fence_mismatch",
        "cloe_lexical_generation_not_published",
        "cloe_lexical_policy_digest_mismatch",
        "cloe_lexical_concurrent_build_active",
        "cloe_lexical_competing_builder_in_progress",
        "cloe_lexical_build_lease_lost",
        "cloe_lexical_builder_lease_expired",
        "cloe_lexical_count_verification_failed",
        "cloe_lexical_row_count_mismatch",
        "cloe_lexical schema or object custody is not owned by the database owner",
        "cloe_lexical schema is missing the expected cloe-lexical-schema:1 marker",
    ):
        if marker in msg:
            return LexicalStorageError(
                marker.replace(" ", "_"),
                f"{marker} during {operation}",
                sqlstate=clean_state,
            )
    return LexicalStorageError(
        "lexical_query_failed",
        f"PostgreSQL lexical {operation} failed"
        + (f" (sqlstate {clean_state})" if clean_state else ""),
        sqlstate=clean_state,
    )


@contextmanager
def open_lexical_connection(
    authority: LexicalPostgresAuthority,
    *,
    read_only: bool = False,
    autocommit: bool = False,
    operation: str = "connect",
) -> Iterator[Any]:
    """Open a Psycopg 3 connection using explicit lexical authority."""
    authority.validate_owner_principal()
    psycopg = _import_psycopg()
    params = authority.connection_params()
    conn = None
    try:
        conn = psycopg.connect(**params)
        if read_only:
            conn.read_only = True
        if autocommit:
            conn.autocommit = True
    except Exception as error:
        if conn is not None:
            conn.close()
        raise sanitize_driver_exception(error, operation=operation) from None
    try:
        with conn:
            yield conn
    except Exception as error:
        raise sanitize_driver_exception(error, operation=operation) from None
    finally:
        conn.close()


def execute_fetchall(
    connection: Any,
    sql: str,
    params: Sequence[Any] | Mapping[str, Any] | None = None,
    *,
    operation: str = "query",
) -> list[tuple[Any, ...]]:
    """Execute one parameterized SQL statement and return all rows."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            if cursor.description is None:
                return []
            return [tuple(row) for row in cursor.fetchall()]
    except Exception as error:
        raise sanitize_driver_exception(error, operation=operation) from None


def execute_fetchone(
    connection: Any,
    sql: str,
    params: Sequence[Any] | Mapping[str, Any] | None = None,
    *,
    operation: str = "query",
) -> tuple[Any, ...] | None:
    """Execute one parameterized SQL statement and return one row or None."""
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            if cursor.description is None:
                return None
            row = cursor.fetchone()
            return tuple(row) if row is not None else None
    except Exception as error:
        raise sanitize_driver_exception(error, operation=operation) from None


def open_psycopg_lexical_connection(
    params: LexicalConnectionParameters,
) -> Any:
    """Open a Psycopg 3 connection from validated LexicalConnectionParameters."""
    params.validate()
    psycopg = _import_psycopg()
    try:
        return psycopg.connect(**params.connection_params())
    except Exception as error:
        raise sanitize_driver_exception(error, operation="connect") from None


@contextmanager
def lexical_connection_scope(
    params: LexicalConnectionParameters,
    *,
    connection_factory: LexicalConnectionFactory = open_psycopg_lexical_connection,
    operation: str = "connect",
    read_only: bool = False,
) -> Iterator[Any]:
    """Context manager opening and closing a cloe_lexical connection."""
    effective_params = replace(params, read_only=True) if read_only else params
    effective_params.validate()
    conn = None
    try:
        conn = connection_factory(effective_params)
    except Exception as error:
        if conn is not None:
            conn.close()
        raise sanitize_driver_exception(error, operation=operation) from None
    try:
        yield conn
    except Exception as error:
        try:
            conn.rollback()
        except Exception:
            pass
        raise sanitize_driver_exception(error, operation=operation) from None
    finally:
        conn.close()


__all__ = [
    "DENIED_LEXICAL_ROLES", "LIMITED_LEXICAL_ROLES", "LexicalConnectionFactory",
    "LexicalConnectionParameters", "LexicalPostgresAuthority", "LexicalRoleDeniedError",
    "LexicalStorageError", "execute_fetchall", "execute_fetchone",
    "lexical_connection_scope", "open_lexical_connection", "open_psycopg_lexical_connection",
    "resolve_lexical_postgres_authority", "sanitize_driver_exception",
]
