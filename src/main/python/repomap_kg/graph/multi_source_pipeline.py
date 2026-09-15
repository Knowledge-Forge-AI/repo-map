"""Complete local multi-binding capture before one staged graph publication."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile

from repomap_kg.extractors.config.nix_resolver import (
    resolve_nix_relations as resolve_nix_relations,
)
from repomap_kg.graph.discovery import (
    discover_repository as discover_repository,
    extract_observations_from_repository_files as extract_observations_from_repository_files,
)
from repomap_kg.graph.multi_source import (
    GraphCandidate,
    SourceSnapshot,
    multi_source_configuration_id,
)
from repomap_kg.graph.multi_source_capture import (
    MultiSourceCaptureError as MultiSourceCaptureError,
    _CapturedSource as _CapturedSource,
    _capture_inventory,
)
from repomap_kg.graph.multi_source_routing import (
    MultiSourceCandidateBundle as MultiSourceCandidateBundle,
    MultiSourceGenerationScan as MultiSourceGenerationScan,
    SealedSourceBinding as SealedSourceBinding,
    _binding_view,
    _module_exports,
    _namespaced_observation as _namespaced_observation,
    _resolved_observation,
    _validate_provenance,
)
from repomap_kg.observations.raw import RawObservation
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig


_MULTI_SOURCE_EXTRACTOR_IDENTITY = "cap1:python-static-v1"
_MULTI_SOURCE_CANONICALIZER_IDENTITY = "canon1:graph-key-v1-binding-path"
_MULTI_SOURCE_SEMANTIC_IDENTITY = "semantic1:multi-source-v1"
_MULTI_SOURCE_QUALITY_IDENTITY = "quality1:default"
_MULTI_SOURCE_RESOLVER_VERSION = "nix-static-v2"


def _resolver_identity(bindings: Sequence[OpsGraphSourceBindingConfig]) -> str:
    payload = [
        [
            item.binding_id,
            item.role,
            item.input_name,
            item.resolution_policy,
            item.selection_policy_id,
        ]
        for item in sorted(bindings, key=lambda binding: binding.binding_id)
    ]
    encoded = json.dumps(
        {"resolver_version": _MULTI_SOURCE_RESOLVER_VERSION, "bindings": payload},
        separators=(",", ":"),
        ensure_ascii=True,
        sort_keys=True,
    ).encode()
    return "resolver1:" + _MULTI_SOURCE_RESOLVER_VERSION + "-" + hashlib.sha256(
        encoded
    ).hexdigest()[:24]


def _multi_source_source_generation(
    snapshots: Sequence[SourceSnapshot],
) -> str:
    ordered = tuple(sorted(snapshots, key=lambda item: item.binding.binding_id))
    if not ordered:
        raise MultiSourceCaptureError(
            "source binding inventory is unsupported", category="source_invalid"
        )
    graph_ids = {item.binding.graph_id for item in ordered}
    if len(graph_ids) != 1:
        raise MultiSourceCaptureError(
            "source binding inventory is invalid", category="source_invalid"
        )
    vector = []
    for snapshot in ordered:
        vector.append({
            "binding_id": snapshot.binding.binding_id,
            "binding_revision": snapshot.binding.revision,
            "snapshot_id": snapshot.snapshot_id,
        })
    payload = {
        "algorithm": "multi-source-snapshot-vector-v1",
        "graph_id": next(iter(graph_ids)),
        "snapshot_vector": vector,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "sg1:" + hashlib.sha256(encoded).hexdigest()


def multi_source_config_generation(graph: OpsGraphConfig) -> str:
    """Bind semantic configuration without reading physical source locations."""

    configured = tuple(
        sorted(graph.effective_source_bindings, key=lambda item: item.binding_id)
    )
    bindings = tuple(item.domain_binding(graph.id) for item in configured)
    configuration_identity = multi_source_configuration_id(graph.id, bindings)
    resolver_identity = _resolver_identity(configured)
    payload = {
        "algorithm": "multi-source-semantic-configuration-v1",
        "graph_id": graph.id,
        "configuration_identity": configuration_identity,
        "extractor_capability_identity": _MULTI_SOURCE_EXTRACTOR_IDENTITY,
        "resolver_identity": resolver_identity,
        "canonicalizer_identity": _MULTI_SOURCE_CANONICALIZER_IDENTITY,
        "semantic_contract_identity": _MULTI_SOURCE_SEMANTIC_IDENTITY,
        "quality_rule_identity": _MULTI_SOURCE_QUALITY_IDENTITY,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "cg1:" + hashlib.sha256(encoded).hexdigest()


def multi_source_semantic_identities(
    graph: OpsGraphConfig,
) -> tuple[str, str, str, str, str]:
    """Return the path-free semantic identities bound by a portable manifest."""

    configured = tuple(
        sorted(graph.effective_source_bindings, key=lambda item: item.binding_id)
    )
    return (
        _MULTI_SOURCE_EXTRACTOR_IDENTITY,
        _resolver_identity(configured),
        _MULTI_SOURCE_CANONICALIZER_IDENTITY,
        _MULTI_SOURCE_SEMANTIC_IDENTITY,
        _MULTI_SOURCE_QUALITY_IDENTITY,
    )


def capture_multi_source_candidate(graph: OpsGraphConfig) -> MultiSourceCandidateBundle:
    """Capture every binding, resolve one bound candidate, then reverify all inputs."""

    with tempfile.TemporaryDirectory(prefix="repomap-multi-source-") as temporary:
        captured = _capture_inventory(
            graph,
            stage_root=Path(temporary),
            discover_fn=discover_repository,
        )
        observations: list[RawObservation] = []
        module_exports: dict[str, Mapping[str, str | tuple[str, ...]]] = {}
        for source in captured:
            extraction_root = source.staged_root or source.root
            try:
                extracted = tuple(
                    extract_observations_from_repository_files(
                        extraction_root,
                        source.files,
                        nix_flake_ref=source.config.alias,
                        include_nix_input_references=True,
                    )
                )
            except MultiSourceCaptureError:
                raise
            except (OSError, UnicodeError, ValueError) as error:
                raise MultiSourceCaptureError(
                    "source capture failed", category="source_capture"
                ) from error
            module_exports[source.config.binding_id] = _module_exports(
                source, extracted
            )
            observations.extend(
                _namespaced_observation(item, source)
                for item in extracted
                if item.kind != "nix.module_export"
            )

        _validate_provenance(observations, captured)
        domain_bindings = tuple(item.config.domain_binding(graph.id) for item in captured)
        configuration_identity = multi_source_configuration_id(
            graph.id, domain_bindings
        )
        resolver_identity = _resolver_identity(tuple(item.config for item in captured))
        candidate = GraphCandidate.create(
            graph.id,
            tuple(item.snapshot for item in captured),
            configuration_identity=configuration_identity,
            extractor_capability_identity=_MULTI_SOURCE_EXTRACTOR_IDENTITY,
            resolver_identity=resolver_identity,
            canonicalizer_identity=_MULTI_SOURCE_CANONICALIZER_IDENTITY,
            semantic_contract_identity=_MULTI_SOURCE_SEMANTIC_IDENTITY,
            quality_rule_identity=_MULTI_SOURCE_QUALITY_IDENTITY,
        )
        views = tuple(
            _binding_view(
                item,
                module_exports.get(item.config.binding_id, {}),
            )
            for item in captured
        )
        try:
            resolutions = resolve_nix_relations(observations, views)
        except MultiSourceCaptureError:
            raise
        except (OSError, UnicodeError, ValueError) as error:
            raise MultiSourceCaptureError(
                "source relation resolution failed", category="source_capture"
            ) from error

        # One final inventory pass covers mutations to any earlier or later
        # binding.  The candidate and all extracted observations remain staged
        # until this whole-vector comparison succeeds.
        try:
            final_captured = _capture_inventory(
                graph,
                discover_fn=discover_repository,
            )
        except MultiSourceCaptureError:
            raise
        if tuple(item.snapshot for item in final_captured) != tuple(
            item.snapshot for item in captured
        ):
            raise MultiSourceCaptureError(
                "source binding changed during capture", category="source_changed"
            )

        resolution_by_source = {item.observation.source_id: item for item in resolutions}
        final: list[RawObservation] = []
        for observation in observations:
            resolution = resolution_by_source.get(observation.source_id)
            if resolution is not None:
                final.append(_resolved_observation(
                    resolution,
                    candidate_id=candidate.candidate_id,
                ))
                continue
            metadata = dict(observation.metadata)
            metadata["candidate_id"] = candidate.candidate_id
            final.append(replace(observation, metadata=metadata))
        _validate_provenance(
            final,
            captured,
            candidate_id=candidate.candidate_id,
        )
        privacy = (
            "public-dev"
            if graph.privacy == "public-dev"
            and all(item.config.privacy == "public-dev" for item in captured)
            else "private-ops"
        )
        snapshots = tuple(item.snapshot for item in captured)
        return MultiSourceCandidateBundle(
            candidate,
            tuple(final),
            resolutions,
            privacy,
            _multi_source_source_generation(snapshots),
            multi_source_config_generation(graph),
        )


def capture_sealed_multi_source_candidate(
    graph_id: str,
    bindings: Sequence[SealedSourceBinding],
    *,
    expected_snapshot_vector: Sequence[tuple[str, int, str]],
) -> MultiSourceCandidateBundle:
    """Run the authoritative path-based engine over verified command-owned roots."""

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
    result = capture_multi_source_candidate(graph)
    if result.candidate.snapshot_vector != tuple(expected_snapshot_vector):
        raise MultiSourceCaptureError(
            "sealed source inventory disagrees with manifest",
            category="source_changed",
        )
    return result


def scan_multi_source_generations(graph: OpsGraphConfig) -> MultiSourceGenerationScan:
    """Derive multi-source fences from discovery manifests without semantics."""

    if not graph.explicit_source_bindings:
        graph = replace(
            graph,
            source_bindings=graph.effective_source_bindings,
            explicit_source_bindings=True,
        )
    captured = _capture_inventory(graph, discover_fn=discover_repository)
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
