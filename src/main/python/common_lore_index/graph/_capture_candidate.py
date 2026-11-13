"""Cooperative assembly over two unchanged authoritative capture fences."""
from __future__ import annotations
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from common_lore_index.extractors.config.nix_resolver import NixBindingView, NixResolution
from common_lore_index.graph._capture_control import CaptureControl
from common_lore_index.graph._capture_identity import (
    _MULTI_SOURCE_CANONICALIZER_IDENTITY, _MULTI_SOURCE_EXTRACTOR_IDENTITY,
    _MULTI_SOURCE_QUALITY_IDENTITY, _MULTI_SOURCE_SEMANTIC_IDENTITY,
    _multi_source_source_generation, _resolver_identity, multi_source_config_generation,
)
from common_lore_index.graph.multi_source import GraphCandidate, multi_source_configuration_id
from common_lore_index.graph.multi_source_capture import MultiSourceCaptureError, _CapturedSource
from common_lore_index.graph.multi_source_routing import (
    MultiSourceCandidateBundle, _binding_view, _module_exports,
    _namespaced_observation, _resolved_observation, _validate_provenance,
)
from common_lore_index.observations.raw import RawObservation
from common_lore_index.ops.config_records import OpsGraphConfig


@dataclass(frozen=True)
class CaptureEngines:
    """Late facade lookups, retaining the original per-phase global seams."""
    inventory: Callable[[], Callable[..., tuple[_CapturedSource, ...]]]
    discover: Callable[[], Callable[..., Any]]
    extract: Callable[[], Callable[..., Any]]
    resolve: Callable[[], Callable[..., tuple[NixResolution, ...]]]


def _extract_sources(captured: Sequence[_CapturedSource], engines: CaptureEngines,
                     control: CaptureControl) -> tuple[list[RawObservation], dict[str, Mapping[str, str | tuple[str, ...]]]]:
    observations: list[RawObservation] = []
    exports: dict[str, Mapping[str, str | tuple[str, ...]]] = {}
    for source in captured:
        control.check()
        try:
            extracted = control.collect(engines.extract()(
                source.staged_root or source.root, source.files,
                nix_flake_ref=source.config.alias, include_nix_input_references=True,
                **control.keywords,
            ))
        except MultiSourceCaptureError:
            raise
        except (OSError, UnicodeError, ValueError) as error:
            raise MultiSourceCaptureError("source capture failed", category="source_capture") from error
        control.check()
        exports[source.config.binding_id] = _module_exports(source, extracted)
        control.extend_into(observations, (
            _namespaced_observation(item, source)
            for item in extracted if item.kind != "nix.module_export"
        ))
    return observations, exports


def _candidate_and_views(graph: OpsGraphConfig, captured: Sequence[_CapturedSource],
                         exports: Mapping[str, Mapping[str, str | tuple[str, ...]]]) -> tuple[GraphCandidate, tuple[NixBindingView, ...]]:
    domain_bindings = tuple(item.config.domain_binding(graph.id) for item in captured)
    candidate = GraphCandidate.create(
        graph.id, tuple(item.snapshot for item in captured),
        configuration_identity=multi_source_configuration_id(graph.id, domain_bindings),
        extractor_capability_identity=_MULTI_SOURCE_EXTRACTOR_IDENTITY,
        resolver_identity=_resolver_identity(tuple(item.config for item in captured)),
        canonicalizer_identity=_MULTI_SOURCE_CANONICALIZER_IDENTITY,
        semantic_contract_identity=_MULTI_SOURCE_SEMANTIC_IDENTITY,
        quality_rule_identity=_MULTI_SOURCE_QUALITY_IDENTITY,
    )
    return candidate, tuple(_binding_view(item, exports.get(item.config.binding_id, {})) for item in captured)


def _final_observations(observations: Sequence[RawObservation], resolutions: Sequence[NixResolution],
                        candidate: GraphCandidate, control: CaptureControl) -> list[RawObservation]:
    resolution_by_source = {item.observation.source_id: item for item in resolutions}
    final: list[RawObservation] = []
    for observation in observations:
        control.check()
        resolution = resolution_by_source.get(observation.source_id)
        if resolution is not None:
            final.append(_resolved_observation(resolution, candidate_id=candidate.candidate_id))
            continue
        metadata = dict(observation.metadata)
        metadata["candidate_id"] = candidate.candidate_id
        final.append(replace(observation, metadata=metadata))
    return final


def capture_candidate(graph: OpsGraphConfig, temporary: Path, engines: CaptureEngines,
                      control: CaptureControl, elide_discovery_hash: bool) -> MultiSourceCandidateBundle:
    control.check()
    captured = engines.inventory()(graph, stage_root=temporary, discover_fn=engines.discover(),
                                 elide_discovery_hash=elide_discovery_hash, **control.keywords)
    observations, exports = _extract_sources(captured, engines, control)
    control.check()
    _validate_provenance(observations, captured)
    candidate, views = _candidate_and_views(graph, captured, exports)
    control.check()
    try:
        resolutions = engines.resolve()(observations, views)
    except MultiSourceCaptureError:
        raise
    except (OSError, UnicodeError, ValueError) as error:
        raise MultiSourceCaptureError("source relation resolution failed", category="source_capture") from error
    control.check()
    final_captured = engines.inventory()(graph, discover_fn=engines.discover(),
                                       elide_discovery_hash=elide_discovery_hash, **control.keywords)
    if tuple(item.snapshot for item in final_captured) != tuple(item.snapshot for item in captured):
        raise MultiSourceCaptureError("source binding changed during capture", category="source_changed")
    final = _final_observations(observations, resolutions, candidate, control)
    control.check()
    _validate_provenance(final, captured, candidate_id=candidate.candidate_id)
    privacy = ("public-dev" if graph.privacy == "public-dev"
               and all(item.config.privacy == "public-dev" for item in captured) else "private-ops")
    control.check()
    return MultiSourceCandidateBundle(candidate, tuple(final), resolutions, privacy,
        _multi_source_source_generation(tuple(item.snapshot for item in captured)), multi_source_config_generation(graph))
