"""Cohesive unit proofs for lexical PostgreSQL driver boundaries."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from common_lore_index.ops.config_records import OpsPostgresConfig
import common_lore_index.storage.lexical_driver as driver


_PARAMETER_CASES = (
    ({"user": ""}, "lexical_authority_missing_user"),
    ({"user": "repomap_read_status"}, "lexical_role_denied"),
    ({"database": ""}, "lexical_authority_missing_database"),
    ({"connect_timeout_sec": True}, "lexical_invalid_timeout"),
    ({"connect_timeout_sec": 0}, "lexical_invalid_timeout"),
    ({"lock_timeout_ms": False}, "lexical_invalid_timeout"),
    ({"lock_timeout_ms": 0}, "lexical_invalid_timeout"),
    ({"statement_timeout_ms": True}, "lexical_invalid_timeout"),
    ({"statement_timeout_ms": 0}, "lexical_invalid_timeout"),
)


class _SqlErr(Exception):
    def __init__(self, message: str, sqlstate: str | None = None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


class _FakeCursor:
    def __init__(
        self,
        *,
        description: Any = (("c",),),
        rows: list[Any] | None = None,
        fail: bool = False,
    ) -> None:
        self.description = description
        self._rows = rows or []
        self._fail = fail

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, _sql: str, _params: Any = None) -> None:
        if self._fail:
            raise _SqlErr("canceling statement due to lock timeout")

    def fetchall(self) -> list[Any]:
        return list(self._rows)

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False
        self.autocommit = False
        self.read_only = False

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        raise RuntimeError("rollback boom")

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    _PARAMETER_CASES,
    ids=(
        "empty-user",
        "limited-role",
        "empty-database",
        "bool-connect-timeout",
        "zero-connect-timeout",
        "bool-lock-timeout",
        "zero-lock-timeout",
        "bool-statement-timeout",
        "zero-statement-timeout",
    ),
)
def test_lexical_connection_parameters_reject_invalid_values(
    overrides: dict[str, Any], expected_code: str
) -> None:
    base: dict[str, Any] = {
        "host": "127.0.0.1",
        "port": 5432,
        "database": "db",
        "user": "owner",
        "password": "pw",
    }
    base.update(overrides)
    with pytest.raises(driver.LexicalStorageError) as exc_info:
        driver.LexicalConnectionParameters(**base).validate()
    assert exc_info.value.code == expected_code


@pytest.mark.parametrize(
    ("user", "database", "expected_code"),
    (
        ("", "db", "lexical_authority_missing_user"),
        ("repomap_read_status", "db", "lexical_role_denied"),
        ("owner", "", "lexical_authority_missing_database"),
    ),
    ids=("empty-user", "limited-role", "empty-database"),
)
def test_lexical_authority_rejects_non_owner_principals(
    user: str, database: str, expected_code: str
) -> None:
    postgres = OpsPostgresConfig(
        host="127.0.0.1",
        port=5432,
        database="db",
        user=user,
        password_file=None,
    )
    with pytest.raises(driver.LexicalStorageError) as exc_info:
        driver.LexicalPostgresAuthority(
            postgres=postgres,
            database=database,
            password="pw",
        ).validate_owner_principal()
    assert exc_info.value.code == expected_code


def test_lexical_authority_resolution_sanitizes_credentials_and_builds_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_no_password(_config: Any) -> str:
        raise ValueError("no pw")

    monkeypatch.setattr(driver, "read_configured_postgres_password", raise_no_password)
    invalid_config: Any = SimpleNamespace()
    with pytest.raises(driver.LexicalStorageError) as exc_info:
        driver.resolve_lexical_postgres_authority(invalid_config, "db")
    assert exc_info.value.code == "lexical_credential_unavailable"

    postgres = OpsPostgresConfig(
        host="127.0.0.1",
        port=5432,
        database="db",
        user="owner",
        password_file=None,
    )
    monkeypatch.setattr(driver, "read_configured_postgres_password", lambda _config: "secret")
    monkeypatch.setattr(driver, "execution_postgres", lambda _config: postgres)
    authority = driver.resolve_lexical_postgres_authority(invalid_config, "db")
    assert authority.connection_params()["dbname"] == "db"

    params = driver.LexicalConnectionParameters(
        host="127.0.0.1",
        port=5432,
        database="db",
        user="owner",
        password="secret",
    ).validate()
    assert params.connection_params()["dbname"] == "db"
    already_sanitized = driver.LexicalStorageError("already_sanitized", "msg")
    assert driver.sanitize_driver_exception(already_sanitized, operation="q") is already_sanitized


_SANITIZATION_CASES = (
    (_SqlErr("denied", "42501"), "lexical_permission_denied"),
    (_SqlErr("missing db", "3D000"), "lexical_database_missing"),
    (_SqlErr("auth fail", "28P01"), "lexical_authentication_failed"),
    (_SqlErr("conn fail", "08006"), "lexical_connection_failed"),
    (_SqlErr("deadlock", "40P01"), "lexical_serialization_conflict"),
    (_SqlErr("canceling statement due to statement timeout", "TOOLONG"), "lexical_statement_timeout"),
    (_SqlErr("canceling statement due to lock timeout"), "lexical_lock_not_available"),
    (_SqlErr("cannot execute in a read-only transaction"), "lexical_read_only_violation"),
    (_SqlErr("cloe_lexical_publication_fence_mismatch"), "cloe_lexical_publication_fence_mismatch"),
    (_SqlErr("cloe_lexical_generation_not_published"), "cloe_lexical_generation_not_published"),
    (_SqlErr("cloe_lexical_policy_digest_mismatch"), "cloe_lexical_policy_digest_mismatch"),
    (_SqlErr("cloe_lexical_concurrent_build_active"), "cloe_lexical_concurrent_build_active"),
    (_SqlErr("cloe_lexical_competing_builder_in_progress"), "cloe_lexical_competing_builder_in_progress"),
    (_SqlErr("cloe_lexical_build_lease_lost"), "cloe_lexical_build_lease_lost"),
    (_SqlErr("cloe_lexical_builder_lease_expired"), "cloe_lexical_builder_lease_expired"),
    (_SqlErr("cloe_lexical_count_verification_failed"), "cloe_lexical_count_verification_failed"),
    (_SqlErr("cloe_lexical_row_count_mismatch"), "cloe_lexical_row_count_mismatch"),
    (_SqlErr("cloe_lexical schema or object custody is not owned by the database owner"), "cloe_lexical_schema_or_object_custody_is_not_owned_by_the_database_owner"),
    (_SqlErr("cloe_lexical schema is missing the expected cloe-lexical-schema:1 marker"), "cloe_lexical_schema_is_missing_the_expected_cloe-lexical-schema:1_marker"),
    (_SqlErr("other err", "23505"), "lexical_query_failed"),
    (_SqlErr("other err no state"), "lexical_query_failed"),
)


@pytest.mark.parametrize(
    ("error", "expected_code"),
    _SANITIZATION_CASES,
    ids=(
        "permission",
        "missing-db",
        "authentication",
        "connection",
        "deadlock",
        "invalid-sqlstate-timeout-message",
        "lock-timeout-message",
        "read-only-message",
        "fence-mismatch",
        "not-published",
        "policy-mismatch",
        "concurrent-build",
        "competing-builder",
        "lease-lost",
        "lease-expired",
        "count-failed",
        "row-count-mismatch",
        "custody",
        "schema-marker",
        "unknown-sqlstate",
        "unknown-error",
    ),
)
def test_sanitize_driver_exception_maps_public_safe_codes(
    error: BaseException, expected_code: str
) -> None:
    assert driver.sanitize_driver_exception(error, operation="q").code == expected_code


def test_lexical_fetch_helpers_return_rows_and_sanitize_failures() -> None:
    assert driver.execute_fetchall(_FakeConnection(_FakeCursor(description=None)), "UPDATE x") == []
    assert driver.execute_fetchone(_FakeConnection(_FakeCursor(description=None)), "UPDATE x") is None
    assert driver.execute_fetchall(
        _FakeConnection(_FakeCursor(rows=[(7,)])), "SELECT 7"
    ) == [(7,)]
    assert driver.execute_fetchone(
        _FakeConnection(_FakeCursor(rows=[(7,)])), "SELECT 7"
    ) == (7,)
    assert driver.execute_fetchone(
        _FakeConnection(_FakeCursor(rows=[])), "SELECT 0"
    ) is None
    with pytest.raises(driver.LexicalStorageError):
        driver.execute_fetchall(_FakeConnection(_FakeCursor(fail=True)), "SELECT 1")
    with pytest.raises(driver.LexicalStorageError):
        driver.execute_fetchone(_FakeConnection(_FakeCursor(fail=True)), "SELECT 1")


def test_lexical_connection_contexts_apply_flags_and_close_on_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    postgres = OpsPostgresConfig(
        host="127.0.0.1",
        port=5432,
        database="db",
        user="owner",
        password_file=None,
    )
    authority = driver.LexicalPostgresAuthority(
        postgres=postgres,
        database="db",
        password="secret",
    ).validate_owner_principal()
    monkeypatch.setattr(
        driver,
        "_import_psycopg",
        lambda: SimpleNamespace(
            connect=lambda **_kwargs: _FakeConnection(_FakeCursor())
        ),
    )
    with driver.open_lexical_connection(authority, read_only=True, autocommit=True) as connection:
        assert connection.autocommit is True
        assert connection.read_only is True

    failed_connection = _FakeConnection(_FakeCursor())
    monkeypatch.setattr(
        driver,
        "_import_psycopg",
        lambda: SimpleNamespace(connect=lambda **_kwargs: failed_connection),
    )
    with pytest.raises(driver.LexicalStorageError):
        with driver.open_lexical_connection(authority):
            raise _SqlErr("canceling statement due to statement timeout")
    assert failed_connection.closed is True

    scoped_connection = _FakeConnection(_FakeCursor())

    def connection_factory(_params: driver.LexicalConnectionParameters) -> _FakeConnection:
        return scoped_connection

    params = driver.LexicalConnectionParameters(
        host="127.0.0.1",
        port=5432,
        database="db",
        user="owner",
        password="secret",
    )
    with pytest.raises(driver.LexicalStorageError):
        with driver.lexical_connection_scope(
            params,
            connection_factory=connection_factory,
            read_only=True,
        ):
            raise _SqlErr("deadlock", "40001")
    assert scoped_connection.closed is True
