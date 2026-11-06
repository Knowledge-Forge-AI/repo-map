"""Existing high-ID admission guards preserve metadata and error boundaries."""

from __future__ import annotations

import pytest

from common_lore_index.storage._repository_publication_lock import (
    guard_existing_large_repository,
    repository_admission_guard_sql,
)
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.sql_load import repository_run_prefix_sql


class _DriverError(Exception):
    sqlstate = "55P03"


class _Database:
    def __init__(self, row=None, error=None):
        self.row = row
        self.error = error
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        if self.error is not None:
            raise self.error
        return self

    def fetchone(self):
        return self.row


@pytest.mark.parametrize("identity", [None, "repo1:fixture"])
@pytest.mark.parametrize("row", [None, (True,)])
def test_admission_guards_only_existing_matching_high_rows(identity, row):
    database = _Database(row=row)
    guard_existing_large_repository(database, "fixture-root", identity)
    sql, params = database.calls[0]
    column = "root_path" if identity is None else "repository_identity"
    assert f"WHERE {column} = %s AND id > 2147483647 FOR NO KEY UPDATE NOWAIT" in sql
    assert " OR " not in sql
    assert params == (("fixture-root" if identity is None else identity),)


@pytest.mark.parametrize("row", [(), (False,), (1,)])
def test_malformed_admission_response_fails_closed(row):
    with pytest.raises(StorageSchemaError, match="staged repository identity was not returned"):
        guard_existing_large_repository(_Database(row=row), "fixture-root", None)


def test_busy_admission_has_sanitized_error_without_driver_cause():
    with pytest.raises(StorageSchemaError, match="^graph publication already active$") as caught:
        guard_existing_large_repository(_Database(error=_DriverError("private diagnostic")), "fixture-root", None)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__


def test_unrelated_admission_driver_error_retains_identity():
    original = RuntimeError("fixture failure")
    with pytest.raises(RuntimeError) as caught:
        guard_existing_large_repository(_Database(error=original), "fixture-root", None)
    assert caught.value is original


@pytest.mark.parametrize("identity", [None, "repo1:fixture"])
def test_sql_admission_guard_is_before_upsert_and_emits_no_binding_row(identity):
    prefix = repository_run_prefix_sql(
        repository_name="fixture", root_path="fixture'root", git_commit=None,
        run_status="running", repository_identity=identity,
    )
    assert prefix[0] == "BEGIN;"
    guard = repository_admission_guard_sql("fixture'root", identity)
    assert prefix.index(guard) < next(i for i, sql in enumerate(prefix) if sql.startswith("INSERT INTO repositories"))
    assert "PERFORM 1 FROM public.repositories" in guard
    assert "EXCEPTION WHEN lock_not_available" in guard
    assert "RAISE EXCEPTION ''graph publication already active'' USING ERRCODE = ''55P03''" in guard
    assert "SELECT " not in guard and "RETURNING " not in guard
    assert "FOR NO KEY UPDATE NOWAIT" in guard
    assert prefix[prefix.index("\\gset repo_") - 1].startswith("INSERT INTO repositories")
    if identity is None:
        assert "root_path = ''fixture''''root''" in guard
    else:
        assert "repository_identity = ''repo1:fixture''" in guard
        assert "fixture''''root" not in guard
