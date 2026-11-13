"""Complete local multi-binding capture before one staged graph publication."""
from __future__ import annotations
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING
from common_lore_index._temporary import OwnedTemporaryDirectory
from common_lore_index.extractors.config.nix_resolver import resolve_nix_relations as resolve_nix_relations
from common_lore_index.graph.discovery import (
    discover_repository as discover_repository,
    extract_observations_from_repository_files as extract_observations_from_repository_files,
)
from common_lore_index.graph._capture_control import CancelCheck, CaptureControl, controlled_capture, validate_cancel_check
from common_lore_index.graph._capture_candidate import CaptureEngines, capture_candidate
from common_lore_index.graph._capture_identity import (
    _MULTI_SOURCE_EXTRACTOR_IDENTITY as _MULTI_SOURCE_EXTRACTOR_IDENTITY,
    _MULTI_SOURCE_CANONICALIZER_IDENTITY as _MULTI_SOURCE_CANONICALIZER_IDENTITY,
    _MULTI_SOURCE_SEMANTIC_IDENTITY as _MULTI_SOURCE_SEMANTIC_IDENTITY,
    _MULTI_SOURCE_QUALITY_IDENTITY as _MULTI_SOURCE_QUALITY_IDENTITY,
    _MULTI_SOURCE_RESOLVER_VERSION as _MULTI_SOURCE_RESOLVER_VERSION,
    _resolver_identity as _resolver_identity,
    _multi_source_source_generation as _multi_source_source_generation,
    multi_source_config_generation as multi_source_config_generation,
    multi_source_semantic_identities as multi_source_semantic_identities,
)
from common_lore_index.graph.multi_source_capture import (
    MultiSourceCaptureError as MultiSourceCaptureError, _CapturedSource as _CapturedSource, _capture_inventory,
)
from common_lore_index.graph.multi_source_routing import (
    MultiSourceCandidateBundle as MultiSourceCandidateBundle,
    MultiSourceGenerationScan as MultiSourceGenerationScan,
    SealedSourceBinding as SealedSourceBinding,
    _namespaced_observation as _namespaced_observation,
)
from common_lore_index.ops.config_binding_records import OpsGraphSourceBindingConfig
from common_lore_index.ops.config_records import OpsGraphConfig
if TYPE_CHECKING:
    from common_lore_index.artifacts._sealing_meter import SealingMeter


def capture_multi_source_candidate(
    graph: OpsGraphConfig, *, elide_discovery_hash: bool = False,
    cancel_check: CancelCheck | None = None,
) -> MultiSourceCandidateBundle:
    """Capture every binding, resolve one bound candidate, then reverify all inputs."""
    if type(elide_discovery_hash) is not bool:
        raise ValueError("capture hash elision must be boolean")
    validate_cancel_check(cancel_check)
    engines = CaptureEngines(lambda: _capture_inventory, lambda: discover_repository,
                             lambda: extract_observations_from_repository_files, lambda: resolve_nix_relations)
    with OwnedTemporaryDirectory(prefix="repomap-multi-source-") as temporary:
        return controlled_capture(cancel_check, lambda guarded: capture_candidate(
            graph, Path(temporary), engines, CaptureControl(guarded), elide_discovery_hash,
        ))


def capture_sealed_multi_source_candidate(
    graph_id: str,
    bindings: Sequence[SealedSourceBinding],
    *,
    expected_snapshot_vector: Sequence[tuple[str, int, str]],
    cancel_check: CancelCheck | None = None,
) -> MultiSourceCandidateBundle:
    """Run the authoritative path-based engine over verified command-owned roots."""

    validate_cancel_check(cancel_check)
    if not bindings:
        raise MultiSourceCaptureError(
            "sealed source inventory is invalid", category="contract_validation"
        )
    repository_scopes = {item.repository_scope for item in bindings}
    if len(repository_scopes) != 1:
        raise MultiSourceCaptureError(
            "sealed source inventory is invalid", category="contract_validation"
        )
    configured = tuple(
        OpsGraphSourceBindingConfig(
            schema_version=1,
            binding_id=item.binding_id,
            source_definition_id=item.source_definition_id,
            alias=item.alias,
            revision=item.revision,
            source_kind=item.source_kind,
            root_path=str(item.root),
            root_path_expanded=str(item.root),
            repository_name=item.repository_scope,
            logical_root=item.logical_root,
            privacy=item.privacy,
            evidence_retention=item.evidence_retention,
            extractor_profile=item.extractor_profile,
            include_paths=(),
            exclude_paths=(),
            selection_policy_id=item.selection_policy_id,
            resolution_policy=item.resolution_policy,
            enabled=True,
            role=item.role,
            input_name=item.input_name,
        )
        for item in bindings
    )
    graph = OpsGraphConfig(
        id=graph_id,
        name="Portable snapshot",
        root_path="",
        root_path_expanded="",
        repository_name=next(iter(repository_scopes)),
        privacy=(
            "public-dev"
            if all(item.privacy == "public-dev" for item in bindings)
            else "private-ops"
        ),
        enabled=True,
        mcp_visible=False,
        extractor_profile="",
        refresh_policy="manual",
        source_bindings=configured,
        explicit_source_bindings=True,
    )
    result = capture_multi_source_candidate(
        graph, elide_discovery_hash=True, **CaptureControl(cancel_check).keywords
    )
    if result.candidate.snapshot_vector != tuple(expected_snapshot_vector):
        raise MultiSourceCaptureError(
            "sealed source inventory disagrees with manifest",
            category="source_changed",
        )
    return result


def scan_multi_source_generations(
    graph: OpsGraphConfig, *, io_meter: SealingMeter | None = None
) -> MultiSourceGenerationScan:
    """Derive multi-source fences from discovery manifests without semantics.

    ``discover_repository`` stays the dynamic module-global seam; an explicit
    sealing meter is forwarded only when one was supplied.
    """

    if not graph.explicit_source_bindings:
        graph = replace(
            graph,
            source_bindings=graph.effective_source_bindings,
            explicit_source_bindings=True,
        )
    if io_meter is None:
        captured = _capture_inventory(graph, discover_fn=discover_repository)
    else:
        captured = _capture_inventory(
            graph, discover_fn=discover_repository, io_meter=io_meter
        )
    snapshots = tuple(item.snapshot for item in captured)
    files = tuple(item for source in captured for item in source.files)
    return MultiSourceGenerationScan(
        source_generation=_multi_source_source_generation(snapshots),
        config_generation=multi_source_config_generation(graph),
        snapshots=snapshots,
        files=files,
    )


__all__ = [
    "MultiSourceCandidateBundle",
    "MultiSourceCaptureError",
    "MultiSourceGenerationScan",
    "SealedSourceBinding",
    "capture_multi_source_candidate",
    "capture_sealed_multi_source_candidate",
    "multi_source_config_generation",
    "multi_source_semantic_identities",
    "scan_multi_source_generations",
]
