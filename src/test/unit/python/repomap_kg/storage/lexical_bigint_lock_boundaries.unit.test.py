"""Unit contracts for BIGINT-safe cloe_lexical lifecycle advisory locks."""

from __future__ import annotations

from typing import Any

from common_lore_index.storage import lexical_lifecycle as lifecycle
from common_lore_index.storage.lexical_build_lease import (
    LIFECYCLE_ADVISORY_NAMESPACE,
    acquire_repository_lifecycle_lock,
)


MAX_SIGNED_BIGINT = 2**63 - 1


class _Cursor:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.connection.executed.append((sql, params))

    def fetchone(self) -> Any:
        return self.connection.lock_row


class _Connection:
    def __init__(self) -> None:
        self.lock_row: Any = (True,)
        self.executed: list[tuple[str, Any]] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self)


def test_lifecycle_lock_binds_the_full_signed_bigint_without_narrowing() -> None:
    """The lease helper must bind a namespace and an untruncated BIGINT ID."""
    connection = _Connection()

    acquire_repository_lifecycle_lock(connection, MAX_SIGNED_BIGINT)

    sql, params = connection.executed[-1]
    compact = " ".join(sql.split())
    assert LIFECYCLE_ADVISORY_NAMESPACE == "cloe_lexical:lifecycle:v1"
    assert "pg_try_advisory_xact_lock(pg_catalog.hashtextextended(" in compact
    assert "pg_catalog.hashtextextended(%s, %s::bigint)" in compact
    assert "::int" not in compact
    assert params == (LIFECYCLE_ADVISORY_NAMESPACE, MAX_SIGNED_BIGINT)


def test_commit_fence_hashes_the_same_namespace_with_native_bigint_repository_id() -> None:
    """The final publication fence must use the same one-key BIGINT lock contract."""
    compact = " ".join(lifecycle.VERIFY_FENCE_AT_COMMIT_SQL.split())

    assert "pg_try_advisory_xact_lock(pg_catalog.hashtextextended(" in compact
    assert (
        f"'{LIFECYCLE_ADVISORY_NAMESPACE}', lc.repository_id::bigint)) "
        "AS advisory_lock_acquired"
    ) in compact
    assert "::int" not in compact
