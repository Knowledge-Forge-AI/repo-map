"""Capture-only sealing inventory, without discovery classification readers.

This module intentionally mirrors the selected-file and snapshot portions of
the incumbent multi-source scan.  It does not construct ``FileInfo`` records,
read classifications, or dispatch through ``discover_repository``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
import os
from pathlib import Path
from typing import TYPE_CHECKING

from common_lore_index.artifacts._sealing_meter import SealingMeter, SealingBudgetExceeded
from common_lore_index.graph._capture_contracts import (
    MultiSourceCaptureError,
    _SourceCapture,
    _SourceChanged,
    _SourceInvalid,
    _SourceUnavailable,
)
from common_lore_index.graph._canonical_selection import canonical_relative_path
from common_lore_index.graph._discovery_selection import (
    normalize_discovery_exclude_paths,
    selected_files,
)
from common_lore_index.graph.multi_source import (
    SnapshotManifestEntry,
    SourceKind,
    SourceSnapshot,
)
from common_lore_index.graph import multi_source_capture
from common_lore_index.ops.config_records import OpsGraphConfig

if TYPE_CHECKING:
    from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig


@dataclass(frozen=True)
class SealingGenerationScan:
    """The generation and snapshots needed by source sealing."""

    source_generation: str
    config_generation: str
    snapshots: tuple[SourceSnapshot, ...]


def _governed_bindings(graph: OpsGraphConfig) -> tuple[OpsGraphSourceBindingConfig, ...]:
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


def _selected_paths(root: Path, excludes: Sequence[str], meter: SealingMeter | None) -> tuple[str, ...]:
    repository_root = root.resolve()
    if meter is None:
        walk = os.walk(repository_root)
    else:
        from common_lore_index.graph._metered_discovery import metered_walk

        walk = metered_walk(repository_root, meter)
    configured_excludes = normalize_discovery_exclude_paths(excludes)
    return tuple(
        sorted(
            {
                canonical_relative_path(repository_root, file_path)
                for file_path in selected_files(repository_root, configured_excludes, walk)
            }
        )
    )


def _scan_binding(
    graph: OpsGraphConfig,
    binding: OpsGraphSourceBindingConfig,
    meter: SealingMeter | None,
) -> SourceSnapshot:
    root = Path(binding.root_path_expanded)
    if not root.is_dir():
        raise _SourceUnavailable
    repository_root = root.resolve()
    entries: list[SnapshotManifestEntry] = []
    paths = _selected_paths(root, binding.exclude_paths, meter)
    for relative in paths:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise _SourceInvalid
        source_path = repository_root / relative
        if meter is None:
            digest, size, executable = multi_source_capture._read_stable_file(source_path)
        else:
            from common_lore_index.graph._metered_capture import read_stable_file_metered

            digest, size, executable = read_stable_file_metered(source_path, meter)
        entries.append(SnapshotManifestEntry(relative, digest, size, executable))
    return SourceSnapshot.create(
        binding.domain_binding(graph.id),
        manifest_entries=entries,
        git_commit=None,
        git_tree=None,
        ignore_policy_id="ignore1:declared-selection",
        metadata_identity="meta1:content-manifest-v1",
    )


def scan_sealing_generations(
    graph: OpsGraphConfig, *, io_meter: SealingMeter | None = None
) -> SealingGenerationScan:
    """Build sealing snapshots from capture-only selected-file reads."""

    if not graph.explicit_source_bindings:
        graph = replace(
            graph,
            source_bindings=graph.effective_source_bindings,
            explicit_source_bindings=True,
        )
    captured: list[SourceSnapshot] = []
    try:
        for binding in _governed_bindings(graph):
            captured.append(_scan_binding(graph, binding, io_meter))
    except (MultiSourceCaptureError, SealingBudgetExceeded):
        raise
    except FileNotFoundError as error:
        raise multi_source_capture._inventory_error(_SourceUnavailable()) from error
    except OSError as error:
        raise multi_source_capture._inventory_error(_SourceCapture()) from error
    except ValueError as error:
        raise multi_source_capture._inventory_error(_SourceInvalid()) from error
    except (_SourceUnavailable, _SourceChanged, _SourceCapture, _SourceInvalid) as error:
        raise multi_source_capture._inventory_error(error) from error

    from common_lore_index.graph import multi_source_pipeline

    snapshots = tuple(captured)
    return SealingGenerationScan(
        source_generation=multi_source_pipeline._multi_source_source_generation(snapshots),
        config_generation=multi_source_pipeline.multi_source_config_generation(graph),
        snapshots=snapshots,
    )


__all__ = (
    "SealingGenerationScan",
    "canonical_relative_path",
    "scan_sealing_generations",
)
