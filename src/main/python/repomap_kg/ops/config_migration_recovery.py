"""CLOE migration recovery: entry classification, rollback, proofs and owned teardown (ADR 0114)."""
from __future__ import annotations

import hashlib
import stat
from typing import Any

from repomap_kg.ops.config_layout import classify_config_filename, portable_config_name
from repomap_kg.ops.config_migration_fs import (
    JOURNAL_NAME, JOURNAL_TEMP_NAME, LOCK_NAME, MAX_FILE_BYTES, OPERATION_DIRECTORY, PROBE_NAMES,
    Home, MigrationRefusal, backup_name, ident, owned_regular, restore_name,
)
from repomap_kg.ops.config_migration_journal import effective_sha256, read_journal, write_journal

JOURNALLESS_NAMES = frozenset((LOCK_NAME, JOURNAL_TEMP_NAME, *PROBE_NAMES))
ROLLBACK_STATES = ("publishing", "applied", "rolling-back")


def _allowed_names(journal: dict[str, Any] | None) -> frozenset[str]:
    if journal is None:
        return JOURNALLESS_NAMES
    owned = {name(entry["index"]) for entry in journal["entries"] for name in (backup_name, restore_name)}
    return JOURNALLESS_NAMES | {JOURNAL_NAME} | owned


def load_operation(home: Home) -> dict[str, Any] | None:
    """Read the bound operation directory's journal and refuse any name it does not own."""
    journal = read_journal(home)
    unknown = sorted(set(home.names(in_op=True)) - _allowed_names(journal))
    if unknown:
        raise MigrationRefusal("config-migration-residue-unsafe")
    return journal


def _content(home: Home, name: str, entry: dict[str, Any], *, in_op: bool = False) -> bytes | None:
    try:
        data, _ = home.read(name, MAX_FILE_BYTES, "config-migration-drift", in_op=in_op)
    except MigrationRefusal:
        return None
    if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        return None
    return data


def _proved(
    home: Home, name: str, info: Any, entry: dict[str, Any], identities: set[Any], *, links: int = 1, in_op: bool = False,
) -> bytes | None:
    if not owned_regular(info, links=links) or ident(info) not in identities:
        return None
    if stat.S_IMODE(info.st_mode) != entry["mode"]:
        return None
    return _content(home, name, entry, in_op=in_op)


def classify_entry(home: Home, entry: dict[str, Any]) -> tuple[str, bytes]:
    """Classify one entry from fresh observations, independently of the journal position."""
    source, target, staged = entry["source"], entry["target"], restore_name(entry["index"])
    s, t, r = home.lstat(source), home.lstat(target), home.lstat(staged, in_op=True)
    # Recorded devices are evidence only (st_dev may change across reboot): bind recorded inodes to the home's device.
    original = (home.dev, entry["ino"])
    restored = None if entry["restored_ino"] is None else (home.dev, entry["restored_ino"])
    data: bytes | None = None
    if s is not None and t is None and r is None:
        data = _proved(home, source, s, entry, {original, restored})
        if data is not None:
            return "source-only", data
    if s is None and t is not None and r is None:
        data = _proved(home, target, t, entry, {original})
        if data is not None:
            return "target-only", data
    if s is not None and t is not None and r is None and ident(s) == ident(t):
        data = _proved(home, source, s, entry, {original}, links=2)
        if data is not None:
            return "dual-link", data
    if s is None and t is None and r is not None:
        if restored is not None:
            data = _proved(home, staged, r, entry, {restored}, in_op=True)
            if data is not None:
                return "restore-staged", data
        if owned_regular(r) and ident(r) != restored:
            backup = backup_name(entry["index"])
            if (
                owned_regular(home.lstat(backup, in_op=True))
                and _content(home, backup, entry, in_op=True) is not None
            ):
                return "restore-scratch", b""
    if s is not None and t is None and r is not None and restored is not None and ident(s) == ident(r):
        data = _proved(home, source, s, entry, {restored}, links=2)
        if data is not None:
            return "restored-dual", data
    if s is None and t is None and r is None:
        backup = backup_name(entry["index"])
        info = home.lstat(backup, in_op=True)
        if owned_regular(info):
            data = _content(home, backup, entry, in_op=True)
            if data is not None:
                return "both-missing", data
    raise MigrationRefusal("config-migration-drift", source)


def check_foreign(home: Home, journal: dict[str, Any]) -> None:
    """Refuse configuration-family names, or portable aliases, that the journal does not own."""
    owned = {entry[key] for entry in journal["entries"] for key in ("source", "target")}
    portable = {portable_config_name(name) for name in owned}
    for name in home.names():
        if name == OPERATION_DIRECTORY or name in owned:
            continue
        if classify_config_filename(name) is not None or portable_config_name(name) in portable:
            raise MigrationRefusal("config-migration-drift", name)


def _prove(home: Home, journal: dict[str, Any], expected: str, key: str, order: list[str]) -> None:
    check_foreign(home, journal)
    contents: dict[str, bytes] = {}
    for entry in journal["entries"]:
        state, data = classify_entry(home, entry)
        if state != expected:
            raise MigrationRefusal("config-migration-drift", entry["source"])
        contents[entry[key]] = data
    if effective_sha256([(name, contents[name]) for name in order]) != journal["effective_sha256"]:
        raise MigrationRefusal("config-migration-drift")


def prove_targets(home: Home, journal: dict[str, Any]) -> None:
    """Applied-state proof: exactly the targets, original inodes and bytes, same effective digest."""
    _prove(home, journal, "target-only", "target", journal["proposed_order"])


def prove_sources(home: Home, journal: dict[str, Any]) -> None:
    _prove(home, journal, "source-only", "source", journal["source_order"])


def preview_rollback(home: Home, journal: dict[str, Any]) -> None:
    """Classify every entry before any action; any ambiguous entry refuses the whole operation."""
    check_foreign(home, journal)
    for entry in journal["entries"]:
        classify_entry(home, entry)


def _expect(home: Home, name: str, identity: Any, links: int) -> None:
    info = home.lstat(name)
    if info is None or ident(info) != identity or info.st_nlink != links:
        raise MigrationRefusal("config-migration-drift", name)


def _restore_entry(home: Home, journal: dict[str, Any], entry: dict[str, Any]) -> None:
    source, target, staged = entry["source"], entry["target"], restore_name(entry["index"])
    original = (home.dev, entry["ino"])
    for _ in range(5):
        state, data = classify_entry(home, entry)
        if state == "source-only":
            return
        if state == "target-only":
            home.link(target, source)
            _expect(home, source, original, 2)
            home.sync()
            home.unlink(target)
            home.sync()
        elif state == "dual-link":
            home.unlink(target)
            home.sync()
        elif state == "restored-dual":
            home.unlink(staged, in_op=True)
            home.sync(in_op=True)
        elif state == "restore-staged":
            home.link(staged, source, source_in_op=True)
            _expect(home, source, (home.dev, entry["restored_ino"]), 2)
            home.sync()
            home.unlink(staged, in_op=True)
            home.sync(in_op=True)
        elif state == "restore-scratch":
            home.unlink(staged, in_op=True)
            home.sync(in_op=True)
        else:
            info = home.create(staged, data, mode=entry["mode"])
            home.sync(in_op=True)
            entry["restored_dev"], entry["restored_ino"] = ident(info)
            write_journal(home, journal)
    raise MigrationRefusal("config-migration-drift", source)


def roll_back(home: Home, journal: dict[str, Any]) -> None:
    """With the lock held: classify all, restore sources in reverse order, prove and mark terminal."""
    preview_rollback(home, journal)
    if journal["state"] != "rolling-back":
        write_journal(home, journal, "rolling-back")
    for entry in reversed(journal["entries"]):
        _restore_entry(home, journal, entry)
    prove_sources(home, journal)
    write_journal(home, journal, "rolled-back")


def teardown(home: Home, journal: dict[str, Any] | None) -> bool:
    """Remove only proved operation-owned names, lock last; return True if the directory was retained."""
    names = home.names(in_op=True)
    if set(names) - _allowed_names(journal):
        raise MigrationRefusal("config-migration-residue-unsafe")
    last = [name for name in (JOURNAL_NAME, LOCK_NAME) if name in names]
    ordered = [name for name in names if name not in last] + last
    infos = {name: home.lstat(name, in_op=True) for name in ordered}
    probes = [infos.get(name) for name in PROBE_NAMES]
    probe_pair = all(owned_regular(info, links=2) for info in probes) and len({ident(i) for i in probes if i}) == 1
    for name in ordered:
        if not (owned_regular(infos[name]) or (name in PROBE_NAMES and probe_pair)):
            raise MigrationRefusal("config-migration-residue-unsafe", name)
    for name in ordered:
        home.unlink(name, in_op=True)
    home.sync(in_op=True)
    removed = home.remove_operation_directory()
    home.sync()
    return not removed
