"""SQLite Local ``ops sqlite-cleanup``: conservative state hygiene for one graph (LOCAL9).

SQLite-only, source-blind and driver-free like the other ``ops sqlite-*``
commands. Nothing outside the selected home's exact Local namespaces is ever
listed: the graph's attempts
(``state/portable-publication/sqlite-local/<graph>/attempts``), the pre-LOCAL3
shared attempts (``state/portable-publication/attempts``) and this graph's
names in the graph store directory. Every existing level of those paths must
be a real directory of this uid; a symlink anywhere refuses
``sqlite-cleanup-layout-invalid`` before any inventory (the shared LOCAL10
rule of :mod:`.local_state_layout`, under cleanup's own code).

Without ``--yes`` the command is a dry run: it takes no lock that would create
a file (an existing lock file is probed read-only through the shared graph
lock owner, so a held lock still refuses ``graph-publication-in-progress``)
and writes, removes, chmods and syncs nothing. The one exception, shared with ``graphs --check-db``,
is that reading the final database (only when an orphan needs it classified)
may create or keep that database's own ``-wal``/``-shm``.

With ``--yes``, under the graph's publisher lock, the full inventory comes
first. Any unsafe item refuses the whole run (``refused``) before anything is
removed or synced. Otherwise it removes graph-local and shared expired
terminal attempts (never an unsettled or record-less one, whatever graph or
backend it came from) and removable orphans (see
:mod:`repomap_kg.storage.sqlite_local.orphans`), then fsyncs ``state/`` and the
home so the existing ``state`` entry is durable from this operation on. That is
current durability, not proof that an older home was ever synced; nothing
above the home is synced. A failed removal or sync is ``incomplete``, never
``cleaned``. Removals themselves are not claimed durable: a removal lost to
power loss is classified identically and removed by the next run.

With no graph store directory there is no database and no lock file to take
(LOCAL10, an accepted special case): none is created to satisfy locking, only
the qualified attempt actions run (each removal revalidates the exact attempt
identity), refresh cannot publish without a store, and orphans stay
``not-inspected`` even if a store appears during the run.

The payload holds counts and bounded codes only: no path, entry name, token or
record content.
"""

from __future__ import annotations

import errno
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from repomap_kg.ops._portable_retention import (
    EXPIRED_TERMINAL,
    INCOMPLETE,
    RETAINED_TERMINAL,
    UNSAFE,
    UNSETTLED,
    RetainedAttempt,
    classify_retained_attempts,
    remove_expired_terminal_attempt,
)
from repomap_kg.ops.config_local import LocalSqliteConfig, local_graph_binding
from repomap_kg.ops.config_records import OpsGraphConfig
from repomap_kg.ops.local_state_layout import local_state_layout, require_private_levels
from repomap_kg.storage.sqlite_local import orphans
from repomap_kg.storage.sqlite_local.connection import publisher_lock
from repomap_kg.storage.sqlite_local.durability import fsync_directory_chain
from repomap_kg.storage.sqlite_local.locking import probe_graph_lock
from repomap_kg.storage.sqlite_local.schema import LocalGraphBinding, LocalStoreError

CLEANUP_LAYOUT_INVALID = "sqlite-cleanup-layout-invalid"
CLEANUP_IO_FAILED = "sqlite-cleanup-io-failed"


class LocalCleanupError(ValueError):
    """Bounded cleanup command refusal (unknown graph)."""


def _graph(config: LocalSqliteConfig, graph_id: str) -> OpsGraphConfig:
    for graph in config.graphs:
        if graph.id == graph_id:
            return graph
    raise LocalCleanupError(f"unknown graph_id: {graph_id}")


def _layout(config: LocalSqliteConfig, graph: OpsGraphConfig) -> tuple[dict[str, Path], Path]:
    """The exact namespace paths, each an absent or real owner directory, and the database."""
    layout = local_state_layout(config, graph)
    require_private_levels(
        layout, layout.store, layout.graph_attempts, layout.legacy, code=CLEANUP_LAYOUT_INVALID
    )
    paths = {
        "state": layout.state,
        "legacy": layout.legacy,
        "graph": layout.graph_attempts,
        "store": layout.store,
    }
    return paths, layout.database


@contextmanager
def _graph_lock(database: Path, *, execute: bool) -> Iterator[bool]:
    """Yield whether the store existed when the lock was decided (not whether a lock is held).

    ``--yes`` takes the publisher lock; a dry run probes an existing lock file
    and never creates one. Without a store there is nothing to lock and no
    lock file is created (see the module docstring).
    """
    if not os.path.lexists(database.parent):
        yield False
        return
    if execute:
        with publisher_lock(database):
            yield True
        return
    with probe_graph_lock(database):
        yield True


def cleanup_local_graph(
    config: LocalSqliteConfig, graph_id: str, *, execute: bool
) -> dict[str, Any]:
    """Inventory (and with ``execute`` clean) one graph's Local state."""
    graph = _graph(config, graph_id)
    try:
        paths, database = _layout(config, graph)
        with _graph_lock(database, execute=execute) as store_present:
            return _Cleanup(graph.id, paths, database, execute).run(local_graph_binding(graph), store_present)
    except OSError as error:
        raise LocalStoreError(CLEANUP_IO_FAILED, errno.errorcode.get(error.errno or 0, "unknown-error")) from None


class _Cleanup:
    def __init__(self, graph_id: str, paths: dict[str, Path], database: Path, execute: bool) -> None:
        self.graph_id, self.paths, self.database, self.execute = graph_id, paths, database, execute
        self.now = int(time.time())
        self.warnings: set[str] = set()
        self.refusals: set[str] = set()
        self.failures: set[str] = set()
        self.removed = {"graph": 0, "legacy": 0, "orphans": 0, "orphan_partial": 0}

    def _attempts(self, key: str) -> list[RetainedAttempt]:
        parent = self.paths[key]
        return classify_retained_attempts(parent, now=self.now) if os.path.lexists(parent) else []

    def run(self, binding: LocalGraphBinding, store_present: bool) -> dict[str, Any]:
        graph_attempts, legacy_attempts = self._attempts("graph"), self._attempts("legacy")
        store = self.paths["store"]
        # A store that appeared after the lock decision is unlocked: never inspect it.
        if not store_present or not os.path.lexists(store):
            return self._finish(graph_attempts, legacy_attempts, orphans.OrphanInventory("not-inspected", ()))
        with orphans.pinned_store(store) as descriptor:
            inventory = orphans.inventory_orphans(descriptor, self.database, binding)
            return self._finish(graph_attempts, legacy_attempts, inventory, descriptor)

    def _finish(
        self,
        graph_attempts: list[RetainedAttempt],
        legacy_attempts: list[RetainedAttempt],
        inventory: orphans.OrphanInventory,
        descriptor: int | None = None,
    ) -> dict[str, Any]:
        self._note(graph_attempts, legacy_attempts, inventory)
        if not self.execute:
            result, durability = "dry-run", "not-attempted"
        elif self.refusals:
            result, durability = "refused", "not-attempted"
        else:
            self._remove_attempts("graph", graph_attempts)
            self._remove_attempts("legacy", legacy_attempts)
            if descriptor is not None:
                self._remove_orphans(descriptor, inventory)
            durability = self._establish_durability()
            result = "incomplete" if self.failures else "cleaned"
        return self._payload(result, durability, graph_attempts, legacy_attempts, inventory)

    def _note(
        self,
        graph_attempts: list[RetainedAttempt],
        legacy_attempts: list[RetainedAttempt],
        inventory: orphans.OrphanInventory,
    ) -> None:
        for items, unsafe, unsettled, incomplete in (
            (graph_attempts, "unsafe-graph-attempt", "graph-attempt-unsettled", "graph-attempt-incomplete"),
            (legacy_attempts, "unsafe-legacy-attempt", "legacy-unresolved-attempt", "legacy-incomplete-attempt"),
        ):
            statuses = {item.status for item in items}
            if UNSAFE in statuses:
                self.refusals.add(unsafe)
            self.warnings.update(
                code for status, code in ((UNSETTLED, unsettled), (INCOMPLETE, incomplete)) if status in statuses
            )
        groups = [group.status for group in inventory.groups]
        if orphans.UNSAFE in groups:
            self.refusals.add("unsafe-orphan")
        self.warnings.update(
            code
            for present, code in (
                (orphans.RECOVERABLE in groups, "recoverable-orphan"),
                (groups.count(orphans.RECOVERABLE) > 1, "multiple-recoverable-orphans"),
                (orphans.UNRECOGNIZED in groups, "unrecognized-orphan-preserved"),
                (orphans.HELD in groups, "final-database-not-valid"),
            )
            if present
        )

    def _remove_attempts(self, key: str, items: list[RetainedAttempt]) -> None:
        for item in items:
            if item.status != EXPIRED_TERMINAL:
                continue
            try:
                remove_expired_terminal_attempt(self.paths[key] / item.name, item.identity, now=self.now)
            except (OSError, RuntimeError, ValueError):
                self.failures.add("attempt-removal-failed")
            else:
                self.removed[key] += 1

    def _remove_orphans(self, descriptor: int, inventory: orphans.OrphanInventory) -> None:
        for group in inventory.groups:
            if group.status not in orphans.REMOVABLE:
                continue
            try:
                orphans.remove_orphan(descriptor, group)
            except (OSError, RuntimeError, ValueError):
                self.failures.add("orphan-removal-failed")
            else:
                self.removed["orphan_partial" if group.status == orphans.PARTIAL else "orphans"] += 1

    def _establish_durability(self) -> str:
        """Sync ``state/`` and then the home: current durability, never history."""
        if not os.path.lexists(self.paths["state"]):
            return "not-applicable"
        try:
            fsync_directory_chain(self.paths["state"], 1)
        except LocalStoreError as error:
            self.failures.add(error.code)
            return error.code
        return "established"

    def _payload(
        self,
        result: str,
        durability: str,
        graph_attempts: list[RetainedAttempt],
        legacy_attempts: list[RetainedAttempt],
        inventory: orphans.OrphanInventory,
    ) -> dict[str, Any]:
        groups = [group.status for group in inventory.groups]
        graph_counts = _attempt_counts(graph_attempts, self.removed["graph"])
        graph_counts["unsettled_preserved"] = graph_counts.pop("unsettled")
        legacy_counts = _attempt_counts(legacy_attempts, self.removed["legacy"])
        legacy_counts["unresolved_preserved"] = legacy_counts.pop("unsettled")
        return {
            "command": "sqlite-cleanup",
            "storage_backend": "sqlite",
            "graph_id": self.graph_id,
            "result": result,
            "dry_run": not self.execute,
            "changed": any(self.removed.values()),
            "final_database": inventory.final_state,
            "graph_attempts": graph_counts,
            "legacy_shared_attempts": legacy_counts,
            "orphans": {
                "stale_found": groups.count(orphans.STALE) + groups.count(orphans.STALE_LINK),
                "stale_removed": self.removed["orphans"],
                "partial_found": groups.count(orphans.PARTIAL),
                "partial_removed": self.removed["orphan_partial"],
                "recoverable_preserved": groups.count(orphans.RECOVERABLE),
                "unrecognized_preserved": groups.count(orphans.UNRECOGNIZED),
                "held_preserved": groups.count(orphans.HELD),
                "unsafe": groups.count(orphans.UNSAFE),
            },
            "durability": durability,
            "manual_recovery_required": bool(
                legacy_counts["unresolved_preserved"]
                or {orphans.RECOVERABLE, orphans.UNRECOGNIZED, orphans.HELD} & set(groups)
            ),
            "warning_count": len(self.warnings),
            "warnings": sorted(self.warnings),
            "refusal_count": len(self.refusals),
            "refusals": sorted(self.refusals),
            "failures": sorted(self.failures),
        }


def _attempt_counts(items: list[RetainedAttempt], removed: int) -> dict[str, int]:
    statuses = [item.status for item in items]
    return {
        "expired_terminal_found": statuses.count(EXPIRED_TERMINAL),
        "expired_terminal_removed": removed,
        "retained_terminal": statuses.count(RETAINED_TERMINAL),
        "unsettled": statuses.count(UNSETTLED),
        "incomplete_preserved": statuses.count(INCOMPLETE),
        "unsafe": statuses.count(UNSAFE),
    }


__all__ = (
    "CLEANUP_IO_FAILED",
    "CLEANUP_LAYOUT_INVALID",
    "LocalCleanupError",
    "cleanup_local_graph",
)
