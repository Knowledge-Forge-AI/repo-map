"""Explicit, backup-first forward schema migration of one graph database (LOCAL8).

The caller holds the graph's :func:`~.connection.publisher_lock` for the whole
call, so no publisher, refresh, backup, restore or second upgrade can
interleave. In order:

1. Under the lock the live database is classified and its accepted
   publication read (exact-current or exact-behind only: drift, future,
   foreign and graph-mismatch refuse here, before any output is touched).
2. Exact-current: ``already-current``. No backup is written and the output is
   neither inspected nor created. This is also how a rerun reconciles an
   upgrade whose post-COMMIT outcome was unknown.
3. Exact-behind: the output must be absent or an empty directory; a LOCAL7
   backup of the *unchanged* database is written (its manifest records the
   old version) and then independently re-verified from disk (manifest, byte
   length, SHA-256, integrity, schema version and publication). Nothing is
   migrated unless that verification equals the live read.
4. One ``BEGIN IMMEDIATE`` transaction re-checks the state, runs each pending
   catalog migration's SQL and ledger row, sets ``user_version`` and requires
   the result to classify exact-current before one COMMIT.
5. A fresh exact-current read must show the unchanged accepted publication.

Commit outcome, as in the publisher (LOCAL3): before COMMIT is attempted
every exception rolls back, is bounded and is tagged ``is_not_committed``; the
live database is still the exact old version and the verified backup is kept.
Once COMMIT is attempted, success needs the positive readback of step 5. An
ordinary error or a failed readback is
``graph-migration-reconciliation-required`` tagged ``is_commit_unknown``;
nothing is restored or rolled back over a possibly committed migration. A
process-control exception propagates tagged the same way. The backup is never
deleted, and there is no downgrade.
"""

from __future__ import annotations

import sqlite3
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NoReturn

from repomap_kg.storage.sqlite_local.backup import check_backup_output, write_backup
from repomap_kg.storage.sqlite_local.backup_manifest import (
    BackupManifest,
    BackupPublication,
    read_publication,
)
from repomap_kg.storage.sqlite_local.connection import (
    classify_write_error,
    open_writer,
    read_transaction,
)
from repomap_kg.storage.sqlite_local.migrations import (
    SchemaState,
    classify,
    current_version,
    pending_migrations,
    record_migration,
)
from repomap_kg.storage.sqlite_local.publisher import COMMIT_UNKNOWN, NOT_COMMITTED
from repomap_kg.storage.sqlite_local.restore import verify_backup
from repomap_kg.storage.sqlite_local.schema import (
    GENERATION_ADVANCED,
    MIGRATION_RECONCILIATION_REQUIRED,
    PUBLICATION_INTERNAL_ERROR,
    PUBLICATION_REJECTED,
    SCHEMA_DRIFT,
    LocalGraphBinding,
    LocalStoreError,
)

UPGRADE_BACKUP_UNVERIFIED = "sqlite-upgrade-backup-unverified"
UPGRADE_FAILED = "sqlite-upgrade-failed"


def _fault_point(name: str) -> None:
    """No-op seam; tests replace it to fail or pause at a named point."""
    return None


@dataclass(frozen=True)
class UpgradeResult:
    result: Literal["upgraded", "already-current"]
    from_version: int
    schema_version: int
    publication: BackupPublication | None
    backup: BackupManifest | None


def upgrade_graph_database(
    path: Path,
    binding: LocalGraphBinding,
    output: Path,
    *,
    created_at: str,
    applied_at: str,
) -> UpgradeResult:
    """Upgrade an exact-behind database to exact-current behind a verified backup."""
    with read_transaction(path, binding, accept_behind=True) as reader:
        before = classify(reader)
        publication = read_publication(reader)
    if before.kind == "current":
        return UpgradeResult("already-current", before.version, before.version, publication, None)
    check_backup_output(output)
    manifest = write_backup(path, binding, output, created_at=created_at)
    _require_verified(output, binding, manifest, before, publication)
    _apply(path, binding, before, publication, applied_at=applied_at)
    return UpgradeResult("upgraded", before.version, current_version(), publication, manifest)


def _require_verified(
    output: Path,
    binding: LocalGraphBinding,
    manifest: BackupManifest,
    before: SchemaState,
    publication: BackupPublication | None,
) -> None:
    """The rollback artifact, re-read from disk, must be exactly the live database's state."""
    try:
        verified = verify_backup(output, binding)
    except LocalStoreError as error:
        raise LocalStoreError(UPGRADE_BACKUP_UNVERIFIED, error.code) from None
    if (verified, verified.schema_version, verified.publication) != (
        manifest, before.version, publication
    ):
        raise LocalStoreError(UPGRADE_BACKUP_UNVERIFIED, "backup does not match the live database")


def _apply(
    path: Path,
    binding: LocalGraphBinding,
    before: SchemaState,
    publication: BackupPublication | None,
    *,
    applied_at: str,
) -> None:
    connection: sqlite3.Connection | None = None
    commit_attempted = False
    try:
        connection = open_writer(path, binding, accept_behind=True)
        connection.execute("BEGIN IMMEDIATE")
        if classify(connection) != before or read_publication(connection) != publication:
            raise LocalStoreError(GENERATION_ADVANCED, "graph changed during upgrade")
        for item in pending_migrations(before.version):
            connection.executescript(item.sql)
            _fault_point("upgrade:ddl-applied")
            record_migration(connection, item, applied_at=applied_at)
        connection.execute(f"PRAGMA user_version = {current_version()}")
        if classify(connection) != SchemaState("current", current_version()):
            raise LocalStoreError(SCHEMA_DRIFT, "upgraded schema does not match the catalog")
        _fault_point("upgrade:before-commit")
        commit_attempted = True
        connection.execute("COMMIT")
        _fault_point("upgrade:after-commit")
    except BaseException as error:
        if connection is not None and connection.in_transaction:
            with suppress(sqlite3.Error):
                connection.execute("ROLLBACK")
        if not commit_attempted or not isinstance(error, Exception):
            _raise_tagged(error, commit_attempted=commit_attempted)
    finally:
        # Cleanup only, before any readback: the outcome is decided below.
        if connection is not None:
            with suppress(sqlite3.Error):
                connection.close()
    _confirm(path, binding, publication)


def _confirm(
    path: Path, binding: LocalGraphBinding, publication: BackupPublication | None
) -> None:
    """Success after an attempted COMMIT needs a positive exact-current readback."""
    try:
        with read_transaction(path, binding) as reader:
            confirmed = read_publication(reader) == publication
    except Exception:
        confirmed = False  # a failed readback proves nothing either way
    except BaseException as interrupt:
        _raise_tagged(interrupt, commit_attempted=True)
    if not confirmed:
        unknown = LocalStoreError(MIGRATION_RECONCILIATION_REQUIRED, "schema upgrade outcome unknown")
        setattr(unknown, COMMIT_UNKNOWN, True)
        raise unknown


def _raise_tagged(error: BaseException, *, commit_attempted: bool) -> NoReturn:
    """Raise ``error`` (bounded if it is a raw ``sqlite3`` error) with its outcome tag."""
    tagged: BaseException = error
    if isinstance(error, sqlite3.Error):
        tagged = classify_write_error(error)
        if tagged.code in (PUBLICATION_REJECTED, PUBLICATION_INTERNAL_ERROR):
            tagged = LocalStoreError(UPGRADE_FAILED, "the database refused the schema change")
    setattr(tagged, COMMIT_UNKNOWN if commit_attempted else NOT_COMMITTED, True)
    if tagged is error:
        raise error
    raise tagged from None


__all__ = (
    "UPGRADE_BACKUP_UNVERIFIED",
    "UPGRADE_FAILED",
    "UpgradeResult",
    "upgrade_graph_database",
)
