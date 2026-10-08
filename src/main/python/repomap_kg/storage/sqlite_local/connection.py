"""Opening SQLite Local graph databases: read-only readers and the one writer.

Transaction policy (ADR 0075):

* Connections use Python's ``autocommit=True`` so the ``sqlite3`` module never
  opens implicit transactions; every transaction is an explicit ``BEGIN``.
* The writer uses ``BEGIN IMMEDIATE`` so write intent is reserved at start,
  ``foreign_keys=ON`` and ``synchronous=FULL``. Journal mode is WAL, set once
  by explicit initialization (it is persistent) and verified on every open.
* Readers open an existing file through a ``file:`` URI built by
  ``Path.as_uri()`` with ``mode=ro`` (never ``immutable=1``), set
  ``query_only``, and run one deferred ``BEGIN`` per operation so every
  query of that operation sees one committed snapshot. They never create,
  initialize, migrate or change the journal mode of a database.
* One publisher per graph: :func:`publisher_lock` verifies the private store
  directory and takes the platform-neutral graph lock (:mod:`.locking`) on a
  sibling lock file. The database file itself is never the lock target.
* Initialization never creates the final path before the database is
  complete. The exact-current schema (every :mod:`.migrations` changeset in
  order) is built, checkpointed and validated in a uniquely named
  sibling temporary file, then hard-linked to the final path, which fails
  rather than overwrites if the path exists, and the temporary name is removed.
  A crash can leave only an orphan ``.<name>.init-*`` file. A store that cannot
  hard-link refuses; there is no overwriting fallback.
* Durability (LOCAL7, :mod:`.durability`): the completed temporary file is
  fsynced before the link, the store directory and the requested ancestor
  levels are fsynced before it, and the store directory is fsynced after it.
  A failed sync is a bounded ``local-durability-*`` refusal, never success;
  the database is then complete and a rerun reports ``already-current``. Only
  the sync after removing the temporary name is best-effort: it covers an
  orphan second link, not the installed database.
* Schema states (LOCAL8): readers and the writer admit only exact-current
  databases; ``accept_behind=True`` (readiness, backup, restore readback and
  ``sqlite-upgrade``) also admits an exact-behind one. Nothing here migrates.
"""

from __future__ import annotations

import errno
import os
import secrets
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from repomap_kg.storage.sqlite_local.durability import (
    fsync_directory,
    fsync_directory_chain,
    fsync_file,
)
from repomap_kg.storage.sqlite_local.locking import hold_graph_lock, lock_path
from repomap_kg.storage.sqlite_local.migrations import (
    classify,
    initialize_schema,
    require_open_state,
)
from repomap_kg.storage.sqlite_local.schema import (
    DATABASE_BUSY,
    DATABASE_READ_ONLY,
    DATABASE_UNAVAILABLE,
    NOT_INITIALIZED,
    PUBLICATION_INTERNAL_ERROR,
    PUBLICATION_REJECTED,
    SCHEMA_DRIFT,
    UNRECOGNIZED,
    LocalGraphBinding,
    LocalStoreError,
    require_binding,
    require_runtime_support,
)

READ_BUSY_TIMEOUT_SECONDS = 5.0
WRITE_BUSY_TIMEOUT_SECONDS = 5.0
_SQLITE_BUSY = 5
_SQLITE_LOCKED = 6
# Plain SQLITE_READONLY: a write refused by ``query_only`` or ``mode=ro``.
# Extended READONLY codes (recovery, cantlock, rollback, dbmoved, cantinit,
# directory) are environment conditions and stay ``graph-database-unavailable``.
_SQLITE_READONLY = 8
_NO_ATOMIC_INSTALL = frozenset(
    (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV, errno.EMLINK)
)


def graph_database_uri(path: Path, *, read_only: bool) -> str:
    """Return a safely escaped ``file:`` URI; options are never user text."""
    mode = "ro" if read_only else "rw"
    return f"{path.resolve().as_uri()}?mode={mode}"


def sidecar_paths(path: Path) -> tuple[Path, Path]:
    return path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")


def _classify(error: sqlite3.Error) -> LocalStoreError:
    code = getattr(error, "sqlite_errorcode", None)
    if isinstance(code, int) and code & 0xFF in (_SQLITE_BUSY, _SQLITE_LOCKED):
        return LocalStoreError(DATABASE_BUSY)
    if code == _SQLITE_READONLY:
        return LocalStoreError(DATABASE_READ_ONLY)
    if isinstance(error, sqlite3.DatabaseError) and not isinstance(
        error, sqlite3.OperationalError
    ):
        return LocalStoreError(UNRECOGNIZED)
    return LocalStoreError(DATABASE_UNAVAILABLE)


def classify_write_error(error: sqlite3.Error) -> LocalStoreError:
    """Bound a writer ``sqlite3`` error; constraint and interface errors are not "unrecognized"."""
    if isinstance(error, (sqlite3.IntegrityError, sqlite3.DataError)):
        return LocalStoreError(PUBLICATION_REJECTED, "the database refused a publication row")
    if isinstance(
        error, (sqlite3.ProgrammingError, sqlite3.InterfaceError, sqlite3.NotSupportedError)
    ):
        return LocalStoreError(PUBLICATION_INTERNAL_ERROR)
    return _classify(error)


def _existing_regular_file(path: Path) -> None:
    try:
        details = os.lstat(path)
    except FileNotFoundError:
        raise LocalStoreError(NOT_INITIALIZED) from None
    except OSError:
        raise LocalStoreError(DATABASE_UNAVAILABLE) from None
    if not stat.S_ISREG(details.st_mode):
        raise LocalStoreError(UNRECOGNIZED)


def _require_wal(connection: sqlite3.Connection) -> None:
    mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    if str(mode).lower() != "wal":
        raise LocalStoreError(SCHEMA_DRIFT)


@contextmanager
def read_transaction(
    path: Path, expected: LocalGraphBinding, *, accept_behind: bool = False
) -> Iterator[sqlite3.Connection]:
    """Yield one read-only connection inside one committed-snapshot transaction."""
    require_runtime_support()
    _existing_regular_file(path)
    try:
        connection = sqlite3.connect(
            graph_database_uri(path, read_only=True),
            uri=True,
            autocommit=True,
            timeout=READ_BUSY_TIMEOUT_SECONDS,
        )
    except sqlite3.Error as error:
        raise _classify(error) from None
    try:
        try:
            connection.execute("PRAGMA query_only = ON")
            connection.execute("BEGIN")
            require_open_state(classify(connection), accept_behind=accept_behind)
            _require_wal(connection)
            require_binding(connection, expected)
        except sqlite3.Error as error:
            raise _classify(error) from None
        try:
            yield connection
        except sqlite3.Error as error:
            raise _classify(error) from None
        try:
            connection.execute("COMMIT")
        except sqlite3.Error as error:
            raise _classify(error) from None
    finally:
        connection.close()


def open_writer(
    path: Path, expected: LocalGraphBinding, *, accept_behind: bool = False
) -> sqlite3.Connection:
    """Open an existing, current (or accepted behind) database for the single writer."""
    require_runtime_support()
    _existing_regular_file(path)
    try:
        connection = sqlite3.connect(
            graph_database_uri(path, read_only=False),
            uri=True,
            autocommit=True,
            timeout=WRITE_BUSY_TIMEOUT_SECONDS,
        )
    except sqlite3.Error as error:
        raise _classify(error) from None
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = FULL")
        require_open_state(classify(connection), accept_behind=accept_behind)
        _require_wal(connection)
        require_binding(connection, expected)
    except sqlite3.Error as error:
        connection.close()
        raise _classify(error) from None
    except BaseException:
        connection.close()
        raise
    return connection


def private_store_directory(directory: Path) -> None:
    """Create or verify an owner-only, non-symlink graph store directory."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISDIR(details.st_mode) or details.st_uid != os.getuid():
            raise LocalStoreError(DATABASE_UNAVAILABLE, "graph store directory is not private")
        os.fchmod(descriptor, 0o700)
    finally:
        os.close(descriptor)


@contextmanager
def publisher_lock(path: Path) -> Iterator[None]:
    """Hold the graph's single-publisher lock or refuse immediately."""
    private_store_directory(path.parent)
    with hold_graph_lock(path):
        yield


def initialize_graph_database(
    path: Path,
    binding: LocalGraphBinding,
    *,
    applied_at: str,
    durable_ancestors: int = 0,
) -> str:
    """Create the current schema for ``binding``; return ``initialized`` or ``already-current``.

    The caller holds :func:`publisher_lock`. An existing file is never
    reinitialized or migrated: a current database of this graph is reported
    unchanged and anything else (an exact-behind one included) is refused. ``durable_ancestors`` parent levels of the store
    directory are fsynced before install, so newly created store levels are
    durable in their parents.
    """
    require_runtime_support()
    if os.path.lexists(path):
        return _existing_database(path, binding)
    temporary = path.with_name(f".{path.name}.init-{secrets.token_hex(8)}")
    descriptor = os.open(
        temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    os.close(descriptor)
    installed = False
    try:
        _fault_point("init:temporary-created")
        _build_complete_database(temporary, binding, applied_at=applied_at)
        fsync_directory_chain(path.parent, durable_ancestors)
        _fault_point("init:before-install")
        try:
            os.link(temporary, path)
        except FileExistsError:
            return _existing_database(path, binding)
        except OSError as error:
            if error.errno in _NO_ATOMIC_INSTALL:
                raise LocalStoreError(
                    DATABASE_UNAVAILABLE,
                    "graph store does not support atomic no-clobber install",
                ) from None
            raise
        installed = True
        _fault_point("init:installed")
        fsync_directory(path.parent)
        _fault_point("init:after-install")
    finally:
        # Only this attempt's own names are removed; the final path never is.
        # After install the temporary name is a second link to the complete
        # final database, so removing it is best-effort.
        for owned in (temporary, *sidecar_paths(temporary)):
            with suppress(OSError):
                owned.unlink()
        if installed:
            with suppress(OSError, LocalStoreError):
                fsync_directory(path.parent)
    return "initialized"


def _fault_point(name: str) -> None:
    """No-op seam; tests replace it to fail or pause at a named point."""
    return None


def _existing_database(path: Path, binding: LocalGraphBinding) -> str:
    """Report an existing current database of ``binding``; refuse anything else."""
    writer = open_writer(path, binding)
    writer.close()
    return "already-current"


def _build_complete_database(
    temporary: Path, binding: LocalGraphBinding, *, applied_at: str
) -> None:
    """Build, checkpoint and validate a self-contained exact-current database file."""
    try:
        connection = sqlite3.connect(
            graph_database_uri(temporary, read_only=False),
            uri=True,
            autocommit=True,
            timeout=WRITE_BUSY_TIMEOUT_SECONDS,
        )
    except sqlite3.Error as error:
        raise _classify(error) from None
    try:
        try:
            if classify(connection).kind != "empty":
                raise LocalStoreError(UNRECOGNIZED)
            mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                raise LocalStoreError(DATABASE_UNAVAILABLE, "WAL journal mode is unavailable")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("BEGIN IMMEDIATE")
            try:
                initialize_schema(connection, binding, applied_at=applied_at)
                connection.execute("COMMIT")
            except BaseException:
                with suppress(sqlite3.Error):
                    connection.execute("ROLLBACK")
                raise
            _fault_point("init:schema-applied")
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if tuple(checkpoint) != (0, 0, 0):
                raise LocalStoreError(DATABASE_UNAVAILABLE, "initial checkpoint is incomplete")
        except sqlite3.Error as error:
            raise _classify(error) from None
    finally:
        connection.close()
    seal_database_file(temporary, binding)


def seal_database_file(
    path: Path, binding: LocalGraphBinding, *, accept_behind: bool = False
) -> None:
    """Make a checkpointed, closed database self-contained and durable.

    Validates it through the writer open, removes an empty ``-wal`` and the
    ``-shm`` (a non-empty ``-wal`` means the checkpoint was incomplete) and
    fsyncs the file. Used for init and backup temporary files only.
    """
    open_writer(path, binding, accept_behind=accept_behind).close()
    discard_sidecars(path)
    fsync_file(path)


def discard_sidecars(path: Path) -> None:
    """Remove an unused database's empty ``-wal`` and its ``-shm``; refuse live WAL."""
    wal, shm = sidecar_paths(path)
    if os.path.lexists(wal):
        if os.lstat(wal).st_size != 0:
            raise LocalStoreError(DATABASE_UNAVAILABLE, "checkpoint is incomplete")
        wal.unlink()
    with suppress(FileNotFoundError):
        shm.unlink()


__all__ = (
    "classify_write_error",
    "discard_sidecars",
    "graph_database_uri",
    "initialize_graph_database",
    "lock_path",
    "open_writer",
    "private_store_directory",
    "publisher_lock",
    "read_transaction",
    "seal_database_file",
    "sidecar_paths",
)
