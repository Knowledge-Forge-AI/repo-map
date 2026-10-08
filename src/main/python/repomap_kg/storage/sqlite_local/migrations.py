"""The ordered, checksummed SQLite Local migration catalog and schema states (LOCAL8).

``MIGRATIONS`` is the single schema authority. Each migration has a stable
name, deterministic SQL bytes and the SHA-256 checksum of those bytes; the
versions are 1..n in order. A fresh database applies every migration in
order (there is no separate "fresh current" DDL), and ``ops sqlite-upgrade``
applies the pending suffix of the same catalog.

* v1 ``sqlite-local-v1``: the historical schema (:data:`.schema.SCHEMA_V1_SQL`,
  bytes and checksum unchanged since LOCAL1).
* v2 ``sqlite-local-v2-observation-path-index``: an index serving the
  exact-path observation search filter and its ``run_id DESC, ordinal``
  order. It changes no stored row and no query result.

Classification never infers a state from ``PRAGMA user_version`` alone. A
RepoMap file is ``current`` or ``behind(k)`` only when its ledger is exactly
the catalog's first ``k`` migrations, ``user_version`` is ``k`` and its
physical schema digest equals a reference database built from the same
prefix. A version or ``user_version`` beyond the catalog is unsupported; any
other mismatch (checksum, name, order, gap, missing or extra object,
impossible ``user_version``/ledger combination, empty ledger) is drift. A
foreign or non-database file stays unrecognized.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Literal

from repomap_kg.storage.sqlite_local.schema import (
    APPLICATION_ID,
    LEDGER_SQL,
    SCHEMA_BEHIND,
    SCHEMA_DRIFT,
    SCHEMA_NAME,
    SCHEMA_UNSUPPORTED,
    SCHEMA_V1_SQL,
    UNRECOGNIZED,
    LocalGraphBinding,
    LocalStoreError,
)


@dataclass(frozen=True)
class Migration:
    """One ordered schema changeset; its checksum is derived from its SQL bytes."""

    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return "sha256:" + hashlib.sha256(self.sql.encode("utf-8")).hexdigest()

    @property
    def identity(self) -> tuple[int, str, str]:
        """The ``(version, name, checksum)`` ledger row this migration records."""
        return (self.version, self.name, self.checksum)


SCHEMA_V2_NAME = "sqlite-local-v2-observation-path-index"
SCHEMA_V2_SQL = """\
CREATE INDEX idx_raw_observations_path_run
    ON raw_observations(path, run_id DESC, ordinal);
"""

MIGRATION_V1 = Migration(1, SCHEMA_NAME, SCHEMA_V1_SQL)
MIGRATION_V2 = Migration(2, SCHEMA_V2_NAME, SCHEMA_V2_SQL)
# The catalog is read at call time; nothing imports it by value for logic.
MIGRATIONS: tuple[Migration, ...] = (MIGRATION_V1, MIGRATION_V2)

SchemaKind = Literal["empty", "current", "behind"]


@dataclass(frozen=True)
class SchemaState:
    """A classified RepoMap database: ``version`` is its exact catalog prefix length."""

    kind: SchemaKind
    version: int


def current_version() -> int:
    return len(MIGRATIONS)


def migration(version: int) -> Migration:
    """The catalog migration with ``version``; refuse an unknown version."""
    if not 1 <= version <= len(MIGRATIONS):
        raise LocalStoreError(SCHEMA_UNSUPPORTED)
    return MIGRATIONS[version - 1]


def pending_migrations(version: int) -> tuple[Migration, ...]:
    """The catalog migrations after an exact-behind ``version``, in order."""
    return MIGRATIONS[version:]


def known_migration(version: int, name: str, checksum: str) -> bool:
    """True when ``(version, name, checksum)`` is exactly a catalog migration."""
    return 1 <= version <= len(MIGRATIONS) and MIGRATIONS[version - 1].identity == (
        version, name, checksum
    )


def schema_objects_digest(connection: sqlite3.Connection) -> str:
    """Digest the database's own schema objects (tables, indexes, SQL text)."""
    rows = connection.execute(
        "SELECT type, name, tbl_name, coalesce(sql, '') FROM sqlite_schema "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()
    digest = hashlib.sha256()
    for row in rows:
        digest.update("\0".join(str(value) for value in row).encode("utf-8") + b"\n")
    return digest.hexdigest()


_REFERENCE_DIGESTS: dict[tuple[tuple[int, str, str], ...], str] = {}


def reference_digest(version: int) -> str:
    """Physical schema digest of an in-memory database built from the first ``version`` migrations."""
    prefix = MIGRATIONS[:version]
    key = tuple(item.identity for item in prefix)
    cached = _REFERENCE_DIGESTS.get(key)
    if cached is None:
        reference = sqlite3.connect(":memory:", autocommit=True)
        try:
            apply_migration_sql(reference, prefix)
            cached = schema_objects_digest(reference)
        finally:
            reference.close()
        _REFERENCE_DIGESTS[key] = cached
    return cached


def apply_migration_sql(connection: sqlite3.Connection, migrations: tuple[Migration, ...]) -> None:
    """Create the ledger table, then run each migration's SQL in catalog order."""
    connection.executescript(LEDGER_SQL)
    for item in migrations:
        connection.executescript(item.sql)


def record_migration(connection: sqlite3.Connection, item: Migration, *, applied_at: str) -> None:
    connection.execute(
        "INSERT INTO local_schema_migrations(version, name, checksum, applied_at) "
        "VALUES (?, ?, ?, ?)",
        (*item.identity, applied_at),
    )


def classify(connection: sqlite3.Connection) -> SchemaState:
    """Classify an open database: ``empty``, ``current``, ``behind`` or raise a refusal."""
    try:
        application_id = connection.execute("PRAGMA application_id").fetchone()[0]
        objects = connection.execute(
            "SELECT count(*) FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
    except sqlite3.DatabaseError as error:
        raise LocalStoreError(UNRECOGNIZED) from error
    if application_id == 0 and objects == 0:
        return SchemaState("empty", 0)
    if application_id != APPLICATION_ID:
        raise LocalStoreError(UNRECOGNIZED)
    try:
        rows = connection.execute(
            "SELECT version, name, checksum FROM local_schema_migrations ORDER BY version"
        ).fetchall()
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    except sqlite3.DatabaseError as error:
        raise LocalStoreError(SCHEMA_DRIFT) from error
    ledger = tuple((int(v), str(n), str(c)) for v, n, c in rows)
    head = current_version()
    if any(version > head for version, _, _ in ledger) or user_version > head:
        raise LocalStoreError(SCHEMA_UNSUPPORTED)
    applied = len(ledger)
    if (
        applied == 0
        or ledger != tuple(item.identity for item in MIGRATIONS[:applied])
        or user_version != applied
    ):
        raise LocalStoreError(SCHEMA_DRIFT)
    if schema_objects_digest(connection) != reference_digest(applied):
        raise LocalStoreError(SCHEMA_DRIFT)
    return SchemaState("current" if applied == head else "behind", applied)


def require_open_state(state: SchemaState, *, accept_behind: bool) -> SchemaState:
    """Admit exact-current (and, when asked, exact-behind); refuse everything else."""
    if state.kind == "current" or (accept_behind and state.kind == "behind"):
        return state
    if state.kind == "behind":
        raise LocalStoreError(SCHEMA_BEHIND, "run ops sqlite-upgrade")
    raise LocalStoreError(UNRECOGNIZED)


def initialize_schema(
    connection: sqlite3.Connection, binding: LocalGraphBinding, *, applied_at: str
) -> None:
    """Create the exact-current schema inside the caller's open write transaction."""
    apply_migration_sql(connection, MIGRATIONS)
    for item in MIGRATIONS:
        record_migration(connection, item, applied_at=applied_at)
    connection.execute(
        "INSERT INTO graph_binding(singleton, graph_id, repository_identity, root_path, "
        "repository_name) VALUES (1, ?, ?, ?, NULL)",
        (binding.graph_id, binding.repository_identity, binding.root_path),
    )
    connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version = {current_version()}")


__all__ = (
    "MIGRATIONS",
    "MIGRATION_V1",
    "MIGRATION_V2",
    "Migration",
    "SCHEMA_V2_NAME",
    "SCHEMA_V2_SQL",
    "SchemaKind",
    "SchemaState",
    "apply_migration_sql",
    "classify",
    "current_version",
    "initialize_schema",
    "known_migration",
    "migration",
    "pending_migrations",
    "record_migration",
    "reference_digest",
    "require_open_state",
    "schema_objects_digest",
)
