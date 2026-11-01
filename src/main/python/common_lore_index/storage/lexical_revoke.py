"""Revocation and row-purge operations for PostgreSQL cloe_lexical generations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common_lore_index.storage.lexical_driver import (
    LexicalStorageError,
    sanitize_driver_exception,
)
from common_lore_index.storage.lexical_build_lease import acquire_revoke_lifecycle_locks
from common_lore_index.storage.lexical_lifecycle import REVOKE_LIMITED_ROLES_SQL

RESOLVE_REPO_ID_SQL = """
SELECT r.id
FROM public.repositories r
WHERE (%(repository_identity)s::text IS NOT NULL AND r.repository_identity = %(repository_identity)s)
   OR (r.repository_identity IS NULL AND %(repository_name)s::text IS NOT NULL AND r.name = %(repository_name)s)
   OR (r.repository_identity IS NULL AND %(root_path)s::text IS NOT NULL AND r.root_path = %(root_path)s)
ORDER BY
    (r.repository_identity = %(repository_identity)s) DESC NULLS LAST,
    (r.name = %(repository_name)s) DESC NULLS LAST,
    (r.root_path = %(root_path)s) DESC NULLS LAST,
    r.id DESC
LIMIT 1
"""


@dataclass(frozen=True)
class LexicalRevokeSummary:
    """Public-safe summary of a cloe_lexical revocation and optional row purge."""

    repository_id: int | None
    revoked_generation_ids: tuple[str, ...]
    authority_rows_removed: int
    purged_document_count: int
    purged_chunk_count: int
    purged_omission_count: int
    reason: str
    purge_rows: bool
    graph_id: str | None = None

    @property
    def revoked_generation_count(self) -> int:
        return len(self.revoked_generation_ids)

    @property
    def purged_authority_count(self) -> int:
        return self.authority_rows_removed

    def to_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "repository_id": self.repository_id,
            "revoked_generation_ids": list(self.revoked_generation_ids),
            "revoked_generation_count": self.revoked_generation_count,
            "authority_rows_removed": self.authority_rows_removed,
            "purged_authority_count": self.purged_authority_count,
            "purged_document_count": self.purged_document_count,
            "purged_chunk_count": self.purged_chunk_count,
            "purged_omission_count": self.purged_omission_count,
            "reason": self.reason,
            "purge_rows": self.purge_rows,
        }


LexicalRevocationOutcome = LexicalRevokeSummary


def revoke_lexical_generations(
    connection: Any,
    *,
    repository_id: int | None = None,
    repository_identity: str | None = None,
    repository_name: str | None = None,
    root_path: str | None = None,
    reason: str = "operator_revoked",
    purge_rows: bool = True,
    dry_run: bool = False,
) -> LexicalRevokeSummary:
    """Revoke active/building cloe_lexical generations and optionally purge body rows."""
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise LexicalStorageError(
            "lexical_revoke_missing_reason",
            "revocation reason must be a non-empty string",
        )
    try:
        with connection.cursor() as cursor:
            resolved_repo_id = repository_id
            if resolved_repo_id is None and any(
                val is not None for val in (repository_identity, repository_name, root_path)
            ):
                cursor.execute(
                    RESOLVE_REPO_ID_SQL,
                    {
                        "repository_identity": repository_identity,
                        "repository_name": repository_name,
                        "root_path": root_path,
                    },
                )
                row = cursor.fetchone()
                if row is None:
                    return LexicalRevokeSummary(
                        repository_id=None,
                        revoked_generation_ids=(),
                        authority_rows_removed=0,
                        purged_document_count=0,
                        purged_chunk_count=0,
                        purged_omission_count=0,
                        reason=clean_reason,
                        purge_rows=purge_rows,
                    )
                resolved_repo_id = int(row[0])

            scope_clause = "WHERE repository_id = %s" if resolved_repo_id is not None else ""
            scope_params: tuple[Any, ...] = (
                (resolved_repo_id,) if resolved_repo_id is not None else ()
            )
            acquire_revoke_lifecycle_locks(connection, resolved_repo_id)

            if dry_run:
                cursor.execute(
                    f"SELECT count(*)::int FROM cloe_lexical.authority {scope_clause}",
                    scope_params,
                )
                authority_removed = int((cursor.fetchone() or (0,))[0])
                cursor.execute(
                    f"SELECT count(*)::int FROM cloe_lexical.chunks {scope_clause}",
                    scope_params,
                )
                purged_chunks = int((cursor.fetchone() or (0,))[0])
                cursor.execute(
                    f"SELECT count(*)::int FROM cloe_lexical.documents {scope_clause}",
                    scope_params,
                )
                purged_docs = int((cursor.fetchone() or (0,))[0])
                cursor.execute(
                    f"SELECT count(*)::int FROM cloe_lexical.omissions {scope_clause}",
                    scope_params,
                )
                purged_omissions = int((cursor.fetchone() or (0,))[0])
                gen_where = (
                    "WHERE repository_id = %s AND state <> 'revoked'"
                    if resolved_repo_id is not None
                    else "WHERE state <> 'revoked'"
                )
                cursor.execute(
                    f"SELECT lexical_generation_id FROM cloe_lexical.generations {gen_where}",
                    scope_params,
                )
                revoked_ids = tuple(sorted(str(r[0]) for r in cursor.fetchall()))
                return LexicalRevokeSummary(
                    repository_id=resolved_repo_id,
                    revoked_generation_ids=revoked_ids,
                    authority_rows_removed=authority_removed,
                    purged_document_count=purged_docs,
                    purged_chunk_count=purged_chunks,
                    purged_omission_count=purged_omissions,
                    reason=clean_reason,
                    purge_rows=False,
                )

            cursor.execute(
                f"DELETE FROM cloe_lexical.authority {scope_clause}",
                scope_params,
            )
            authority_removed = int(cursor.rowcount or 0)

            purged_chunks = 0
            purged_docs = 0
            purged_omissions = 0
            if purge_rows:
                cursor.execute(
                    f"DELETE FROM cloe_lexical.chunks {scope_clause}",
                    scope_params,
                )
                purged_chunks = int(cursor.rowcount or 0)
                cursor.execute(
                    f"DELETE FROM cloe_lexical.documents {scope_clause}",
                    scope_params,
                )
                purged_docs = int(cursor.rowcount or 0)
                cursor.execute(
                    f"DELETE FROM cloe_lexical.omissions {scope_clause}",
                    scope_params,
                )
                purged_omissions = int(cursor.rowcount or 0)

            update_where = (
                "WHERE repository_id = %s AND state <> 'revoked'"
                if resolved_repo_id is not None
                else "WHERE state <> 'revoked'"
            )
            update_params = (
                (clean_reason, resolved_repo_id)
                if resolved_repo_id is not None
                else (clean_reason,)
            )
            cursor.execute(
                f"""
                UPDATE cloe_lexical.generations
                SET state = 'revoked',
                    revoked_at = clock_timestamp(),
                    revocation_reason = %s,
                    builder_owner_id = NULL,
                    lease_expires_at = NULL
                {update_where}
                RETURNING lexical_generation_id
                """,
                update_params,
            )
            revoked_ids = tuple(sorted(str(r[0]) for r in cursor.fetchall()))
            cursor.execute(REVOKE_LIMITED_ROLES_SQL)
    except Exception as error:
        raise sanitize_driver_exception(error, operation="lexical_revoke") from None

    return LexicalRevokeSummary(
        repository_id=resolved_repo_id,
        revoked_generation_ids=revoked_ids,
        authority_rows_removed=authority_removed,
        purged_document_count=purged_docs,
        purged_chunk_count=purged_chunks,
        purged_omission_count=purged_omissions,
        reason=clean_reason,
        purge_rows=purge_rows,
    )


__all__ = [
    "LexicalRevocationOutcome",
    "LexicalRevokeSummary",
    "RESOLVE_REPO_ID_SQL",
    "revoke_lexical_generations",
]
