"""Transaction-owned exclusion for staged publication over BIGINT identities."""

from __future__ import annotations

from typing import Any

from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.sql_core import sql_literal
from common_lore_index.storage.staging_ownership import StageOwnershipError


_INT32_MAX = 2**31 - 1
_BIGINT_MAX = 2**63 - 1
_BUSY = "graph publication already active"
_ROW_LOCK = "FOR NO KEY UPDATE NOWAIT"


class PublicationContentionError(StorageSchemaError):
    """Internal, sanitized publication/admission contention refusal."""


def _lock_row(connection: Any, sql: str, values: tuple[object, ...]) -> Any:
    try:
        return connection.execute(sql, values).fetchone()
    except Exception as error:
        if getattr(error, "sqlstate", None) == "55P03":
            raise PublicationContentionError(_BUSY) from None
        raise


def acquire_publication_lock(
    connection: Any, repository_id: int, *, legacy_class: int,
) -> None:
    if (
        not isinstance(repository_id, int)
        or isinstance(repository_id, bool)
        or not 0 < repository_id <= _BIGINT_MAX
    ):
        raise StageOwnershipError("invalid stage owner")
    if repository_id <= _INT32_MAX:
        row = connection.execute(
            "SELECT pg_try_advisory_xact_lock(%s, %s)",
            (legacy_class, repository_id),
        ).fetchone()
    else:
        row = _lock_row(
            connection,
            "SELECT TRUE FROM public.repositories WHERE id = %s " + _ROW_LOCK,
            (repository_id,),
        )
        if row is None:
            raise StorageSchemaError("staged repository identity was not returned")
    if row is None or not row or row[0] is not True:
        raise PublicationContentionError(_BUSY)


def guard_existing_large_repository(
    connection: Any, root_path: str, repository_identity: str | None,
) -> None:
    """Refuse an existing high-ID row conflict before its admission upsert."""
    column, value = _admission_match(root_path, repository_identity)
    row = _lock_row(
        connection,
        f"SELECT TRUE FROM public.repositories WHERE {column} = %s "
        f"AND id > {_INT32_MAX} {_ROW_LOCK}",
        (value,),
    )
    if row is not None and (not row or row[0] is not True):
        raise StorageSchemaError("staged repository identity was not returned")


def repository_admission_guard_sql(
    root_path: str, repository_identity: str | None,
) -> str:
    """Render the same admission guard without a psql result-binding row."""
    column, value = _admission_match(root_path, repository_identity)
    body = f"""BEGIN
    PERFORM 1 FROM public.repositories
    WHERE {column} = {sql_literal(value)} AND id > {_INT32_MAX}
    {_ROW_LOCK};
EXCEPTION WHEN lock_not_available THEN
    RAISE EXCEPTION '{_BUSY}' USING ERRCODE = '55P03';
END;"""
    return "DO " + sql_literal(body) + ";"


def _admission_match(root_path: str, repository_identity: str | None) -> tuple[str, str]:
    if repository_identity is None:
        return "root_path", root_path
    return "repository_identity", repository_identity
