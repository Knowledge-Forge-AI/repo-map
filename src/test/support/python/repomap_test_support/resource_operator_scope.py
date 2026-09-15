"""Closed physical scope and reconciliation ownership for operator reclaim."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from repomap_test_support.resource_index import AdvisoryIndex
from repomap_test_support.resource_index_recovery import MaintenanceIndexBinding
from repomap_test_support.resource_safe_tree_delete import (
    RunEntryInspection,
    SafeTreeDeleteError,
    inspect_run_entry,
)
from repomap_test_support.resource_safe_tree_pin import (
    EntryPin,
    close_pin,
    pin_run_entry,
)


from repomap_test_support.resource_operator_inventory import (
    COTENANT_ACTIVITY_FIELDS as COTENANT_ACTIVITY_FIELDS,
    OwnedPath as OwnedPath,
    ScopeEntry as ScopeEntry,
    _MAX_AUDIT_PID as _MAX_AUDIT_PID,
    category_counts as category_counts,
    classify_cotenant_activity as classify_cotenant_activity,
    classify_liveness as classify_liveness,
    inventory_digest as inventory_digest,
)

PROJECT = "repo-map_dev"


class OperatorScopeIdentityError(RuntimeError):
    """The immediate operator population cannot be identity-bound safely."""


def bind_operator_root(scratch_root: Path) -> Path:
    root = Path(scratch_root)
    try:
        metadata = root.stat(follow_symlinks=False)
        resolved = root.resolve(strict=True)
    except OSError as error:
        raise ValueError("explicit scratch root is unavailable") from error
    if (
        not root.is_absolute()
        or root.is_symlink()
        or resolved != root
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ValueError("explicit scratch root identity is unsafe")
    runs = root / "r"
    runs_metadata = runs.stat(follow_symlinks=False)
    if (
        runs.is_symlink()
        or not stat.S_ISDIR(runs_metadata.st_mode)
        or runs_metadata.st_uid != os.getuid()
        or runs_metadata.st_dev != metadata.st_dev
    ):
        raise ValueError("selected run directory identity is unsafe")
    return root


def inventory_operator_scope(root: Path) -> tuple[ScopeEntry, ...]:
    """Bind the immediate ``r`` population, pinning each entry it records.

    Callers own every returned pin and must pass the population to
    ``close_scope_pins`` once the reclamation decision is finished.
    """
    runs = root / "r"
    before = _population_snapshot(runs)
    entries: list[ScopeEntry] = []
    try:
        _bind_population(root, before, entries)
        if _population_snapshot(runs) != before:
            raise OperatorScopeIdentityError("run population identity changed")
    except BaseException:
        close_scope_pins(tuple(entries))
        raise
    return tuple(entries)


def close_scope_pins(entries: tuple[ScopeEntry, ...]) -> None:
    """Release every inventory pin; repeat releases are no-ops."""
    for entry in entries:
        close_pin(entry.pin)


def _bind_population(
    root: Path,
    before: tuple[tuple[str, int, int, int], ...],
    entries: list[ScopeEntry],
) -> None:
    folded: set[str] = set()
    for name, device, inode, mode in before:
        if name.casefold() in folded:
            raise OperatorScopeIdentityError(
                "run population casefold identity is ambiguous"
            )
        folded.add(name.casefold())
        pin = _pin_entry(root, name)
        try:
            inspection = _inspect_entry(root, name)
            category, manifest = _classify_entry(root, name)
        except BaseException:
            close_pin(pin)
            raise
        entries.append(ScopeEntry(name, inspection, category, manifest, pin))
        _require_bound_identity(inspection, pin, (device, inode, mode))


def _require_bound_identity(
    inspection: RunEntryInspection,
    pin: EntryPin | None,
    expected: tuple[int, int, int],
) -> None:
    if (inspection.device, inspection.inode, inspection.mode) != expected:
        raise OperatorScopeIdentityError("run entry identity changed")
    if pin is not None and (pin.device, pin.inode, pin.mode) != expected:
        raise OperatorScopeIdentityError("run entry pin identity changed")


def _pin_entry(root: Path, name: str) -> EntryPin | None:
    try:
        return pin_run_entry(root, name)
    except SafeTreeDeleteError as error:
        raise OperatorScopeIdentityError(
            "run entry pin identity is unsafe"
        ) from error


def _inspect_entry(root: Path, name: str) -> RunEntryInspection:
    try:
        return inspect_run_entry(root, name)
    except SafeTreeDeleteError as error:
        raise OperatorScopeIdentityError(
            "run entry inspection identity is unsafe"
        ) from error


def capture_protections(
    root: Path, entries: tuple[ScopeEntry, ...]
) -> tuple[tuple[OwnedPath, ...], int]:
    names = {entry.name for entry in entries}
    owned = []
    pins = 0
    base = root / ".protections" / PROJECT
    for kind in ("pins", "reports", "monitoring"):
        directory = base / kind
        if not directory.exists():
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("protection authority is unsafe")
        for path in directory.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                raise ValueError("protection record is unsafe")
            if path.stem not in names:
                continue
            metadata = path.stat(follow_symlinks=False)
            owned.append(
                OwnedPath(
                    path,
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_mode,
                    owner_names=(path.stem,),
                )
            )
            if kind == "pins":
                pins += 1
    return tuple(owned), pins


def capture_monitoring(
    root: Path, entries: tuple[ScopeEntry, ...]
) -> tuple[OwnedPath, ...]:
    names = {entry.name for entry in entries}
    base = root / "index" / PROJECT
    if not base.exists():
        return ()
    if base.is_symlink() or not base.is_dir():
        raise ValueError("monitoring authority is unsafe")
    owned = []
    for phase in base.iterdir():
        if phase.is_symlink() or not phase.is_dir():
            raise ValueError("monitoring phase authority is unsafe")
        for link in phase.iterdir():
            if not link.is_symlink():
                raise ValueError("monitoring entry is unsafe")
            target = link.resolve(strict=False)
            owner_names = set()
            if link.name in names:
                owner_names.add(link.name)
            owner_names.update(
                entry.name
                for entry in entries
                if (
                    target == root / "r" / entry.name
                    or root / "r" / entry.name in target.parents
                )
            )
            if not owner_names:
                continue
            metadata = link.stat(follow_symlinks=False)
            owned.append(
                OwnedPath(
                    link,
                    metadata.st_dev,
                    metadata.st_ino,
                    metadata.st_mode,
                    link_target=target,
                    owner_names=tuple(sorted(owner_names)),
                )
            )
    return tuple(owned)


def quarantined_run_names(root: Path) -> frozenset[str]:
    """Return exact preserved quarantine identities without reading payloads."""
    base = root / ".quarantine" / PROJECT
    if not base.exists():
        return frozenset()
    if base.is_symlink() or not base.is_dir():
        raise ValueError("quarantine authority is unsafe")
    names = set()
    for entry in base.iterdir():
        if entry.is_symlink() or not entry.is_dir():
            raise ValueError("quarantine entry identity is unsafe")
        names.add(entry.name)
    return frozenset(names)


def capture_index_records(
    binding: MaintenanceIndexBinding, entries: tuple[ScopeEntry, ...]
) -> tuple[OwnedPath, ...]:
    names = {entry.name for entry in entries}
    owned = []
    index = AdvisoryIndex(binding.root, binding.scratch_root)
    for path in sorted(binding.records_path.iterdir(), key=lambda item: item.name):
        parts = path.name.rsplit(".", 2)
        if len(parts) != 3 or parts[2] != "json" or parts[0] not in names:
            continue
        kind, run_id, _payload = index._read_record(path)
        if run_id != parts[0] or kind != parts[1]:
            raise ValueError("index record identity is unsafe")
        metadata = path.stat(follow_symlinks=False)
        owned.append(
            OwnedPath(
                path,
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                owner_names=(run_id,),
                record_kind=kind,
            )
        )
    return tuple(owned)


def unlink_owned(owned: OwnedPath) -> None:
    metadata = owned.path.stat(follow_symlinks=False)
    if (metadata.st_dev, metadata.st_ino, metadata.st_mode) != (
        owned.device, owned.inode, owned.mode
    ):
        raise ValueError("reconciliation identity changed")
    if owned.link_target is not None and (
        not owned.path.is_symlink()
        or owned.path.resolve(strict=False) != owned.link_target
    ):
        raise ValueError("monitoring identity changed")
    owned.path.unlink()
    fsync_directory(owned.path.parent)


def ensure_private_directory(path: Path) -> None:
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
    for directory in (path, *path.parents):
        if directory == directory.parent:
            break
        metadata = directory.stat(follow_symlinks=False)
        if directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError("operator evidence directory is unsafe")
        if directory == path or ".operator-reclamation" in directory.parts:
            if stat.S_IMODE(metadata.st_mode) != 0o700:
                raise ValueError("operator evidence directory is not private")
        if directory.name == ".operator-reclamation":
            break


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _population_snapshot(root: Path) -> tuple[tuple[str, int, int, int], ...]:
    values = []
    for path in root.iterdir():
        metadata = path.stat(follow_symlinks=False)
        values.append((path.name, metadata.st_dev, metadata.st_ino, metadata.st_mode))
    return tuple(sorted(values))


def _classify_entry(root: Path, name: str) -> tuple[str, dict | None]:
    path = root / "r" / name
    if not path.is_dir() or path.is_symlink():
        return "opaque", None
    manifest_path = path / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        return "ambiguous", None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "ambiguous", None
    if not isinstance(manifest, dict):
        return "ambiguous", None
    if manifest.get("project") not in {None, PROJECT}:
        return "foreign", manifest
    exact = (
        manifest.get("schema") == "repomap-test-scratch-manifest-v1"
        and manifest.get("project") == PROJECT
        and manifest.get("run_kind") == "test"
        and manifest.get("run_id") == name
        and isinstance(manifest.get("phase"), str)
        and Path(manifest.get("physical_run_root", "")) == path
    )
    return ("valid" if exact else "ambiguous"), manifest


__all__ = [
    "COTENANT_ACTIVITY_FIELDS", "OperatorScopeIdentityError", "OwnedPath", "ScopeEntry",
    "classify_cotenant_activity",
    "bind_operator_root", "capture_index_records",
    "capture_monitoring", "capture_protections", "category_counts",
    "classify_liveness", "close_scope_pins", "ensure_private_directory",
    "fsync_directory",
    "inventory_digest", "inventory_operator_scope", "quarantined_run_names",
    "unlink_owned",
]
