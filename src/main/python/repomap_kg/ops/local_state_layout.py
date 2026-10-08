"""The SQLite Local ``state/`` integrity rule for mutation owners (LOCAL10).

Mutation-owned Local state must be a real, owner-controlled ``state/`` tree
directly under the resolved home. ``sqlite-init``, ``refresh-graph`` (and so
``refresh-enabled``), ``sqlite-backup``, ``sqlite-restore``, ``sqlite-upgrade``
and ``sqlite-cleanup`` check it before any lock or mutation: every existing
level from ``state`` down to the paths they use must be a real directory of
this uid, not a symlink, and the graph database must resolve inside
``state/sqlite-local/graphs``. A symlinked home still works (it is resolved
first); a symlinked ``state``, even one whose target is itself named
``state``, refuses. Nothing is relinked or migrated. The refusal is path-free.

Read-only paths (config checks, readiness and MCP reads) never call this
check. It is a Local-home integrity rule, not a filesystem sandbox. Ownership
is a POSIX uid; a host without one refuses because it cannot be verified.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from repomap_kg.ops.config_local import LocalSqliteConfig, sqlite_graph_database_path
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_kg.storage.sqlite_local.schema import LocalStoreError

LOCAL_STAGE_ID = "sqlite-local"
LOCAL_STATE_LAYOUT_INVALID = "local-state-layout-invalid"


def attempts_namespace(graph_id: str) -> str:
    """The per-graph retained-attempt namespace; graph ids are path-safe."""
    return f"{LOCAL_STAGE_ID}/{graph_id}"


@dataclass(frozen=True)
class LocalStateLayout:
    """The exact Local paths of one graph under the resolved home (pure paths)."""

    home: Path
    state: Path
    legacy: Path
    graph_attempts: Path
    store: Path
    database: Path


def local_state_layout(config: LocalSqliteConfig, graph: OpsGraphConfig) -> LocalStateLayout:
    database = sqlite_graph_database_path(config, graph)
    home = config.control_root.resolve()
    state = home / "state"
    publication = state / "portable-publication"
    return LocalStateLayout(
        home=home,
        state=state,
        legacy=publication / "attempts",
        graph_attempts=publication / attempts_namespace(graph.id) / "attempts",
        store=state / "sqlite-local" / "graphs",
        database=database,
    )


def _current_uid() -> int | None:
    getuid = getattr(os, "getuid", None)
    return None if getuid is None else int(getuid())


def _absent_or_owned(path: Path, uid: int) -> bool:
    try:
        details = os.lstat(path)
    except FileNotFoundError:
        return True
    except NotADirectoryError:
        return False  # a level above it is not a directory
    return stat.S_ISDIR(details.st_mode) and details.st_uid == uid


def require_private_levels(
    layout: LocalStateLayout, *targets: Path, code: str = LOCAL_STATE_LAYOUT_INVALID
) -> None:
    """Refuse unless every existing level from ``state`` to each target is a real owned directory."""
    uid = _current_uid()
    if uid is None:
        raise LocalStoreError(code, "Local state ownership cannot be verified on this platform")
    levels = {layout.state}
    for target in targets:
        levels.add(target)
        levels.update(parent for parent in target.parents if parent.is_relative_to(layout.state))
    if (
        not layout.home.is_dir()
        or layout.database.parent != layout.store
        or not all(_absent_or_owned(level, uid) for level in levels)
    ):
        raise LocalStoreError(code, "a Local state level is not a private directory")


def mutable_local_state(
    config: LocalSqliteConfig, graph: OpsGraphConfig, *, attempts: bool = False
) -> LocalStateLayout:
    """The graph's layout after checking the store (and with ``attempts`` its attempt levels)."""
    layout = local_state_layout(config, graph)
    require_private_levels(layout, layout.store, *((layout.graph_attempts,) if attempts else ()))
    return layout


__all__ = (
    "LOCAL_STAGE_ID",
    "LOCAL_STATE_LAYOUT_INVALID",
    "LocalStateLayout",
    "attempts_namespace",
    "local_state_layout",
    "mutable_local_state",
    "require_private_levels",
)
