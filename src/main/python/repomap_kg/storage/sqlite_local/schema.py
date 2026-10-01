"""SQLite Local schema v1 bytes, the ledger table and the bounded error vocabulary.

The schema stores RepoMap's logical graph contract for exactly one graph:
files, raw observations, canonical nodes/edges/evidence and their links, the
publication runs that produced them, and one accepted-publication marker. It
is not a copy of the PostgreSQL physical schema: there is no repository table
or ``repository_id`` (one database is one graph) and no staging, coordinator,
role or authority tables.

The v1 name, SQL bytes and checksum below are the historical v1 migration and
never change. The ordered, checksummed migration catalog, the current schema
version and state classification live in :mod:`.migrations` (LOCAL8). Unknown,
future, drifted or foreign files are refused before any write; nothing is ever
silently reinitialized or migrated.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from repomap_kg.storage.errors import StorageSchemaError

# "RPM1" as a big-endian 32-bit integer; identifies a RepoMap SQLite Local file.
APPLICATION_ID = 0x52504D31
SCHEMA_NAME = "sqlite-local-v1"
MINIMUM_SQLITE_VERSION = (3, 37, 0)  # STRICT tables

SCHEMA_V1_SQL = """\
CREATE TABLE graph_binding (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    graph_id TEXT NOT NULL CHECK (graph_id <> ''),
    repository_identity TEXT NOT NULL CHECK (repository_identity LIKE 'repo1:%'),
    root_path TEXT NOT NULL CHECK (root_path LIKE 'graph:%'),
    repository_name TEXT
) STRICT;

CREATE TABLE runs (
    id INTEGER PRIMARY KEY CHECK (id > 0),
    previous_run_id INTEGER REFERENCES runs(id),
    status TEXT NOT NULL CHECK (status = 'complete'),
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    publisher TEXT NOT NULL CHECK (publisher = 'sqlite-local-direct-v1'),
    execution_route TEXT NOT NULL CHECK (execution_route = 'portable-worker-v1'),
    portable_protocol_version TEXT NOT NULL,
    snapshot_manifest_id TEXT NOT NULL,
    snapshot_vector_json TEXT NOT NULL,
    extraction_receipt_id TEXT NOT NULL,
    publication_bundle_id TEXT NOT NULL,
    graph_candidate_id TEXT NOT NULL,
    resolver_identity TEXT NOT NULL,
    portable_canonicalizer_identity TEXT NOT NULL,
    semantic_contract_identity TEXT NOT NULL,
    quality_rule_identity TEXT NOT NULL,
    worker_capability_identity TEXT NOT NULL,
    portable_stage_id TEXT NOT NULL,
    portable_execution_mode TEXT NOT NULL,
    source_generation TEXT NOT NULL,
    config_generation TEXT NOT NULL,
    extractor_generation TEXT NOT NULL,
    canonicalizer_generation TEXT NOT NULL,
    publication_job_id TEXT NOT NULL,
    publication_attempt INTEGER NOT NULL CHECK (publication_attempt > 0),
    family_receipts_json TEXT NOT NULL,
    privacy TEXT NOT NULL
) STRICT;

CREATE TABLE accepted_publication (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    generation INTEGER NOT NULL CHECK (generation > 0),
    run_id INTEGER NOT NULL REFERENCES runs(id)
) STRICT;

CREATE TABLE files (
    path TEXT PRIMARY KEY,
    language TEXT NOT NULL,
    role TEXT NOT NULL,
    content_hash TEXT,
    executable INTEGER NOT NULL CHECK (executable IN (0, 1)),
    generated INTEGER NOT NULL CHECK (generated IN (0, 1)),
    metadata_json TEXT NOT NULL,
    last_seen_run_id INTEGER NOT NULL REFERENCES runs(id)
) STRICT;

CREATE TABLE raw_observations (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    path TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    PRIMARY KEY (run_id, ordinal)
) STRICT;

CREATE TABLE canonical_nodes (
    id INTEGER PRIMARY KEY,
    graph_key_version INTEGER NOT NULL CHECK (graph_key_version >= 1),
    canonical_key TEXT NOT NULL CHECK (canonical_key <> ''),
    kind TEXT NOT NULL CHECK (kind <> ''),
    display_name TEXT NOT NULL CHECK (display_name <> ''),
    metadata_json TEXT NOT NULL,
    confidence TEXT NOT NULL,
    conflict INTEGER NOT NULL CHECK (conflict IN (0, 1)),
    first_seen_run_id INTEGER NOT NULL REFERENCES runs(id),
    last_seen_run_id INTEGER NOT NULL REFERENCES runs(id),
    UNIQUE (graph_key_version, canonical_key)
) STRICT;

CREATE TABLE canonical_edges (
    id INTEGER PRIMARY KEY,
    graph_key_version INTEGER NOT NULL CHECK (graph_key_version >= 1),
    source_canonical_key TEXT NOT NULL,
    edge_kind TEXT NOT NULL,
    target_canonical_key TEXT NOT NULL,
    identity_metadata_json TEXT NOT NULL,
    identity_metadata_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    confidence TEXT NOT NULL,
    conflict INTEGER NOT NULL CHECK (conflict IN (0, 1)),
    first_seen_run_id INTEGER NOT NULL REFERENCES runs(id),
    last_seen_run_id INTEGER NOT NULL REFERENCES runs(id),
    UNIQUE (graph_key_version, source_canonical_key, edge_kind,
            target_canonical_key, identity_metadata_hash),
    FOREIGN KEY (graph_key_version, source_canonical_key)
        REFERENCES canonical_nodes(graph_key_version, canonical_key),
    FOREIGN KEY (graph_key_version, target_canonical_key)
        REFERENCES canonical_nodes(graph_key_version, canonical_key)
) STRICT;

CREATE TABLE canonical_evidence (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    graph_key_version INTEGER NOT NULL CHECK (graph_key_version >= 1),
    evidence_key TEXT NOT NULL CHECK (evidence_key <> ''),
    raw_observation_ordinal INTEGER NOT NULL,
    raw_schema_version INTEGER NOT NULL,
    raw_kind TEXT NOT NULL,
    raw_source_id TEXT NOT NULL,
    path TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    extractor TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    confidence TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    UNIQUE (run_id, graph_key_version, evidence_key),
    FOREIGN KEY (run_id, raw_observation_ordinal)
        REFERENCES raw_observations(run_id, ordinal)
) STRICT;

CREATE TABLE canonical_node_evidence (
    canonical_node_id INTEGER NOT NULL REFERENCES canonical_nodes(id),
    canonical_evidence_id INTEGER NOT NULL REFERENCES canonical_evidence(id),
    link_kind TEXT NOT NULL CHECK (link_kind <> ''),
    PRIMARY KEY (canonical_node_id, canonical_evidence_id, link_kind)
) STRICT;

CREATE TABLE canonical_edge_evidence (
    canonical_edge_id INTEGER NOT NULL REFERENCES canonical_edges(id),
    canonical_evidence_id INTEGER NOT NULL REFERENCES canonical_evidence(id),
    link_kind TEXT NOT NULL CHECK (link_kind <> ''),
    PRIMARY KEY (canonical_edge_id, canonical_evidence_id, link_kind)
) STRICT;

CREATE INDEX idx_raw_observations_kind ON raw_observations(kind);
CREATE INDEX idx_canonical_nodes_kind ON canonical_nodes(graph_key_version, kind);
CREATE INDEX idx_canonical_edges_target
    ON canonical_edges(graph_key_version, target_canonical_key);
CREATE INDEX idx_canonical_edges_kind ON canonical_edges(graph_key_version, edge_kind);
CREATE INDEX idx_canonical_evidence_path ON canonical_evidence(path);
CREATE INDEX idx_canonical_node_evidence_evidence
    ON canonical_node_evidence(canonical_evidence_id);
CREATE INDEX idx_canonical_edge_evidence_evidence
    ON canonical_edge_evidence(canonical_evidence_id);
"""

SCHEMA_V1_CHECKSUM = "sha256:" + hashlib.sha256(SCHEMA_V1_SQL.encode("utf-8")).hexdigest()

LEDGER_SQL = """\
CREATE TABLE local_schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
) STRICT;
"""

class LocalStoreError(StorageSchemaError):
    """Bounded, path-free SQLite Local refusal with a stable code."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        super().__init__(code if detail is None else f"{code}: {detail}")


NOT_INITIALIZED = "graph-database-not-initialized"
UNRECOGNIZED = "graph-database-unrecognized"
SCHEMA_UNSUPPORTED = "graph-database-schema-unsupported"
SCHEMA_DRIFT = "graph-database-schema-drift"
GRAPH_MISMATCH = "graph-database-graph-mismatch"
PUBLICATION_ABSENT = "graph-publication-absent"
DATABASE_BUSY = "graph-database-busy"
DATABASE_READ_ONLY = "graph-database-read-only"
DATABASE_UNAVAILABLE = "graph-database-unavailable"
PUBLICATION_IN_PROGRESS = "graph-publication-in-progress"
GENERATION_ADVANCED = "accepted-generation-advanced"
PUBLICATION_REJECTED = "graph-publication-rejected"
PUBLICATION_INTERNAL_ERROR = "graph-publication-internal-error"
PUBLICATION_RECONCILIATION_REQUIRED = "graph-publication-reconciliation-required"
SCHEMA_BEHIND = "graph-database-schema-behind"
MIGRATION_RECONCILIATION_REQUIRED = "graph-migration-reconciliation-required"
RUNTIME_UNSUPPORTED = "sqlite-runtime-unsupported"


@dataclass(frozen=True)
class LocalGraphBinding:
    """The single logical graph a database owns."""

    graph_id: str
    repository_identity: str
    root_path: str


@dataclass(frozen=True)
class AcceptedIdentity:
    """The accepted generation and the publication attempt that produced it."""

    generation: int
    run_id: int
    previous_run_id: int | None
    publication_bundle_id: str | None
    publication_job_id: str | None
    publication_attempt: int | None


def accepted_identity(connection: sqlite3.Connection) -> AcceptedIdentity | None:
    """Read the accepted marker with its run's attempt identity; ``None`` if unpublished."""
    row = connection.execute(
        "SELECT a.generation, a.run_id, r.previous_run_id, r.publication_bundle_id, "
        "r.publication_job_id, r.publication_attempt FROM accepted_publication a "
        "JOIN runs r ON r.id = a.run_id"
    ).fetchone()
    if row is None:
        return None
    return AcceptedIdentity(
        int(row[0]),
        int(row[1]),
        None if row[2] is None else int(row[2]),
        row[3],
        row[4],
        None if row[5] is None else int(row[5]),
    )


def require_runtime_support(version_info: tuple[int, int, int] | None = None) -> None:
    """Refuse a runtime SQLite library older than the STRICT-table floor."""
    actual = version_info or sqlite3.sqlite_version_info
    if tuple(actual) < MINIMUM_SQLITE_VERSION:
        raise LocalStoreError(
            RUNTIME_UNSUPPORTED,
            "SQLite 3.37.0 or newer is required",
        )


def read_binding(connection: sqlite3.Connection) -> LocalGraphBinding:
    row = connection.execute(
        "SELECT graph_id, repository_identity, root_path FROM graph_binding"
    ).fetchone()
    if row is None:
        raise LocalStoreError(SCHEMA_DRIFT)
    return LocalGraphBinding(str(row[0]), str(row[1]), str(row[2]))


def require_binding(connection: sqlite3.Connection, expected: LocalGraphBinding) -> None:
    if read_binding(connection) != expected:
        raise LocalStoreError(GRAPH_MISMATCH)


__all__ = (
    "APPLICATION_ID",
    "AcceptedIdentity",
    "DATABASE_BUSY",
    "DATABASE_READ_ONLY",
    "DATABASE_UNAVAILABLE",
    "GENERATION_ADVANCED",
    "GRAPH_MISMATCH",
    "LEDGER_SQL",
    "LocalGraphBinding",
    "LocalStoreError",
    "MIGRATION_RECONCILIATION_REQUIRED",
    "MINIMUM_SQLITE_VERSION",
    "NOT_INITIALIZED",
    "PUBLICATION_ABSENT",
    "PUBLICATION_IN_PROGRESS",
    "PUBLICATION_INTERNAL_ERROR",
    "PUBLICATION_RECONCILIATION_REQUIRED",
    "PUBLICATION_REJECTED",
    "RUNTIME_UNSUPPORTED",
    "SCHEMA_BEHIND",
    "SCHEMA_DRIFT",
    "SCHEMA_NAME",
    "SCHEMA_UNSUPPORTED",
    "SCHEMA_V1_CHECKSUM",
    "SCHEMA_V1_SQL",
    "UNRECOGNIZED",
    "accepted_identity",
    "read_binding",
    "require_binding",
    "require_runtime_support",
)
