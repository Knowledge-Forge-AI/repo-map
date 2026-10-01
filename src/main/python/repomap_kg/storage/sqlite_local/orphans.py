"""Orphan SQLite Local initialization and restore temporaries (LOCAL9).

``initialize_graph_database`` builds ``.<name>.init-<16 hex>`` and
``install_backup`` copies into ``.<name>.restore-<16 hex>`` beside the final
database ``<name>`` (``<graph_id>.sqlite3``). A crash can leave either,
possibly with the sidecars its owner removes in its own cleanup: ``-wal`` and
``-shm`` for init, ``-wal``, ``-shm`` and ``-journal`` for restore. Only names
matching exactly those patterns for this graph are inventoried, through one
pinned store directory descriptor; the final database, its sidecars, its lock
and every other graph's names never match.

Structure: every member must be a regular, owner-only file of this uid with
one link. The one exception is the base name of an orphan left after install,
a second link to the final database's own inode. Anything else is ``unsafe``
and the caller refuses the whole cleanup.

Classification against the final database:

* current or behind: every orphan is ``stale`` and removable. A second link
  without sidecars loses only its orphan name (``stale-link``); a second link
  with sidecars was opened by some SQLite client and is ``unsafe``.
* absent (no database and none of its sidecars): a group with a non-empty
  ``-wal`` or any ``-journal`` may hold content outside its base and is
  ``unrecognized``. Otherwise empty sidecars without a base, and a base that
  is structurally incomplete (shorter than a header, not a SQLite header, not
  WAL-marked, shorter than its header's page count), are ``partial`` and
  removable. A structurally complete base that opens immutable as an
  exact-current or exact-behind database of this graph is ``recoverable``;
  any other base, and any failure to inspect one, is ``unrecognized``. Both
  are preserved.
* anything else (refused, busy, or sidecars without a database): ``held``.

Nothing is ever linked, renamed or adopted into the final path. Removal
re-checks each name's identity through the pinned descriptor and unlinks it
relative to that descriptor; the final database is only read.
"""

from __future__ import annotations

import os
import re
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from repomap_kg.storage.sqlite_local.backup import inspect_sealed_database, owned_names
from repomap_kg.storage.sqlite_local.connection import read_transaction
from repomap_kg.storage.sqlite_local.migrations import classify
from repomap_kg.storage.sqlite_local.schema import (
    DATABASE_UNAVAILABLE,
    LocalGraphBinding,
    LocalStoreError,
)

STALE = "stale"
STALE_LINK = "stale-link"
PARTIAL = "partial"
RECOVERABLE = "recoverable"
UNRECOGNIZED = "unrecognized"
HELD = "held"
UNSAFE = "unsafe"
REMOVABLE = frozenset({STALE, STALE_LINK, PARTIAL})
_VALID = ("current", "behind")

# The exact sidecar sets each owner's own cleanup removes.
_OWNER_SUFFIXES = {"init": ("-wal", "-shm"), "restore": ("-wal", "-shm", "-journal")}
_HEADER = b"SQLite format 3\x00"
_HEADER_BYTES = 100


class OrphanChanged(RuntimeError):
    """An inventoried orphan name no longer has its inventoried identity."""


@dataclass
class OrphanGroup:
    """One orphan temporary and its sidecars; names are operator-private."""

    kind: str
    base: str
    members: dict[str, os.stat_result] = field(default_factory=dict)
    status: str = UNSAFE


@dataclass(frozen=True)
class OrphanInventory:
    final_state: str  # current, behind, absent, not-valid or not-inspected (no orphans)
    groups: tuple[OrphanGroup, ...]


def _match(database_name: str, entry: str) -> tuple[str, str] | None:
    """``(kind, base name)`` when ``entry`` is one of this database's owned temporary names."""
    for kind, suffixes in _OWNER_SUFFIXES.items():
        alternatives = "|".join(re.escape(suffix) for suffix in suffixes)
        found = re.fullmatch(
            rf"(\.{re.escape(database_name)}\.{kind}-[0-9a-f]{{16}})(?:{alternatives})?", entry
        )
        if found is not None:
            return kind, found.group(1)
    return None


@contextmanager
def pinned_store(directory: Path) -> Iterator[int]:
    """Open the graph store directory once, refusing a symlink or a foreign owner."""
    expected = os.lstat(directory)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino) or (
            opened.st_uid != os.getuid()
        ):
            raise LocalStoreError(DATABASE_UNAVAILABLE, "graph store directory is not private")
        yield descriptor
    finally:
        os.close(descriptor)


def inventory_orphans(
    store: int, database: Path, binding: LocalGraphBinding
) -> OrphanInventory:
    """Group and classify this graph's orphan temporaries; nothing is changed.

    The final database is opened (read-only) only when an orphan exists.
    """
    groups: dict[str, OrphanGroup] = {}
    for entry in sorted(os.listdir(store)):
        matched = _match(database.name, entry)
        if matched is not None:
            group = groups.setdefault(matched[1], OrphanGroup(matched[0], matched[1]))
            group.members[entry] = os.stat(entry, dir_fd=store, follow_symlinks=False)
    if not groups:
        return OrphanInventory("not-inspected", ())
    final_state, final_identity = _final_state(database, binding)
    for group in groups.values():
        group.status = _classify(store, database.parent, group, final_state, final_identity, binding)
    return OrphanInventory(final_state, tuple(groups.values()))


def _final_state(
    database: Path, binding: LocalGraphBinding
) -> tuple[str, tuple[int, int] | None]:
    try:
        details = os.lstat(database)
    except FileNotFoundError:
        if any(os.path.lexists(name) for name in owned_names(database)[1:]):
            return "not-valid", None
        return "absent", None
    identity = (details.st_dev, details.st_ino) if stat.S_ISREG(details.st_mode) else None
    try:
        with read_transaction(database, binding, accept_behind=True) as connection:
            kind = classify(connection).kind
    except (LocalStoreError, OSError):
        return "not-valid", identity
    return kind, identity


def _owner_file(details: os.stat_result, *, links: int) -> bool:
    return (
        stat.S_ISREG(details.st_mode)
        and details.st_uid == os.getuid()
        and not details.st_mode & 0o077
        and details.st_nlink == links
    )


def _classify(
    store: int,
    directory: Path,
    group: OrphanGroup,
    final_state: str,
    final_identity: tuple[int, int] | None,
    binding: LocalGraphBinding,
) -> str:
    base = group.members.get(group.base)
    second_link = base is not None and (base.st_dev, base.st_ino) == final_identity
    for name, details in group.members.items():
        if not _owner_file(details, links=2 if name == group.base and second_link else 1):
            return UNSAFE
    sidecars = {name: details for name, details in group.members.items() if name != group.base}
    if second_link and sidecars:
        return UNSAFE
    if final_state in _VALID:
        return STALE_LINK if second_link else STALE
    if final_state != "absent":
        return HELD
    if any(
        name.endswith("-journal") or (name.endswith("-wal") and details.st_size)
        for name, details in sidecars.items()
    ):
        return UNRECOGNIZED  # content may live outside the base; never judged
    try:
        if base is None or _structurally_incomplete(store, group.base, base):
            return PARTIAL
    except (OSError, OrphanChanged):
        return UNSAFE
    try:
        inspect_sealed_database(directory / group.base, binding)
    except (LocalStoreError, OSError, sqlite3.Error, ValueError):
        return UNRECOGNIZED
    return RECOVERABLE


def _structurally_incomplete(store: int, name: str, details: os.stat_result) -> bool:
    """True only for a base the maintained writers can leave but never complete."""
    if details.st_size < _HEADER_BYTES:
        return True
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=store)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (details.st_dev, details.st_ino):
            raise OrphanChanged("orphan identity changed")
        header = os.pread(descriptor, _HEADER_BYTES, 0)
    finally:
        os.close(descriptor)
    if len(header) < _HEADER_BYTES or header[:16] != _HEADER or header[18:20] != b"\x02\x02":
        return True
    page_size = int.from_bytes(header[16:18], "big")
    page_size = 65536 if page_size == 1 else page_size
    pages = int.from_bytes(header[28:32], "big")
    if page_size < 512 or page_size & (page_size - 1) or header[24:28] != header[92:96]:
        return False  # the header's page count is not authoritative; inspection decides
    return 0 < pages and details.st_size < pages * page_size


def remove_orphan(store: int, group: OrphanGroup) -> None:
    """Unlink one removable group's names (only the orphan name of a second link)."""
    if group.status not in REMOVABLE:
        raise ValueError("orphan is not removable")
    names = [group.base] if group.status == STALE_LINK else sorted(
        group.members, key=lambda name: name == group.base
    )
    for name in names:
        expected = group.members[name]
        current = os.stat(name, dir_fd=store, follow_symlinks=False)
        if (
            current.st_dev, current.st_ino, current.st_nlink, current.st_uid, stat.S_IFMT(current.st_mode)
        ) != (
            expected.st_dev, expected.st_ino, expected.st_nlink, expected.st_uid, stat.S_IFMT(expected.st_mode)
        ):
            raise OrphanChanged("orphan identity changed")
        os.unlink(name, dir_fd=store)


__all__ = (
    "HELD",
    "OrphanChanged",
    "OrphanGroup",
    "OrphanInventory",
    "PARTIAL",
    "RECOVERABLE",
    "REMOVABLE",
    "STALE",
    "STALE_LINK",
    "UNRECOGNIZED",
    "UNSAFE",
    "inventory_orphans",
    "pinned_store",
    "remove_orphan",
)
