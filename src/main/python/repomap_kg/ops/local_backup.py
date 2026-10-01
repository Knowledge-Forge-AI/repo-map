"""SQLite Local ``ops sqlite-backup``, ``sqlite-restore`` (LOCAL7) and ``sqlite-upgrade`` (LOCAL8).

All three commands are SQLite-only, source-blind and driver-free: a PostgreSQL home
is refused before any filesystem or database action, no source root is checked
or read, no worker, network, PostgreSQL or container path is reached, and
nothing falls back to one.

``backup_local_graph`` snapshots one initialized graph (enabled or not) under
its publisher lock into a new backup directory (see
:mod:`repomap_kg.storage.sqlite_local.backup`). The output must be absent or an
empty real directory whose parent exists, and must not lie inside the home's
private ``state`` tree or any configured source root, so a later refresh can
never capture a backup. The completed directory is also the Local export
format; there is no second one.

``restore_local_graph`` validates a backup completely before touching the
store, then installs it only into an absent target (see
:mod:`repomap_kg.storage.sqlite_local.restore`). Retained publication attempts
are not touched; the next refresh reconciles them against the restored
accepted marker, which is the source of truth. A backup of an older known
schema version restores at that version and is never migrated.

``upgrade_local_graph`` is the only forward schema migration (see
:mod:`repomap_kg.storage.sqlite_local.upgrade`): under the graph's publisher
lock an exact-current database is reported ``already-current`` with no backup;
an exact-behind one is backed up into ``--backup-output`` (same output policy
as ``sqlite-backup``), the backup is verified and only then is the schema
migrated in one transaction. The accepted generation and publication bundle
are unchanged. There is no downgrade and the backup is never deleted.

All three refuse ``local-state-layout-invalid`` first when the home's
``state/`` tree is not real and owned (LOCAL10, :mod:`.local_state_layout`).

Every refusal is a bounded code without a filesystem path. Unexpected
filesystem errors are translated to ``sqlite-backup-io-failed``,
``sqlite-restore-io-failed`` or ``sqlite-upgrade-io-failed`` with the errno
name only.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any

from repomap_kg.ops.config_local import (
    SQLITE_GRAPH_STORE_RELATIVE,
    LocalSqliteConfig,
    local_graph_binding,
)
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_kg.ops.local_state_layout import mutable_local_state
from repomap_kg.storage.sqlite_local.backup import check_backup_output, write_backup
from repomap_kg.storage.sqlite_local.backup_manifest import (
    BACKUP_OUTPUT_FORBIDDEN,
    BACKUP_OUTPUT_INVALID,
    BackupPublication,
)
from repomap_kg.storage.sqlite_local.connection import publisher_lock
from repomap_kg.storage.sqlite_local.durability import fsync_directory
from repomap_kg.storage.sqlite_local.publisher import utc_timestamp
from repomap_kg.storage.sqlite_local.restore import (
    install_backup,
    require_absent_target,
    verify_backup,
)
from repomap_kg.storage.sqlite_local.migrations import current_version
from repomap_kg.storage.sqlite_local.schema import NOT_INITIALIZED, LocalStoreError
from repomap_kg.storage.sqlite_local.upgrade import upgrade_graph_database

BACKUP_IO_FAILED = "sqlite-backup-io-failed"
RESTORE_IO_FAILED = "sqlite-restore-io-failed"
UPGRADE_IO_FAILED = "sqlite-upgrade-io-failed"


class LocalBackupError(ValueError):
    """Bounded backup or restore command refusal (unknown graph)."""


def _graph(config: LocalSqliteConfig, graph_id: str) -> OpsGraphConfig:
    for graph in config.graphs:
        if graph.id == graph_id:
            return graph
    raise LocalBackupError(f"unknown graph_id: {graph_id}")


def _io_failure(code: str, error: OSError) -> LocalStoreError:
    return LocalStoreError(code, errno.errorcode.get(error.errno or 0, "unknown-error"))


def _publication_fields(publication: BackupPublication | None) -> dict[str, Any]:
    return {
        "accepted_publication": publication is not None,
        "accepted_generation": None if publication is None else publication.generation,
        "publication_bundle_id": None if publication is None else publication.publication_bundle_id,
    }


def _output_path(config: LocalSqliteConfig, output: str | Path) -> Path:
    """Resolve the output's parent (not the output) and refuse forbidden places."""
    requested = Path(output).expanduser()
    if requested.name in ("", ".", ".."):
        raise LocalStoreError(BACKUP_OUTPUT_INVALID, "output must name a new or empty directory")
    try:
        parent = requested.parent.resolve(strict=True)
    except (OSError, RuntimeError):
        raise LocalStoreError(BACKUP_OUTPUT_INVALID, "output parent is not a directory") from None
    resolved = parent / requested.name
    forbidden = [(config.control_root / SQLITE_GRAPH_STORE_RELATIVE.parts[0]).resolve()]
    for graph in config.graphs:
        forbidden.extend(
            Path(binding.root_path_expanded).resolve() for binding in graph.effective_source_bindings
        )
    if any(resolved == root or resolved.is_relative_to(root) for root in forbidden):
        raise LocalStoreError(
            BACKUP_OUTPUT_FORBIDDEN, "output must be outside the home state and every source root"
        )
    return resolved


def backup_local_graph(
    config: LocalSqliteConfig, graph_id: str, output: str | Path
) -> dict[str, Any]:
    """Write one completed backup of ``graph_id``'s database into ``output``."""
    graph = _graph(config, graph_id)
    try:
        path = mutable_local_state(config, graph).database
        if not path.is_file():
            raise LocalStoreError(NOT_INITIALIZED, "run ops sqlite-init for this graph first")
        target = _output_path(config, output)
        check_backup_output(target)
        with publisher_lock(path):
            manifest = write_backup(
                path, local_graph_binding(graph), target, created_at=utc_timestamp()
            )
    except OSError as error:
        raise _io_failure(BACKUP_IO_FAILED, error) from None
    return {
        "command": "sqlite-backup",
        "storage_backend": "sqlite",
        "result": "created",
        "graph_id": graph.id,
        "schema_version": manifest.schema_version,
        **_publication_fields(manifest.publication),
        "database_bytes": manifest.database_bytes,
        "database_sha256": manifest.database_sha256,
    }


def _nearest_directory(path: Path) -> Path:
    while not path.is_dir() and path.parent != path:
        path = path.parent
    return path


def restore_local_graph(
    config: LocalSqliteConfig, graph_id: str, backup: str | Path
) -> dict[str, Any]:
    """Validate ``backup`` fully, then install it at ``graph_id``'s absent target."""
    graph = _graph(config, graph_id)
    binding = local_graph_binding(graph)
    try:
        target = mutable_local_state(config, graph).database
        source = Path(os.path.abspath(Path(backup).expanduser()))
        manifest = verify_backup(source, binding)
        require_absent_target(target)
        fsync_directory(_nearest_directory(target.parent))  # durability probe, no side effect
        with publisher_lock(target):
            publication = install_backup(
                source,
                manifest,
                target,
                binding,
                durable_ancestors=len(SQLITE_GRAPH_STORE_RELATIVE.parts),
            )
    except OSError as error:
        raise _io_failure(RESTORE_IO_FAILED, error) from None
    return {
        "command": "sqlite-restore",
        "storage_backend": "sqlite",
        "result": "restored",
        "graph_id": graph.id,
        "schema_version": manifest.schema_version,
        "schema_state": "current" if manifest.schema_version == current_version() else "behind",
        **_publication_fields(publication),
        "database_sha256": manifest.database_sha256,
    }


def upgrade_local_graph(
    config: LocalSqliteConfig, graph_id: str, backup_output: str | Path
) -> dict[str, Any]:
    """Explicitly migrate ``graph_id``'s exact-behind database, backup first."""
    graph = _graph(config, graph_id)
    try:
        path = mutable_local_state(config, graph).database
        if not path.is_file():
            raise LocalStoreError(NOT_INITIALIZED, "run ops sqlite-init for this graph first")
        target = _output_path(config, backup_output)
        with publisher_lock(path):
            outcome = upgrade_graph_database(
                path,
                local_graph_binding(graph),
                target,
                created_at=utc_timestamp(),
                applied_at=utc_timestamp(),
            )
    except OSError as error:
        raise _io_failure(UPGRADE_IO_FAILED, error) from None
    return {
        "command": "sqlite-upgrade",
        "storage_backend": "sqlite",
        "result": outcome.result,
        "graph_id": graph.id,
        "from_schema_version": outcome.from_version,
        "schema_version": outcome.schema_version,
        **_publication_fields(outcome.publication),
        "backup_created": outcome.backup is not None,
        "backup_database_sha256": None if outcome.backup is None else outcome.backup.database_sha256,
    }


__all__ = (
    "BACKUP_IO_FAILED",
    "LocalBackupError",
    "RESTORE_IO_FAILED",
    "UPGRADE_IO_FAILED",
    "backup_local_graph",
    "restore_local_graph",
    "upgrade_local_graph",
)
