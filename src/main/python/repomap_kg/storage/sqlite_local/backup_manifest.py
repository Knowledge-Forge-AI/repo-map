"""The SQLite Local backup artifact contract and its public-safe manifest.

REPOMAP-PRODUCT3-SQLITE-LOCAL7. A completed backup is one directory holding
exactly two owner-only regular files:

* ``graph.sqlite3``: a self-contained (sidecar-free, WAL-marked, checkpointed)
  snapshot of one graph database;
* ``manifest.json``: canonical JSON binding that snapshot to its graph, its
  schema and its exact accepted publication, with its byte length and SHA-256.

The manifest is linked last and is the completion marker: a directory without
it is incomplete and is never restored. It records logical identifiers only
(graph id, repository identity, ``graph:<id>`` root, publication ids and the
accepted run's privacy class). It never records source roots, home, backup or
other filesystem paths, environment values, PostgreSQL metadata or payload
bodies. A manifest is evidence about the backup artifact; it is never a new
accepted publication. The database file inherits the graph's privacy
classification and is not public-safe content.

Schema identity (LOCAL8). ``sqlite.user_version`` is the database's exact
schema version (any known catalog version, not only the current one) and
``schema_name``/``schema_checksum`` are that version's *head migration*
identity, not a cumulative whole-schema checksum; the database itself must
classify as exactly that catalog prefix (ledger, ``user_version`` and physical
schema digest). A LOCAL7-era manifest therefore reads as a v1 backup.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from repomap_kg.storage.sqlite_local.migrations import known_migration, migration
from repomap_kg.storage.sqlite_local.schema import (
    APPLICATION_ID,
    LocalGraphBinding,
    LocalStoreError,
    accepted_identity,
)

BACKUP_FORMAT = "repomap-sqlite-local-backup"
MANIFEST_VERSION = 1
DATABASE_FILE = "graph.sqlite3"
MANIFEST_FILE = "manifest.json"
MAX_MANIFEST_BYTES = 16 * 1024

BACKUP_ARTIFACT_INVALID = "sqlite-backup-artifact-invalid"
BACKUP_INCOMPLETE = "sqlite-backup-incomplete"
BACKUP_TARGET_EXISTS = "sqlite-backup-target-exists"
BACKUP_OUTPUT_INVALID = "sqlite-backup-output-invalid"
BACKUP_OUTPUT_FORBIDDEN = "sqlite-backup-output-forbidden"
RESTORE_TARGET_EXISTS = "sqlite-restore-target-exists"

_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TOP_KEYS = frozenset({"format", "manifest_version", "created_at", "graph", "sqlite", "publication", "database"})
_GRAPH_KEYS = frozenset({"graph_id", "repository_identity", "root_path"})
_SQLITE_KEYS = frozenset({"application_id", "user_version", "schema_name", "schema_checksum"})
_PUBLICATION_KEYS = frozenset(
    {"accepted", "generation", "run_id", "publication_bundle_id", "publication_job_id",
     "publication_attempt", "privacy"}
)
_DATABASE_KEYS = frozenset({"file", "bytes", "sha256"})


@dataclass(frozen=True)
class BackupPublication:
    """The exact accepted publication a snapshot holds."""

    generation: int
    run_id: int
    publication_bundle_id: str
    publication_job_id: str
    publication_attempt: int
    privacy: str


@dataclass(frozen=True)
class BackupManifest:
    created_at: str
    binding: LocalGraphBinding
    publication: BackupPublication | None
    database_bytes: int
    database_sha256: str
    schema_version: int

    def encode(self) -> bytes:
        """Deterministic canonical bytes: sorted keys, compact, one trailing newline."""
        publication = self.publication
        head = migration(self.schema_version)
        payload = {
            "format": BACKUP_FORMAT,
            "manifest_version": MANIFEST_VERSION,
            "created_at": self.created_at,
            "graph": {
                "graph_id": self.binding.graph_id,
                "repository_identity": self.binding.repository_identity,
                "root_path": self.binding.root_path,
            },
            "sqlite": {
                "application_id": APPLICATION_ID,
                "user_version": head.version,
                "schema_name": head.name,
                "schema_checksum": head.checksum,
            },
            "publication": {
                "accepted": publication is not None,
                "generation": None if publication is None else publication.generation,
                "run_id": None if publication is None else publication.run_id,
                "publication_bundle_id": None if publication is None else publication.publication_bundle_id,
                "publication_job_id": None if publication is None else publication.publication_job_id,
                "publication_attempt": None if publication is None else publication.publication_attempt,
                "privacy": None if publication is None else publication.privacy,
            },
            "database": {"file": DATABASE_FILE, "bytes": self.database_bytes, "sha256": self.database_sha256},
        }
        return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def read_publication(connection: sqlite3.Connection) -> BackupPublication | None:
    """The accepted publication inside an open database; ``None`` if unpublished."""
    accepted = accepted_identity(connection)
    if accepted is None:
        return None
    privacy = connection.execute("SELECT privacy FROM runs WHERE id = ?", (accepted.run_id,)).fetchone()
    bundle, job, attempt = (
        accepted.publication_bundle_id, accepted.publication_job_id, accepted.publication_attempt
    )
    if privacy is None or bundle is None or job is None or attempt is None:
        raise LocalStoreError(BACKUP_ARTIFACT_INVALID, "accepted publication is incomplete")
    return BackupPublication(accepted.generation, accepted.run_id, bundle, job, attempt, str(privacy[0]))


def _invalid(reason: str) -> LocalStoreError:
    return LocalStoreError(BACKUP_ARTIFACT_INVALID, reason)


def _block(payload: dict[str, Any], key: str, keys: frozenset[str]) -> dict[str, Any]:
    value = payload[key]
    if not isinstance(value, dict) or set(value) != keys:
        raise _invalid("manifest-invalid")
    return value


def _integer(value: object, *, minimum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise _invalid("manifest-invalid")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise _invalid("manifest-invalid")
    return value


def parse_manifest(encoded: bytes) -> BackupManifest:
    """Strictly parse one manifest; refuse unknown formats and schemas."""
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise _invalid("manifest-invalid")
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _invalid("manifest-invalid") from None
    if not isinstance(payload, dict) or set(payload) != _TOP_KEYS:
        raise _invalid("manifest-invalid")
    if payload["format"] != BACKUP_FORMAT or payload["manifest_version"] != MANIFEST_VERSION or isinstance(
        payload["manifest_version"], bool
    ):
        raise _invalid("format-unsupported")
    created_at = _text(payload["created_at"])
    if not _TIMESTAMP.match(created_at):
        raise _invalid("manifest-invalid")
    graph = _block(payload, "graph", _GRAPH_KEYS)
    binding = LocalGraphBinding(
        _text(graph["graph_id"]), _text(graph["repository_identity"]), _text(graph["root_path"])
    )
    sqlite = _block(payload, "sqlite", _SQLITE_KEYS)
    schema_version = _integer(sqlite["user_version"], minimum=0)
    name, checksum = sqlite["schema_name"], sqlite["schema_checksum"]
    if (
        _integer(sqlite["application_id"], minimum=0) != APPLICATION_ID
        or not isinstance(name, str)
        or not isinstance(checksum, str)
        or not known_migration(schema_version, name, checksum)
    ):
        raise _invalid("schema-unsupported")
    database = _block(payload, "database", _DATABASE_KEYS)
    digest = _text(database["sha256"])
    if database["file"] != DATABASE_FILE or not _SHA256.match(digest):
        raise _invalid("manifest-invalid")
    return BackupManifest(
        created_at=created_at,
        binding=binding,
        publication=_publication(_block(payload, "publication", _PUBLICATION_KEYS)),
        database_bytes=_integer(database["bytes"], minimum=1),
        database_sha256=digest,
        schema_version=schema_version,
    )


def _publication(block: dict[str, Any]) -> BackupPublication | None:
    accepted = block["accepted"]
    if accepted is False:
        if any(block[key] is not None for key in _PUBLICATION_KEYS - {"accepted"}):
            raise _invalid("manifest-invalid")
        return None
    if accepted is not True:
        raise _invalid("manifest-invalid")
    return BackupPublication(
        generation=_integer(block["generation"], minimum=1),
        run_id=_integer(block["run_id"], minimum=1),
        publication_bundle_id=_text(block["publication_bundle_id"]),
        publication_job_id=_text(block["publication_job_id"]),
        publication_attempt=_integer(block["publication_attempt"], minimum=1),
        privacy=_text(block["privacy"]),
    )


__all__ = (
    "BACKUP_ARTIFACT_INVALID",
    "BACKUP_FORMAT",
    "BACKUP_INCOMPLETE",
    "BACKUP_OUTPUT_FORBIDDEN",
    "BACKUP_OUTPUT_INVALID",
    "BACKUP_TARGET_EXISTS",
    "BackupManifest",
    "BackupPublication",
    "DATABASE_FILE",
    "MANIFEST_FILE",
    "MANIFEST_VERSION",
    "MAX_MANIFEST_BYTES",
    "RESTORE_TARGET_EXISTS",
    "parse_manifest",
    "read_publication",
)
