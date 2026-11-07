"""Owned PostgreSQL lifecycle locks and leases for cloe_lexical builds."""

from __future__ import annotations

from typing import Any

from common_lore_index.storage.lexical_driver import LexicalStorageError

LIFECYCLE_ADVISORY_NAMESPACE = "cloe_lexical:lifecycle:v1"
LEXICAL_BUILD_LEASE_SECONDS = 120


def acquire_repository_lifecycle_lock(connection: Any, repository_id: int) -> None:
    """Acquire the shared non-blocking per-repository lifecycle lock."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_xact_lock(pg_catalog.hashtextextended(%s, %s::bigint))",
            (LIFECYCLE_ADVISORY_NAMESPACE, repository_id),
        )
        row = cursor.fetchone()
    if row is None or len(row) != 1 or row[0] is not True:
        raise LexicalStorageError(
            "cloe_lexical_competing_builder_in_progress",
            "repository lexical lifecycle lock is held by another operation",
        )


def acquire_revoke_lifecycle_locks(
    connection: Any, repository_id: int | None
) -> None:
    """Lock one repository, or every current repository in stable order."""
    if repository_id is not None:
        acquire_repository_lifecycle_lock(connection, repository_id)
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM public.repositories ORDER BY id")
        repository_ids = tuple(int(row[0]) for row in cursor.fetchall())
    for current_id in repository_ids:
        acquire_repository_lifecycle_lock(connection, current_id)


def refresh_lexical_build_lease(
    connection: Any,
    *,
    repository_id: int,
    lexical_generation_id: str,
    builder_owner_id: str,
) -> None:
    """Fence and refresh one owned building generation in the current batch transaction."""
    acquire_repository_lifecycle_lock(connection, repository_id)
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE cloe_lexical.generations
            SET lease_expires_at = clock_timestamp() + interval '{LEXICAL_BUILD_LEASE_SECONDS} seconds'
            WHERE repository_id = %s
              AND lexical_generation_id = %s
              AND builder_owner_id = %s
              AND state = 'building'
              AND lease_expires_at > clock_timestamp()
            RETURNING lexical_generation_id
            """,
            (
                repository_id,
                lexical_generation_id,
                builder_owner_id,
            ),
        )
        if cursor.fetchone() is None:
            raise LexicalStorageError(
                "cloe_lexical_build_lease_lost",
                "owned lexical build lease is no longer active",
            )


def cleanup_owned_lexical_generation(
    connection: Any,
    *,
    repository_id: int,
    lexical_generation_id: str,
    builder_owner_id: str,
) -> None:
    """Purge only an owned non-published generation after an uncertain build."""
    acquire_repository_lifecycle_lock(connection, repository_id)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT state, builder_owner_id
            FROM cloe_lexical.generations
            WHERE repository_id = %s AND lexical_generation_id = %s
            FOR UPDATE
            """,
            (repository_id, lexical_generation_id),
        )
        row = cursor.fetchone()
        if row is None:
            return
        state, owner = row[:2]
        if state == "published":
            raise LexicalStorageError(
                "cloe_lexical_cleanup_published_generation",
                "uncertain lexical build outcome reached a published generation",
            )
        if state == "revoked" or (state == "invalidated" and owner is None):
            return
        if owner != builder_owner_id or state not in {"building", "invalidated"}:
            raise LexicalStorageError(
                "cloe_lexical_cleanup_owner_mismatch",
                "lexical build cleanup does not own the generation",
            )
        cursor.execute(
            """
            DELETE FROM cloe_lexical.authority
            WHERE repository_id = %s AND lexical_generation_id = %s
            """,
            (repository_id, lexical_generation_id),
        )
        for table in ("chunks", "documents", "omissions"):
            cursor.execute(
                f"DELETE FROM cloe_lexical.{table} WHERE repository_id = %s AND lexical_generation_id = %s",
                (repository_id, lexical_generation_id),
            )
        cursor.execute(
            """
            UPDATE cloe_lexical.generations
            SET state = 'invalidated',
                revoked_at = clock_timestamp(),
                revocation_reason = 'build_failed_rollback',
                builder_owner_id = NULL,
                lease_expires_at = NULL
            WHERE repository_id = %s
              AND lexical_generation_id = %s
              AND builder_owner_id = %s
              AND state IN ('building', 'invalidated')
            """,
            (repository_id, lexical_generation_id, builder_owner_id),
        )
        if cursor.rowcount != 1:
            raise LexicalStorageError(
                "cloe_lexical_cleanup_owner_mismatch",
                "lexical build cleanup lost its owned generation",
            )
    connection.commit()


def purge_superseded_published_rows(
    cursor: Any,
    *,
    repository_id: int,
    lexical_generation_id: str,
) -> None:
    """Remove body rows only for older published generations after activation."""
    for table in ("chunks", "documents", "omissions"):
        cursor.execute(
            f"""
            DELETE FROM cloe_lexical.{table} AS doomed
            WHERE doomed.repository_id = %s
              AND doomed.lexical_generation_id <> %s
              AND EXISTS (
                  SELECT 1
                  FROM cloe_lexical.generations old_generation
                  WHERE old_generation.repository_id = doomed.repository_id
                    AND old_generation.lexical_generation_id = doomed.lexical_generation_id
                    AND old_generation.state = 'published'
              )
            """,
            (repository_id, lexical_generation_id),
        )


__all__ = [
    "LEXICAL_BUILD_LEASE_SECONDS",
    "LIFECYCLE_ADVISORY_NAMESPACE",
    "acquire_revoke_lifecycle_locks",
    "acquire_repository_lifecycle_lock",
    "cleanup_owned_lexical_generation",
    "purge_superseded_published_rows",
    "refresh_lexical_build_lease",
]
