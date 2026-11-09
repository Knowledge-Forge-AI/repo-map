"""Exclusive bundle writer and bounded, descriptor-anchored, non-following reader.

Layout under ``<base>/first-use-workload/<scenario>-<attempt>/``: ``intent.json``,
``observation-SS-U.json``, ``reports/report-SS-U.json``, ``plans/plan-SS-U.json``,
then ``index.json`` and finally ``verdict.json``. The writer never overwrites,
renames over, deletes or repairs; an interrupted write stays ``incomplete``.
The reader admits every name, type, owner, mode and size through held
directory descriptors before it opens any data file.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from first_use_workload_domains import (
    CONTROL_NAMES, HEX32, INTENT_NAME, MAX_BUNDLE_BYTES, MAX_BUNDLE_MEMBERS, OBSERVATION_NAME,
    PLAN_NAME, PLANS_DIR, REPORT_NAME, REPORTS_DIR, SCENARIOS, WorkloadError,
)
from first_use_workload_records import member_limit

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
_SUBDIRS = {REPORTS_DIR: REPORT_NAME, PLANS_DIR: PLAN_NAME}


def bundle_directory_name(scenario: str, attempt: str) -> str:
    if scenario not in SCENARIOS or HEX32.fullmatch(attempt) is None:
        raise WorkloadError("invalid_domain")
    return f"{scenario}-{attempt}"


_ANCHORING_SUPPORTED = (
    os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.mkdir in os.supports_dir_fd
    and os.scandir in os.supports_fd
)


def _anchoring_supported() -> bool:
    """Descriptor anchoring is a platform fact fixed at import; no path fallback exists."""
    return _ANCHORING_SUPPORTED


@dataclass
class BundleWriter:
    """Writes one attempt's members exclusively, in payload -> index -> verdict order."""

    base: Path
    scenario: str
    attempt: str
    written: dict[str, bytes] = field(default_factory=dict)
    _stage: str = "payload"
    _subdirs: set[str] = field(default_factory=set)
    _total: int = 0

    def __post_init__(self) -> None:
        if not _anchoring_supported():
            raise WorkloadError("unsafe_input")
        self.root = self.base / bundle_directory_name(self.scenario, self.attempt)
        os.mkdir(self.root, 0o700)

    def _check(self, name: str, data: bytes) -> None:
        if name == "index.json":
            if self._stage != "payload":
                raise WorkloadError("unsafe_input")
        elif name == "verdict.json":
            if self._stage != "index":
                raise WorkloadError("unsafe_input")
        elif self._stage != "payload":
            raise WorkloadError("unsafe_input")
        if name in self.written:
            raise WorkloadError("unsafe_input")
        if len(data) > member_limit(name):
            raise WorkloadError("too_large")
        if len(self.written) + 1 > MAX_BUNDLE_MEMBERS or self._total + len(data) > MAX_BUNDLE_BYTES:
            raise WorkloadError("unbounded")

    def write(self, name: str, data: bytes) -> None:
        self._check(name, data)
        directory = os.open(self.root, _DIR_FLAGS)
        try:
            head, _sep, leaf = name.rpartition("/")
            if head:
                if head not in self._subdirs:
                    os.mkdir(head, 0o700, dir_fd=directory)
                    self._subdirs.add(head)
                child = os.open(head, _DIR_FLAGS, dir_fd=directory)
                os.close(directory)
                directory = child
            descriptor = os.open(leaf, _WRITE_FLAGS, 0o600, dir_fd=directory)
            try:
                view = memoryview(data)
                while view:
                    view = view[os.write(descriptor, view):]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            os.close(directory)
        self.written[name] = data
        self._total += len(data)
        if name == "index.json":
            self._stage = "index"
        elif name == "verdict.json":
            self._stage = "closed"


def _admit_directory(details: os.stat_result) -> None:
    if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
        raise WorkloadError("unsafe_input")
    if details.st_uid != os.geteuid() or details.st_mode & 0o022:
        raise WorkloadError("unsafe_input")


def _admit_file(details: os.stat_result, name: str) -> None:
    if not stat.S_ISREG(details.st_mode):
        raise WorkloadError("unsafe_input")
    if details.st_uid != os.geteuid() or details.st_mode & 0o022:
        raise WorkloadError("unsafe_input")
    if details.st_size > member_limit(name):
        raise WorkloadError("too_large")


def _version(details: os.stat_result) -> tuple[int, ...]:
    return (
        details.st_dev, details.st_ino, details.st_mode, details.st_uid, details.st_size,
        details.st_mtime_ns, details.st_ctime_ns,
    )


def _open_directory(name: str | Path, parent: int | None) -> tuple[int, os.stat_result]:
    try:
        if parent is None:
            before = os.lstat(name)
            descriptor = os.open(name, _DIR_FLAGS)
        else:
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            descriptor = os.open(name, _DIR_FLAGS, dir_fd=parent)
    except FileNotFoundError:
        raise WorkloadError("unreadable") from None
    except OSError:
        raise WorkloadError("unsafe_input") from None
    details = os.fstat(descriptor)
    if _version(details) != _version(before):
        os.close(descriptor)
        raise WorkloadError("unsafe_input")
    try:
        _admit_directory(details)
    except WorkloadError:
        os.close(descriptor)
        raise
    return descriptor, details


def _read_member(directory: int, leaf: str, name: str, admitted: os.stat_result) -> bytes:
    limit = member_limit(name)
    try:
        descriptor = os.open(leaf, _READ_FLAGS, dir_fd=directory)
    except OSError:
        raise WorkloadError("unsafe_input") from None
    try:
        if _version(os.fstat(descriptor)) != _version(admitted):
            raise WorkloadError("unsafe_input")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if _version(os.fstat(descriptor)) != _version(admitted) or len(data) != admitted.st_size:
            raise WorkloadError("unsafe_input")
    except BlockingIOError:
        raise WorkloadError("unsafe_input") from None
    finally:
        os.close(descriptor)
    return data


def _bounded_names(directory: int, remaining: int, *, root: bool) -> tuple[list[str], int]:
    """Collect at most the remaining member names, then sort the bounded list."""
    names: list[str] = []
    used = 0
    entry_limit = remaining + (len(_SUBDIRS) if root else 0)
    with os.scandir(directory) as entries:
        for entry in entries:
            if len(names) >= entry_limit:
                raise WorkloadError("unbounded")
            names.append(entry.name)
            if not root or entry.name not in _SUBDIRS:
                used += 1
                if used > remaining:
                    raise WorkloadError("unbounded")
    return sorted(names), used


def _root_pattern(name: str) -> bool:
    return name == INTENT_NAME or name in CONTROL_NAMES or OBSERVATION_NAME.fullmatch(name) is not None


def read_bundle(root: Path) -> dict[str, bytes]:
    """Return every member's bytes keyed by its literal relative name."""
    if not _anchoring_supported():
        raise WorkloadError("unsafe_input")
    anchor, _details = _open_directory(root, None)
    held: list[int] = [anchor]
    try:
        plan: list[tuple[int, str, str, os.stat_result]] = []
        remaining = MAX_BUNDLE_MEMBERS
        root_names, used = _bounded_names(anchor, remaining, root=True)
        remaining -= used
        for name in root_names:
            if name in _SUBDIRS:
                child, _child_details = _open_directory(name, anchor)
                held.append(child)
                pattern = _SUBDIRS[name]
                child_names, used = _bounded_names(child, remaining, root=False)
                remaining -= used
                if not child_names:
                    raise WorkloadError("unsafe_input")
                for leaf in child_names:
                    leaf_details = os.stat(leaf, dir_fd=child, follow_symlinks=False)
                    if pattern.fullmatch(leaf) is None:
                        raise WorkloadError("unsafe_input")
                    member = f"{name}/{leaf}"
                    _admit_file(leaf_details, member)
                    plan.append((child, leaf, member, leaf_details))
            elif _root_pattern(name):
                details = os.stat(name, dir_fd=anchor, follow_symlinks=False)
                _admit_file(details, name)
                plan.append((anchor, name, name, details))
            else:
                raise WorkloadError("unsafe_input")
        if len(plan) > MAX_BUNDLE_MEMBERS:
            raise WorkloadError("unbounded")
        if sum(item[3].st_size for item in plan) > MAX_BUNDLE_BYTES:
            raise WorkloadError("unbounded")
        return {member: _read_member(directory, leaf, member, details)
                for directory, leaf, member, details in plan}
    except OSError:
        raise WorkloadError("unreadable") from None
    finally:
        for descriptor in reversed(held):
            os.close(descriptor)


__all__ = ["BundleWriter", "bundle_directory_name", "read_bundle"]
