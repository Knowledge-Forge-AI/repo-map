"""Safe no-clobber restore of one SQLite Local backup into an absent target (LOCAL7).

Validation happens before anything under the graph store is touched:

* the backup is a real directory holding exactly ``graph.sqlite3`` and
  ``manifest.json`` (no manifest: ``sqlite-backup-incomplete``);
* the manifest parses strictly, names a supported format and schema and binds
  the configured logical graph (no source root is needed or read);
* the database's byte length and SHA-256 equal the manifest's;
* the database opens read-only and immutable with the RepoMap application id,
  exactly the manifest's known schema version (an exact catalog prefix), the
  same graph binding, a passing ``integrity_check`` and exactly the manifest's
  accepted publication (or none for an unpublished one).

Every artifact refusal is ``sqlite-backup-artifact-invalid: <reason>``.

Install requires the target to be absent: any existing database file (valid,
empty or unrecognized) or leftover ``-wal``/``-shm``/``-journal`` sidecar is
``sqlite-restore-target-exists`` and is left untouched. There is no force,
deletion, quarantine or in-place replacement; replacing an existing or corrupt
target is a separate destructive recovery decision. Under the caller's
publisher lock the bytes are copied into a unique sibling temporary file while
being hashed (the copy must still equal the manifest), revalidated, fsynced,
hard-linked (never overwriting a race winner) and the store directory fsynced.
A failure after the link is not success: the installed file is the complete,
validated database, a rerun refuses as target-exists and readiness classifies
it normally. Success is returned only after a readback through the normal
read-only path shows the manifest's schema version and accepted publication.

Restore never migrates (LOCAL8). A v1 backup restores as an exact-behind v1
database: readiness reports ``schema-behind`` and ordinary reads and refreshes
refuse ``graph-database-schema-behind`` until ``ops sqlite-upgrade`` runs. A
current backup restores as current. Unknown, future or drifted schemas refuse.
"""

from __future__ import annotations

import errno
import hashlib
import os
import secrets
import stat
from contextlib import suppress
from pathlib import Path

from repomap_kg.storage.sqlite_local.backup import file_digest, inspect_sealed_database, owned_names
from repomap_kg.storage.sqlite_local.backup_manifest import (
    BACKUP_ARTIFACT_INVALID,
    BACKUP_INCOMPLETE,
    DATABASE_FILE,
    MANIFEST_FILE,
    MAX_MANIFEST_BYTES,
    RESTORE_TARGET_EXISTS,
    BackupManifest,
    BackupPublication,
    parse_manifest,
    read_publication,
)
from repomap_kg.storage.sqlite_local.connection import _NO_ATOMIC_INSTALL, read_transaction
from repomap_kg.storage.sqlite_local.durability import (
    fsync_descriptor,
    fsync_directory,
    fsync_directory_chain,
)
from repomap_kg.storage.sqlite_local.migrations import classify
from repomap_kg.storage.sqlite_local.schema import (
    DATABASE_UNAVAILABLE,
    LocalGraphBinding,
    LocalStoreError,
)

RESTORE_READBACK_MISMATCH = "sqlite-restore-readback-mismatch"
_CHUNK = 1024 * 1024


def _fault_point(name: str) -> None:
    """No-op seam; tests replace it to fail or pause at a named point."""
    return None


def _invalid(reason: str) -> LocalStoreError:
    return LocalStoreError(BACKUP_ARTIFACT_INVALID, reason)


def _read_manifest(path: Path) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise _invalid("manifest-unreadable") from None
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_MANIFEST_BYTES:
            raise _invalid("manifest-invalid")
        return os.read(descriptor, MAX_MANIFEST_BYTES + 1)
    finally:
        os.close(descriptor)


def verify_backup(backup: Path, binding: LocalGraphBinding) -> BackupManifest:
    """Fully validate one backup directory for ``binding``; touch nothing else."""
    try:
        if not stat.S_ISDIR(os.lstat(backup).st_mode):
            raise _invalid("not-a-directory")
        names = set(os.listdir(backup))
    except OSError:
        raise _invalid("unreadable") from None
    if MANIFEST_FILE not in names:
        raise LocalStoreError(BACKUP_INCOMPLETE, "no completed manifest")
    if names != {DATABASE_FILE, MANIFEST_FILE}:
        raise _invalid("unexpected-entry")
    manifest = parse_manifest(_read_manifest(backup / MANIFEST_FILE))
    if manifest.binding != binding:
        raise _invalid("graph-mismatch")
    try:
        size, digest = file_digest(backup / DATABASE_FILE)
    except (OSError, LocalStoreError):
        raise _invalid("database-unreadable") from None
    if size != manifest.database_bytes:
        raise _invalid("database-length-mismatch")
    if digest != manifest.database_sha256:
        raise _invalid("database-digest-mismatch")
    _require_database(backup / DATABASE_FILE, binding, manifest)
    return manifest


def _require_database(path: Path, binding: LocalGraphBinding, manifest: BackupManifest) -> None:
    try:
        version, publication = inspect_sealed_database(path, binding)
    except LocalStoreError as error:
        raise _invalid(error.code) from None
    except OSError:
        raise _invalid("database-unreadable") from None
    if version != manifest.schema_version:
        raise _invalid("schema-mismatch")
    if publication != manifest.publication:
        raise _invalid("publication-mismatch")


def require_absent_target(target: Path) -> None:
    """Refuse any existing target file or sidecar; never touch it."""
    if os.path.lexists(target):
        raise LocalStoreError(RESTORE_TARGET_EXISTS, "a graph database already exists")
    if any(os.path.lexists(name) for name in owned_names(target)[1:]):
        raise LocalStoreError(RESTORE_TARGET_EXISTS, "database sidecars present")


def _copy(source: Path, temporary: Path) -> tuple[int, str]:
    reader = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        writer = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            digest = hashlib.sha256()
            size = 0
            while chunk := os.read(reader, _CHUNK):
                digest.update(chunk)
                size += len(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(writer, view)
                    if written <= 0:
                        raise OSError(errno.EIO, "short write")
                    view = view[written:]
            fsync_descriptor(writer)
        finally:
            os.close(writer)
    finally:
        os.close(reader)
    return size, digest.hexdigest()


def install_backup(
    backup: Path,
    manifest: BackupManifest,
    target: Path,
    binding: LocalGraphBinding,
    *,
    durable_ancestors: int,
) -> BackupPublication | None:
    """Install a verified backup at the absent ``target``; the caller holds its lock."""
    require_absent_target(target)
    fsync_directory_chain(target.parent, durable_ancestors)
    temporary = target.with_name(f".{target.name}.restore-{secrets.token_hex(8)}")
    installed = False
    try:
        if _copy(backup / DATABASE_FILE, temporary) != (manifest.database_bytes, manifest.database_sha256):
            raise _invalid("database-changed-during-restore")
        _require_database(temporary, binding, manifest)
        _fault_point("restore:before-install")
        try:
            os.link(temporary, target)
        except FileExistsError:
            raise LocalStoreError(RESTORE_TARGET_EXISTS, "a graph database already exists") from None
        except OSError as error:
            if error.errno in _NO_ATOMIC_INSTALL:
                raise LocalStoreError(
                    DATABASE_UNAVAILABLE, "graph store does not support atomic no-clobber install"
                ) from None
            raise
        installed = True
        _fault_point("restore:installed")
        fsync_directory(target.parent)
        _fault_point("restore:after-install")
    finally:
        # Only this attempt's names; after install the temporary name is a
        # second link to the installed database, so removing it is best-effort.
        for owned in owned_names(temporary):
            with suppress(OSError):
                owned.unlink()
        if installed:
            with suppress(OSError, LocalStoreError):
                fsync_directory(target.parent)
    with read_transaction(target, binding, accept_behind=True) as reader:
        version = classify(reader).version
        restored = read_publication(reader)
    if (version, restored) != (manifest.schema_version, manifest.publication):
        raise LocalStoreError(RESTORE_READBACK_MISMATCH)
    return restored


__all__ = (
    "RESTORE_READBACK_MISMATCH",
    "install_backup",
    "require_absent_target",
    "verify_backup",
)
