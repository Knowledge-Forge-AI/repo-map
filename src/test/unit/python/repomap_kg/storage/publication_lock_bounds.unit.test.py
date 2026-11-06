"""Publication lock protocol boundaries, without importing a database driver."""

from __future__ import annotations

from dataclasses import replace

import pytest

from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.staged_publication import execute_final_transaction
from common_lore_index.storage.staging_ownership import StageOwnershipError
from repomap_test_support.publication_fixtures import PublicationFixture


class _MergeReached(Exception):
    pass


class _DriverError(Exception):
    def __init__(self, sqlstate):
        self.sqlstate = sqlstate


class _Connection:
    def __init__(self, *, row=(True,), error=None):
        self.row = row
        self.error = error
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if len(self.calls) != 1:
            raise _MergeReached
        if self.error is not None:
            raise self.error
        return self

    def fetchone(self):
        return self.row


def _handoff(repository_id):
    return PublicationFixture(stage_id="lock-boundary", repository_id=repository_id).handoff


@pytest.mark.parametrize("repository_id", [1, 2**31 - 1, 2**31, 2**63 - 1])
def test_publication_lock_covers_bigint_without_changing_legacy_protocol(repository_id):
    connection = _Connection()
    with pytest.raises(_MergeReached):
        execute_final_transaction(connection, _handoff(repository_id))
    sql, params = connection.calls[0]
    if repository_id <= 2**31 - 1:
        assert sql == "SELECT pg_try_advisory_xact_lock(%s, %s)"
        assert params == (19042, repository_id)
    else:
        assert sql == (
            "SELECT TRUE FROM public.repositories WHERE id = %s "
            "FOR NO KEY UPDATE NOWAIT"
        )
        assert params == (repository_id,)


@pytest.mark.parametrize("repository_id", [True, False, 0, -1, 2**63, "7", None])
def test_invalid_publication_identity_fails_before_sql(repository_id):
    handoff = _handoff(1)
    invalid = replace(handoff, merge=replace(
        handoff.merge, owner=replace(handoff.merge.owner, repository_id=repository_id),
    ))
    connection = _Connection()
    with pytest.raises(StageOwnershipError, match="invalid stage owner"):
        execute_final_transaction(connection, invalid)
    assert connection.calls == []


@pytest.mark.parametrize("repository_id", [1, 2**31])
def test_busy_lock_never_reaches_merge(repository_id):
    connection = _Connection(row=(False,))
    with pytest.raises(StorageSchemaError, match="graph publication already active"):
        execute_final_transaction(connection, _handoff(repository_id))
    assert len(connection.calls) == 1


def test_missing_high_repository_never_becomes_a_successful_lock():
    connection = _Connection(row=None)
    with pytest.raises(StorageSchemaError, match="staged repository identity was not returned"):
        execute_final_transaction(connection, _handoff(2**31))
    assert len(connection.calls) == 1


def test_high_row_contention_has_only_the_sanitized_incumbent_category():
    connection = _Connection(error=_DriverError("55P03"))
    with pytest.raises(StorageSchemaError, match="^graph publication already active$") as caught:
        execute_final_transaction(connection, _handoff(2**31))
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    assert len(connection.calls) == 1


@pytest.mark.parametrize("sqlstate", ["40001", "42501", "XX000", None])
def test_other_high_row_failures_keep_driver_identity_and_causality(sqlstate):
    error = _DriverError(sqlstate)
    connection = _Connection(error=error)
    with pytest.raises(_DriverError) as caught:
        execute_final_transaction(connection, _handoff(2**31))
    assert caught.value is error
    assert len(connection.calls) == 1


def test_legacy_lock_does_not_translate_driver_errors():
    error = _DriverError("55P03")
    connection = _Connection(error=error)
    with pytest.raises(_DriverError) as caught:
        execute_final_transaction(connection, _handoff(1))
    assert caught.value is error
