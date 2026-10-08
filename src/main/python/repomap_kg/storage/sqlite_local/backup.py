"""Consistent online backup of one SQLite Local graph database (LOCAL7).

The caller holds the graph's :func:`~.connection.publisher_lock`, so no
publisher can move the accepted marker while the snapshot is taken. Inside one
read-only committed-snapshot transaction on the live database the accepted
publication is read and SQLite's online backup API copies every committed page,
WAL-resident frames included, in a single step. The live main file is never
copied raw and never written.

Materialization happens only inside the output directory:

1. a uniquely named temporary database (``O_EXCL``) receives the snapshot, is
   checkpointed, closed, made sidecar-free and fsynced;
2. it is reopened read-only and immutable and validated (header WAL mark,
   application id, schema, graph binding, ``integrity_check``) and its schema
   version and accepted publication must equal the ones read from the live
   snapshot;
3. its exact bytes are hashed;
4. it is hard-linked (no clobber) to ``graph.sqlite3``, the temporary name is
   removed and the directory fsynced;
5. the manifest is written to a temporary name, fsynced, hard-linked to
   ``manifest.json`` and the directory fsynced. Only then is success returned.

Any failure (including a catchable interrupt) removes only this attempt's own
names (the final names only when they are still this attempt's inodes) and an
output directory this attempt created, so no completed manifest claims success.

An exact-behind database (a known older catalog version, LOCAL8) is backed up
as it is: the manifest records its exact version, so the artifact is the
rollback point ``ops sqlite-upgrade`` creates before any schema change.
"""

from __future__ import annotations

import errno
import hashlib
import os
import secrets
import sqlite3
import stat
from contextlib import suppress
from pathlib import Path

from repomap_kg.storage.sqlite_local.backup_manifest import (
    BACKUP_OUTPUT_INVALID,
    BACKUP_TARGET_EXISTS,
    DATABASE_FILE,
    MANIFEST_FILE,
    BackupManifest,
    BackupPublication,
    read_publication,
)
from repomap_kg.storage.sqlite_local.connection import (
    _NO_ATOMIC_INSTALL,
    READ_BUSY_TIMEOUT_SECONDS,
    graph_database_uri,
    read_transaction,
    seal_database_file,
    sidecar_paths,
)
from repomap_kg.storage.sqlite_local.durability import fsync_descriptor, fsync_directory
from repomap_kg.storage.sqlite_local.migrations import classify, require_open_state
from repomap_kg.storage.sqlite_local.schema import (
    DATABASE_UNAVAILABLE,
    GENERATION_ADVANCED,
    UNRECOGNIZED,
    LocalGraphBinding,
    LocalStoreError,
    require_binding,
    require_runtime_support,
)

_HEADER = b"SQLite format 3\x00"
_CHUNK = 1024 * 1024


def _fault_point(name: str) -> None:
    """No-op seam; tests replace it to fail or pause at a named point."""
    return None


def owned_names(path: Path) -> tuple[Path, ...]:
    """A temporary database and every sidecar SQLite may create beside it."""
    return (path, *sidecar_paths(path), path.with_name(path.name + "-journal"))


def file_digest(path: Path) -> tuple[int, str]:
    """Byte length and SHA-256 of one regular file, read through one descriptor."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise LocalStoreError(UNRECOGNIZED)
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(descriptor, _CHUNK):
            digest.update(chunk)
            size += len(chunk)
    finally:
        os.close(descriptor)
    return size, digest.hexdigest()


def inspect_sealed_database(
    path: Path, binding: LocalGraphBinding
) -> tuple[int, BackupPublication | None]:
    """Validate a closed, sidecar-free database; return its schema version and publication.

    The schema must be exact-current or exact-behind (a known catalog prefix).

    Opens ``mode=ro&immutable=1``: correct only for a file no connection is
    writing (a sealed backup or restore temporary). It creates no sidecars.
    """
    require_runtime_support()
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        header = os.read(descriptor, 20)
    finally:
        os.close(descriptor)
    if len(header) < 20 or header[:16] != _HEADER:
        raise LocalStoreError(UNRECOGNIZED)
    if header[18:20] != b"\x02\x02":
        raise LocalStoreError(UNRECOGNIZED, "database is not WAL-marked")
    try:
        connection = sqlite3.connect(
            graph_database_uri(path, read_only=True) + "&immutable=1",
            uri=True,
            autocommit=True,
            timeout=READ_BUSY_TIMEOUT_SECONDS,
        )
    except sqlite3.Error:
        raise LocalStoreError(UNRECOGNIZED) from None
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        state = require_open_state(classify(connection), accept_behind=True)
        require_binding(connection, binding)
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise LocalStoreError(UNRECOGNIZED, "integrity check failed")
        publication = read_publication(connection)
        connection.execute("COMMIT")
    except sqlite3.Error:
        raise LocalStoreError(UNRECOGNIZED) from None
    finally:
        connection.close()
    return state.version, publication


def check_backup_output(output: Path) -> None:
    """Refuse an output that is not absent or an empty real directory."""
    try:
        details = os.lstat(output)
    except FileNotFoundError:
        if not output.parent.is_dir():
            raise LocalStoreError(BACKUP_OUTPUT_INVALID, "output parent is not a directory") from None
        return
    if not stat.S_ISDIR(details.st_mode):
        raise LocalStoreError(BACKUP_OUTPUT_INVALID, "output is not a directory")
    if os.listdir(output):
        raise LocalStoreError(BACKUP_TARGET_EXISTS, "output directory is not empty")


def _snapshot(
    source: Path, binding: LocalGraphBinding, temporary: Path
) -> tuple[int, BackupPublication | None]:
    with read_transaction(source, binding, accept_behind=True) as reader:
        version = classify(reader).version
        publication = read_publication(reader)
        try:
            destination = sqlite3.connect(
                graph_database_uri(temporary, read_only=False), uri=True, autocommit=True
            )
        except sqlite3.Error:
            raise LocalStoreError(DATABASE_UNAVAILABLE, "backup database cannot be opened") from None
        try:
            reader.backup(destination, pages=-1)
            mode = destination.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            checkpoint = destination.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if str(mode).lower() != "wal" or tuple(checkpoint) != (0, 0, 0):
                raise LocalStoreError(DATABASE_UNAVAILABLE, "backup checkpoint is incomplete")
        except sqlite3.Error:
            raise LocalStoreError(DATABASE_UNAVAILABLE, "backup snapshot failed") from None
        finally:
            destination.close()
    return version, publication


def _link(source: Path, target: Path) -> tuple[int, int]:
    try:
        os.link(source, target)
    except FileExistsError:
        raise LocalStoreError(BACKUP_TARGET_EXISTS, "output directory is not empty") from None
    except OSError as error:
        if error.errno in _NO_ATOMIC_INSTALL:
            raise LocalStoreError(DATABASE_UNAVAILABLE, "backup store does not support atomic no-clobber install") from None
        raise
    details = os.lstat(target)
    return details.st_dev, details.st_ino


def _write_new(path: Path, encoded: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError(errno.EIO, "short write")
            view = view[written:]
        fsync_descriptor(descriptor)
    finally:
        os.close(descriptor)


def write_backup(
    source: Path, binding: LocalGraphBinding, output: Path, *, created_at: str
) -> BackupManifest:
    """Write one completed backup of ``source`` into ``output`` (absent or empty).

    The caller holds the publisher lock of ``source`` and has checked
    ``output`` with :func:`check_backup_output`.
    """
    fsync_directory(output.parent)  # durability probe before any side effect
    created = False
    if not os.path.lexists(output):
        os.mkdir(output, 0o700)
        created = True
    token = secrets.token_hex(8)
    temporary = output / f".{DATABASE_FILE}.backup-{token}"
    manifest_temporary = output / f".{MANIFEST_FILE}.tmp-{token}"
    final_database, final_manifest = output / DATABASE_FILE, output / MANIFEST_FILE
    linked: dict[Path, tuple[int, int]] = {}
    try:
        if created:
            fsync_directory(output.parent)
        os.close(os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
        version, publication = _snapshot(source, binding, temporary)
        _fault_point("backup:snapshot-complete")
        seal_database_file(temporary, binding, accept_behind=True)
        if inspect_sealed_database(temporary, binding) != (version, publication):
            raise LocalStoreError(GENERATION_ADVANCED, "backup snapshot changed")
        size, digest = file_digest(temporary)
        linked[final_database] = _link(temporary, final_database)
        _fault_point("backup:database-linked")
        temporary.unlink()
        fsync_directory(output)
        if sorted(os.listdir(output)) != [DATABASE_FILE]:
            raise LocalStoreError(BACKUP_OUTPUT_INVALID, "output directory changed during backup")
        manifest = BackupManifest(created_at, binding, publication, size, digest, version)
        _write_new(manifest_temporary, manifest.encode())
        _fault_point("backup:before-manifest-link")
        linked[final_manifest] = _link(manifest_temporary, final_manifest)
        _fault_point("backup:manifest-linked")
        manifest_temporary.unlink()
        fsync_directory(output)
    except BaseException:
        _discard_attempt(output, (*owned_names(temporary), manifest_temporary), linked, created=created)
        raise
    return manifest


def _discard_attempt(
    output: Path,
    temporaries: tuple[Path, ...],
    linked: dict[Path, tuple[int, int]],
    *,
    created: bool,
) -> None:
    """Remove only this attempt's names; the manifest goes first."""
    for final in sorted(linked, key=lambda name: name.name != MANIFEST_FILE):
        with suppress(OSError):
            details = os.lstat(final)
            if (details.st_dev, details.st_ino) == linked[final]:
                final.unlink()
    for name in temporaries:
        with suppress(OSError):
            name.unlink()
    with suppress(OSError, LocalStoreError):
        if created:
            output.rmdir()
            fsync_directory(output.parent)
        else:
            fsync_directory(output)


__all__ = (
    "check_backup_output",
    "file_digest",
    "inspect_sealed_database",
    "owned_names",
    "write_backup",
)
