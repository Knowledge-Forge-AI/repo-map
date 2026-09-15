"""Exact scratch accounting and dry-run historical candidate classification."""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from repomap_test_support.resource_ledger import (
    CleanupResult,
    FinalPresence,
    ResourceKind,
    ResourceLedger,
    RetainedReason,
)
from repomap_test_support.test_scratch import TestScratchLayout


class ScratchAccountingError(RuntimeError):
    """Scratch ownership or exact readback cannot be established."""


@dataclass(frozen=True)
class ScratchMeasurement:
    allocated_bytes: int
    apparent_bytes: int
    inode_count: int
    retained_allocated_bytes: int
    retained_apparent_bytes: int
    retained_inode_count: int
    largest_subtree_category: str
    unsafe_link_count: int


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _retained_owner(path: Path, retained_paths: tuple[Path, ...]) -> bool:
    return any(path == retained or retained in path.parents for retained in retained_paths)


def measure_scratch(
    root: Path,
    *,
    retained_paths: Iterable[Path] = (),
    reject_unsafe_links: bool = False,
) -> ScratchMeasurement:
    """Measure one exact tree without following links or reading file contents."""
    root = Path(root)
    if root.is_symlink():
        raise ScratchAccountingError("scratch root must not be a symlink")
    if not root.exists():
        return ScratchMeasurement(0, 0, 0, 0, 0, 0, "none", 0)
    resolved_root = root.resolve()
    retained = tuple(Path(item).resolve() for item in retained_paths)
    if any(not _inside(item, resolved_root) for item in retained):
        raise ScratchAccountingError("retained path escapes the scratch root")

    allocated = apparent = inodes = 0
    retained_allocated = retained_apparent = retained_inodes = 0
    category_sizes: dict[str, int] = {}
    unsafe_links = 0
    stack = [root]
    seen: set[tuple[int, int]] = set()
    while stack:
        path = stack.pop()
        try:
            metadata = path.lstat()
        except OSError as error:
            raise ScratchAccountingError("scratch readback failed") from error
        if stat.S_ISLNK(metadata.st_mode):
            try:
                target = path.resolve(strict=True)
            except OSError:
                unsafe_links += 1
                if reject_unsafe_links:
                    raise ScratchAccountingError(
                        "scratch accounting refuses a dangling symlink"
                    )
            else:
                if not _inside(target, resolved_root):
                    unsafe_links += 1
                    if reject_unsafe_links:
                        raise ScratchAccountingError(
                            "scratch accounting refuses a symlink escape"
                        )
        key = (metadata.st_dev, metadata.st_ino)
        if key in seen:
            if stat.S_ISDIR(metadata.st_mode):
                raise ScratchAccountingError("scratch tree contains a directory alias")
            continue
        seen.add(key)
        item_allocated = getattr(metadata, "st_blocks", 0) * 512
        allocated += item_allocated
        apparent += metadata.st_size
        inodes += 1
        try:
            owned_path = path.resolve(strict=True)
        except OSError:
            owned_path = path.absolute()
        if retained and _retained_owner(owned_path, retained):
            retained_allocated += item_allocated
            retained_apparent += metadata.st_size
            retained_inodes += 1
        relative = path.relative_to(root)
        category = relative.parts[0] if relative.parts else "run_root"
        category_sizes[category] = category_sizes.get(category, 0) + item_allocated
        if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            try:
                with os.scandir(path) as entries:
                    stack.extend(Path(entry.path) for entry in entries)
            except OSError as error:
                raise ScratchAccountingError("scratch directory scan failed") from error
    largest = max(category_sizes, key=lambda k: category_sizes.get(k, 0), default="none")
    return ScratchMeasurement(
        allocated,
        apparent,
        inodes,
        retained_allocated,
        retained_apparent,
        retained_inodes,
        largest,
        unsafe_links,
    )


class ScratchRunOwner:
    """Registers, measures, and removes only one layout's exact transient paths."""

    def __init__(self, layout: TestScratchLayout, ledger: ResourceLedger) -> None:
        if layout.run_root.name != ledger.identity.run_id:
            raise ScratchAccountingError("layout and ledger run identity differ")
        self.layout = layout
        self.ledger = ledger
        self._retained = {
            Path(record.identity).resolve()
            for record in ledger.records
            if record.retained
            and record.kind
            in {ResourceKind.SCRATCH_FILE, ResourceKind.SCRATCH_EVIDENCE_GROUP}
            and Path(record.identity).is_absolute()
        }
        self._measure = measure_scratch

    def register_layout(self) -> ScratchMeasurement:
        for directory in self._transient_roots():
            self.ledger.register(
                ResourceKind.SCRATCH_DIRECTORY,
                str(directory),
                creation_owner="test-scratch-layout",
                created_before_run=False,
                creation_observed=directory.is_dir() and not directory.is_symlink(),
                cleanup_required=True,
            )
        self._register_retained_file(
            self.layout.manifest,
            ResourceKind.SCRATCH_FILE,
            RetainedReason.OPERATOR_REVIEW,
        )
        self._register_retained_file(
            self.ledger.path,
            ResourceKind.SCRATCH_EVIDENCE_GROUP,
            RetainedReason.DIAGNOSTIC_EVIDENCE,
        )
        return self.checkpoint("run_entry")

    def retain(self, path: Path, *, reason: RetainedReason | str) -> None:
        path = Path(path)
        if path.is_symlink() or not path.exists():
            raise ScratchAccountingError("retained scratch path must exist without symlink")
        if not _inside(path.resolve(), self.layout.run_root.resolve()):
            raise ScratchAccountingError("retained scratch path escapes the run root")
        if any(_inside(path.resolve(), root.resolve()) for root in self._transient_roots()):
            raise ScratchAccountingError("retained evidence cannot be transient scratch")
        measurement = self._measure(path, reject_unsafe_links=True)
        if measurement is None:
            raise ScratchAccountingError("retained scratch readback is unavailable")
        self.ledger.register(
            ResourceKind.SCRATCH_EVIDENCE_GROUP,
            str(path),
            creation_owner="current-run-retention",
            created_before_run=False,
            creation_observed=True,
            cleanup_required=False,
            retained=True,
            retained_reason=reason,
            size_bytes=measurement.allocated_bytes,
            inode_count=measurement.inode_count,
        )
        self._retained.add(path.resolve())

    def checkpoint(self, label: str) -> ScratchMeasurement:
        measurement = self._measure(
            self.layout.run_root,
            retained_paths=self._retained,
        )
        if measurement is None:
            raise ScratchAccountingError("scratch checkpoint readback is unavailable")
        self.ledger.add_checkpoint(
            label,
            {
                "allocated_bytes": measurement.allocated_bytes,
                "apparent_bytes": measurement.apparent_bytes,
                "inode_count": measurement.inode_count,
                "retained_evidence_bytes": measurement.retained_allocated_bytes,
                "largest_owned_subtree_category": measurement.largest_subtree_category,
                "unsafe_link_count": measurement.unsafe_link_count,
            },
        )
        return self.measure_current()

    def measure_current(self) -> ScratchMeasurement:
        """Read back the current tree, including evidence written by a checkpoint."""
        measurement = self._measure(
            self.layout.run_root,
            retained_paths=self._retained,
        )
        if measurement is None:
            raise ScratchAccountingError("scratch checkpoint readback is unavailable")
        return measurement

    def cleanup_transient(self, *, record_boundaries: bool = True) -> None:
        if record_boundaries:
            self.checkpoint("before_cleanup")
        for directory in self._transient_roots():
            record = self.ledger.get(ResourceKind.SCRATCH_DIRECTORY, str(directory))
            if directory.is_symlink():
                raise ScratchAccountingError("transient scratch path is a symlink")
            self.ledger.mark_cleanup_attempted(record.kind, record.identity)
            try:
                if directory.exists():
                    shutil.rmtree(directory)
            except OSError:
                self.ledger.mark_cleanup_result(
                    record.kind, record.identity, CleanupResult.FAILED
                )
                self.ledger.mark_final_presence(
                    record.kind, record.identity, FinalPresence.PRESENT
                )
                raise ScratchAccountingError("transient scratch cleanup failed")
            readback = self._measure(directory)
            if readback is None:
                raise ScratchAccountingError("scratch cleanup readback is unavailable")
            result = (
                CleanupResult.REMOVED
                if record.creation_observed
                else CleanupResult.ALREADY_ABSENT
            )
            self.ledger.mark_cleanup_result(record.kind, record.identity, result)
            self.ledger.mark_final_presence(
                record.kind,
                record.identity,
                FinalPresence.ABSENT if readback.inode_count == 0 else FinalPresence.PRESENT,
            )
            if readback.inode_count != 0 or readback.allocated_bytes != 0:
                raise ScratchAccountingError("scratch cleanup readback found residue")
        if record_boundaries:
            self.checkpoint("after_cleanup")

    def _transient_roots(self) -> tuple[Path, ...]:
        """Return non-overlapping top-level groups created by the layout."""
        roots = {
            self.layout.run_root / directory.relative_to(self.layout.run_root).parts[0]
            for directory in self.layout.directories()
        }
        return tuple(sorted(roots, key=lambda item: item.name))

    def final_projection(self) -> dict[str, int]:
        known = {
            Path(record.identity).resolve()
            for record in self.ledger.records
            if record.kind
            in {
                ResourceKind.SCRATCH_DIRECTORY,
                ResourceKind.SCRATCH_FILE,
                ResourceKind.SCRATCH_EVIDENCE_GROUP,
            }
            and Path(record.identity).is_absolute()
        }
        unknown_allocated = unknown_inodes = 0
        for child in self.layout.run_root.iterdir():
            if child.is_symlink():
                raise ScratchAccountingError("unknown owned residue includes a symlink")
            if child.resolve() in known:
                continue
            measurement = self._measure(child)
            if measurement is None:
                raise ScratchAccountingError("final scratch readback is unavailable")
            unknown_allocated += measurement.allocated_bytes
            unknown_inodes += measurement.inode_count
        if unknown_allocated or unknown_inodes:
            raise ScratchAccountingError("unknown owned residue remains")

        transient_bytes = transient_inodes = 0
        retained_bytes = retained_inodes = 0
        for record in self.ledger.records:
            if record.kind not in {
                ResourceKind.SCRATCH_DIRECTORY,
                ResourceKind.SCRATCH_FILE,
                ResourceKind.SCRATCH_EVIDENCE_GROUP,
            }:
                continue
            path = Path(record.identity)
            measurement = self._measure(
                path,
                reject_unsafe_links=record.retained,
            )
            if measurement is None:
                raise ScratchAccountingError("final scratch readback is unavailable")
            if record.retained:
                if record.inode_count > 0 and measurement.inode_count == 0:
                    raise ScratchAccountingError("registered retained evidence is missing")
                retained_bytes += measurement.allocated_bytes
                retained_inodes += measurement.inode_count
            else:
                transient_bytes += measurement.allocated_bytes
                transient_inodes += measurement.inode_count
        return {
            "scratch_transient_bytes_remaining": transient_bytes,
            "scratch_retained_bytes": retained_bytes,
            "scratch_unknown_owned_bytes": unknown_allocated,
            "scratch_inodes_remaining": transient_inodes,
            "scratch_retained_inodes": retained_inodes,
        }

    def _register_retained_file(
        self,
        path: Path,
        kind: ResourceKind,
        reason: RetainedReason,
    ) -> None:
        measurement = self._measure(path, reject_unsafe_links=True)
        if measurement is None:
            raise ScratchAccountingError("retained file readback is unavailable")
        self.ledger.register(
            kind,
            str(path),
            creation_owner="test-scratch-layout",
            created_before_run=False,
            creation_observed=True,
            cleanup_required=False,
            retained=True,
            retained_reason=reason,
            size_bytes=measurement.allocated_bytes,
            inode_count=measurement.inode_count,
        )
        self._retained.add(path.resolve())


from repomap_test_support.resource_scratch_history import (  # noqa: E402
    HistoricalScratchCandidate,
    HistoricalScratchInventory,
    classify_historical_scratch,
)


__all__ = [
    "HistoricalScratchCandidate",
    "HistoricalScratchInventory",
    "ScratchAccountingError",
    "ScratchMeasurement",
    "ScratchRunOwner",
    "classify_historical_scratch",
    "measure_scratch",
]
