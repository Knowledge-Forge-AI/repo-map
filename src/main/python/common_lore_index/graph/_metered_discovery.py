"""Metered traversal and the governed metadata-only preflight (ADR 0173 3.3-3.4).

``metered_walk`` is equivalent to ``os.walk(top)`` with ``topdown=True``,
``followlinks=False`` and ``onerror=None``: listing failures skip the directory,
symlinked directories are listed but never entered, and pruning ``dirnames``
in place controls descent. Each listing is one admitted open and each entry is
admitted before it is retained, so a governed meter's finite entry ceiling also
bounds pending names. ``preflight_inventory`` walks every binding with metadata
only, applies the existing ``ArtifactLimits`` inventory predicate incrementally
and records the plan facts that refuse a provable overrun before any body read.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, replace
import os
from pathlib import Path

from common_lore_index.artifacts._manifest_records import ArtifactLimits
from common_lore_index.artifacts._sealing_meter import SealingMeter, SealingPlanFacts
from common_lore_index.graph._metered_classification import ClassificationReaders
from common_lore_index.graph._canonical_selection import canonical_relative_path
from common_lore_index.graph._discovery_selection import (
    normalize_discovery_exclude_paths,
    selected_files,
)
from common_lore_index.graph.multi_source import SourceKind
from common_lore_index.graph._capture_contracts import MultiSourceCaptureError
from common_lore_index.ops.config_records import OpsGraphConfig


def metered_walk(top: Path | str, meter: SealingMeter) -> Iterator[tuple[str, list[str], list[str]]]:
    """Top-down ``os.walk`` equivalent whose listings and entries are admitted."""

    stack = [os.fspath(top)]
    while stack:
        current = stack.pop()
        dirs: list[str] = []
        nondirs: list[str] = []
        meter.admit_open()
        try:
            listing = os.scandir(current)
        except OSError:
            continue
        failed = False
        with listing:
            while True:
                try:
                    entry = next(listing)
                except StopIteration:
                    break
                except OSError:
                    failed = True
                    break
                meter.admit_entry()
                try:
                    is_dir = entry.is_dir()
                except OSError:
                    is_dir = False
                (dirs if is_dir else nondirs).append(entry.name)
        if failed:
            continue
        yield current, dirs, nondirs
        for dirname in reversed(dirs):
            child = os.path.join(current, dirname)
            if not os.path.islink(child):
                stack.append(child)


@dataclass(frozen=True)
class MeteredDiscoveryHooks:
    """``discover_repository`` I/O hooks bound to one call-owned meter.

    The sealing caller selects these, so ``graph.discovery`` itself never
    imports the metered (``artifacts``-backed) readers.
    """

    meter: SealingMeter

    def walk(self, top: Path) -> Iterator[tuple[str, list[str], list[str]]]:
        return metered_walk(top, self.meter)

    def readers(self) -> ClassificationReaders:
        return ClassificationReaders(self.meter)


def _governed_bindings(graph: OpsGraphConfig) -> tuple:
    if not graph.explicit_source_bindings:
        graph = replace(
            graph,
            source_bindings=graph.effective_source_bindings,
            explicit_source_bindings=True,
        )
    bindings = graph.effective_source_bindings
    if (
        not bindings
        or any(not item.enabled for item in bindings)
        or any(
            item.source_kind not in {SourceKind.FOLDER, SourceKind.GIT_WORKING_TREE}
            for item in bindings
        )
    ):
        raise MultiSourceCaptureError(
            "source binding inventory is unsupported", category="source_invalid"
        )
    return tuple(sorted(bindings, key=lambda item: item.binding_id))


def preflight_inventory(
    graph: OpsGraphConfig, meter: SealingMeter, limits: ArtifactLimits
) -> SealingPlanFacts:
    """Walk every binding's metadata, apply the inventory predicate, record the plan.

    Availability failures of every binding are reported before any body is
    read. Retained inventory never exceeds ``limits.max_artifacts`` entries.
    """

    if not meter.governed:
        raise ValueError("preflight requires a governed sealing meter")
    bindings = _governed_bindings(graph)
    files = total = symlinked = 0
    for binding in bindings:
        root = Path(binding.root_path_expanded)
        if not root.is_dir():
            raise MultiSourceCaptureError("source unavailable", category="source_unavailable")
    for binding in bindings:
        repository_root = Path(binding.root_path_expanded).resolve()
        excludes = normalize_discovery_exclude_paths(binding.exclude_paths)
        seen: set[str] = set()
        for file_path in selected_files(
            repository_root, excludes, metered_walk(repository_root, meter)
        ):
            try:
                relative = canonical_relative_path(repository_root, file_path)
                size = file_path.stat().st_size
            except FileNotFoundError as error:
                raise MultiSourceCaptureError(
                    "source unavailable", category="source_unavailable"
                ) from error
            except OSError as error:
                raise MultiSourceCaptureError(
                    "source capture failed", category="source_capture"
                ) from error
            symlinked += int(file_path.is_symlink())  # selected entries, before deduplication
            if relative in seen:
                continue
            seen.add(relative)
            files += 1
            total += size
            if files > limits.max_artifacts:
                raise ValueError("artifact count bounds exceeded")
            if len(relative.encode("utf-8")) > limits.max_path_bytes:
                raise ValueError("artifact path bounds exceeded")
            if total > limits.max_total_bytes:
                raise ValueError("artifact byte bounds exceeded")
    plan = SealingPlanFacts(len(bindings), files, total, symlinked)
    meter.note_plan(plan)
    return plan


__all__ = ("MeteredDiscoveryHooks", "metered_walk", "preflight_inventory")
