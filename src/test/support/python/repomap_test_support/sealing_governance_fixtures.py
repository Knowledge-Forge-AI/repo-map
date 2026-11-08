"""Public-safe trees, graphs and independent witnesses for sealing governance proofs.

The expectation helpers compute meter counters from the tree layout alone
(file sizes, directory listings and the documented reader request sizes), so a
test never trusts the subject meter to describe its own work. The open
recorder wraps ``os.open`` at the test boundary and records basenames, so a
sentinel file that must never be opened is witnessed independently of the
subject's counters and of the process user identity (it works under root).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
import math
import os
from pathlib import Path
from typing import Any

from common_lore_index.artifacts.source_sealer import seal_configured_sources
from common_lore_index.artifacts.store import FileSystemArtifactStore
from common_lore_index.graph.multi_source import (
    SourceKind,
    graph_source_binding_id,
    source_selection_policy_id,
)
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig
from common_lore_index.ops.generations import canonicalizer_generation, extractor_generation

GRAPH_ID = "sealing-fixture"
MIB = 1024 * 1024
STORE_CHUNK = 64 * 1024


def write_tree(root: Path, files: Mapping[str, bytes]) -> Path:
    """Create ``root`` with exactly ``files`` (relative POSIX path -> bytes)."""
    root.mkdir(parents=True, exist_ok=True)
    for relative, data in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


def binding_for(alias: str, root: Path, *, exclude_paths: tuple[str, ...] = ()) -> OpsGraphSourceBindingConfig:
    return OpsGraphSourceBindingConfig(
        schema_version=1,
        binding_id=graph_source_binding_id(GRAPH_ID, alias),
        source_definition_id=f"src1:{alias}",
        alias=alias,
        revision=1,
        source_kind=SourceKind.FOLDER,
        root_path=str(root),
        root_path_expanded=str(root),
        repository_name=f"fixture-{alias}",
        logical_root=".",
        privacy="public-dev",
        evidence_retention="metadata-only",
        extractor_profile="default",
        include_paths=(),
        exclude_paths=exclude_paths,
        selection_policy_id=source_selection_policy_id((), exclude_paths),
        resolution_policy="allow-declared",
        enabled=True,
        role="entry" if alias == "entry" else "input",
        input_name=None if alias == "entry" else alias,
    )


def graph_for(*bindings: OpsGraphSourceBindingConfig) -> OpsGraphConfig:
    return OpsGraphConfig(
        id=GRAPH_ID, name="Sealing fixture", root_path="", root_path_expanded="",
        repository_name="multi-source", privacy="public-dev", enabled=True, mcp_visible=False,
        extractor_profile="", refresh_policy="manual", source_bindings=tuple(bindings),
        explicit_source_bindings=True,
    )


def seal(graph: OpsGraphConfig, store_root: Path, **kwargs: Any) -> tuple[Any, Any, str]:
    store = FileSystemArtifactStore(store_root)
    return seal_configured_sources(
        graph, store, extractor_generation=extractor_generation(graph),
        canonicalizer_generation=canonicalizer_generation(), **kwargs,
    )


def _calls(size: int, chunk: int) -> int:
    return math.ceil(size / chunk)


@dataclass(frozen=True)
class TreeExpectation:
    """Independently derived counters for one plain (``.txt``/``.py``) tree."""

    sizes: Mapping[str, int]
    walked_directories: int
    listed_entries: int
    depth: Mapping[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.sizes.values())

    def read_bytes(self, manifest_bytes: int, *, collision: bool) -> int:
        store = (3 if collision else 1) * (self.total + manifest_bytes)
        return 2 * self.total + 2 * self.total + self.total + store

    def read_calls(self, manifest_bytes: int, *, collision: bool) -> int:
        """R1+R5 per scan with one EOF probe each, R6 exact, R7 plus probe, R7c both sides."""
        scans = 2 * sum(2 * (_calls(size, MIB) + 1) for size in self.sizes.values())
        copy = sum(_calls(size, MIB) for size in self.sizes.values())
        stored = (*self.sizes.values(), manifest_bytes)
        verify = sum(_calls(size, STORE_CHUNK) + 1 for size in stored)
        compare = sum(2 * (_calls(size, STORE_CHUNK) + 1) for size in stored) if collision else 0
        return scans + copy + verify + compare

    def opens(self, *, walks: int, collision: bool) -> int:
        per_put = 4 if collision else 3
        copy = sum(self.depth.get(path, 0) + 2 for path in self.sizes)
        return (
            walks * self.walked_directories + 2 * 2 * len(self.sizes) + copy
            + per_put * (len(self.sizes) + 1)
        )

    def fsyncs(self, *, collision: bool) -> int:
        return (1 if collision else 2) * (len(self.sizes) + 1)


def expectation_for(root: Path, files: Mapping[str, bytes]) -> TreeExpectation:
    """Count walked directories and listed entries of a tree with no ignored names."""
    directories = 0
    entries = 0
    for _current, dirnames, filenames in os.walk(root):
        directories += 1
        entries += len(dirnames) + len(filenames)
    return TreeExpectation(
        {path: len(data) for path, data in files.items()}, directories, entries,
        {path: path.count("/") for path in files},
    )


@dataclass
class OpenRecorder:
    """Basenames passed to ``os.open`` while installed; never consults the subject."""

    names: list[str] = field(default_factory=list)

    def opened(self, name: str) -> bool:
        return name in self.names


@contextmanager
def record_opens(monkeypatch: Any) -> Iterator[OpenRecorder]:
    recorder = OpenRecorder()
    real_open = os.open

    def recording_open(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        recorder.names.append(os.path.basename(os.fsdecode(path)))
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", recording_open)
    try:
        yield recorder
    finally:
        monkeypatch.setattr(os, "open", real_open)


def open_descriptor_count() -> int:
    """Open descriptors of this process (Linux ``/proc`` or the BSD ``/dev/fd``)."""
    for directory in ("/proc/self/fd", "/dev/fd"):
        if os.path.isdir(directory):
            return len(os.listdir(directory))
    raise RuntimeError("descriptor table is not observable on this platform")


__all__ = (
    "GRAPH_ID", "OpenRecorder", "TreeExpectation", "binding_for", "expectation_for",
    "graph_for", "open_descriptor_count", "record_opens", "seal", "write_tree",
)
