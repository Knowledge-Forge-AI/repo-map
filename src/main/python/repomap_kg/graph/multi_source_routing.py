"""Observation routing, Nix export mapping, and relation resolution across sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from repomap_kg.extractors.config.nix_resolver import (
    NixBindingView,
    NixResolution,
    ResolutionOutcome,
)
from repomap_kg.graph.discovery_records import FileInfo
from repomap_kg.graph.multi_source import (
    GraphCandidate,
    SourceKind,
    SourceSnapshot,
)
from repomap_kg.graph.multi_source_capture import (
    MultiSourceCaptureError,
    _CapturedSource,
)
from repomap_kg.graph.keys import (
    GraphKeyError,
    config_document_key,
    config_path_key,
    css_custom_property_key,
    css_document_key,
    css_rule_key,
    css_selector_key,
    doc_page_key,
    doc_section_key,
    file_key,
    html_anchor_key,
    html_document_key,
    html_element_key,
    parse_key,
    xml_attribute_key,
    xml_document_key,
    xml_element_key,
)
from repomap_kg.observations.raw import RawObservation


def _rebase_graph_key(key: str, alias: str) -> str:
    try:
        parsed = parse_key(key)
    except (GraphKeyError, ValueError):
        return key

    ns = parsed.namespace
    if ns == "file":
        file_path = "/".join(parsed.segments)
        return file_key(f"{alias}/{file_path}")

    if ns in {
        "doc.page",
        "doc.section",
        "config.document",
        "config.path",
        "css.document",
        "css.rule",
        "css.selector",
        "css.custom_property",
        "html.document",
        "html.element",
        "html.anchor",
        "xml.document",
        "xml.element",
        "xml.attribute",
    }:
        inner_file = parsed.segments[0]
        rebased_file = _rebase_graph_key(inner_file, alias)
        if ns == "doc.page":
            return doc_page_key(rebased_file)
        if ns == "doc.section":
            return doc_section_key(rebased_file, parsed.segments[1])
        if ns == "config.document":
            return config_document_key(rebased_file)
        if ns == "config.path":
            return config_path_key(rebased_file, parsed.segments[1])
        if ns == "css.document":
            return css_document_key(rebased_file)
        if ns == "css.rule":
            return css_rule_key(rebased_file, parsed.segments[1])
        if ns == "css.selector":
            return css_selector_key(rebased_file, parsed.segments[1])
        if ns == "css.custom_property":
            return css_custom_property_key(rebased_file, parsed.segments[1])
        if ns == "html.document":
            return html_document_key(rebased_file)
        if ns == "html.element":
            return html_element_key(rebased_file, parsed.segments[1])
        if ns == "html.anchor":
            return html_anchor_key(rebased_file, parsed.segments[1])
        if ns == "xml.document":
            return xml_document_key(rebased_file)
        if ns == "xml.element":
            return xml_element_key(rebased_file, parsed.segments[1])
        if ns == "xml.attribute":
            return xml_attribute_key(rebased_file, parsed.segments[1], parsed.segments[2])

    return key


@dataclass(frozen=True)
class MultiSourceCandidateBundle:
    candidate: GraphCandidate
    observations: tuple[RawObservation, ...]
    resolutions: tuple[NixResolution, ...]
    privacy: str
    source_generation: str = ""
    config_generation: str = ""


@dataclass(frozen=True)
class MultiSourceGenerationScan:
    """Cheap, path-free generation evidence for a configured constellation.

    ``files`` is ordered by binding identity and then source-relative path.  It
    deliberately contains only discovery records; semantic extraction and Nix
    resolution are owned by :func:`capture_multi_source_candidate`.
    """

    source_generation: str
    config_generation: str
    snapshots: tuple[SourceSnapshot, ...]
    files: tuple[FileInfo, ...]


@dataclass(frozen=True)
class SealedSourceBinding:
    """Validated semantic binding metadata plus one command-owned source view."""

    binding_id: str
    source_definition_id: str
    alias: str
    revision: int
    source_kind: SourceKind
    root: Path
    repository_scope: str
    logical_root: str
    privacy: str
    evidence_retention: str
    extractor_profile: str
    selection_policy_id: str
    resolution_policy: str
    role: str
    input_name: str | None


def _namespaced_observation(
    observation: RawObservation,
    source: _CapturedSource,
) -> RawObservation:
    alias = source.config.alias
    path = f"{alias}/{observation.path}"
    metadata = dict(observation.metadata)
    resolved = metadata.get("resolved_path")
    if isinstance(resolved, str):
        metadata["resolved_path"] = f"{alias}/{resolved}"
    for meta_key in ("source_key", "page_key", "source_element_key"):
        val = metadata.get(meta_key)
        if isinstance(val, str):
            metadata[meta_key] = _rebase_graph_key(val, alias)
    metadata.update({
        "graph_id": source.snapshot.binding.graph_id,
        "binding_id": source.config.binding_id,
        "binding_alias": alias,
        "binding_role": source.config.role,
        "binding_revision": source.config.revision,
        "snapshot_id": source.snapshot.snapshot_id,
        "snapshot_manifest_digest": source.snapshot.manifest_digest,
        "source_relative_path": observation.path,
    })
    target = observation.target
    if isinstance(target, str):
        target = _rebase_graph_key(target, alias)
    return replace(
        observation,
        source_id=f"{source.config.binding_id}:{observation.source_id}",
        path=path,
        name=path if observation.kind == "file" else observation.name,
        target=target,
        metadata=metadata,
    )


def _module_exports(
    source: _CapturedSource,
    extracted: Sequence[RawObservation],
) -> dict[str, str | tuple[str, ...]]:
    """Collect source-local literal Nix output mappings for the resolver."""

    files = {entry.relative_path for entry in source.snapshot.manifest_entries}
    mappings: dict[str, list[str]] = {}
    for observation in extracted:
        if observation.kind != "nix.module_export":
            continue
        module = observation.metadata.get("module_name")
        export_path = observation.metadata.get("resolved_path")
        if not isinstance(export_path, str):
            export_path = observation.metadata.get("export_path")
        if not isinstance(module, str) or not isinstance(export_path, str):
            continue
        if export_path.startswith("file:"):
            export_path = export_path.removeprefix("file:")
        if export_path.startswith(f"{source.config.alias}/"):
            export_path = export_path[len(source.config.alias) + 1:]
        export_path = export_path.removeprefix("./")
        if export_path in files:
            mappings.setdefault(module, []).append(export_path)
    return {
        module: values[0] if len(values) == 1 else tuple(sorted(set(values)))
        for module, values in mappings.items()
    }


def _binding_view(
    source: _CapturedSource,
    module_exports: Mapping[str, str | tuple[str, ...]],
) -> NixBindingView:
    """Build a resolver view for a captured source binding."""

    return NixBindingView(
        alias=source.config.alias,
        input_name=source.config.input_name or source.config.alias,
        files=frozenset(
            entry.relative_path for entry in source.snapshot.manifest_entries
        ),
        module_exports=dict(module_exports),
        binding_id=source.config.binding_id,
        snapshot_id=source.snapshot.snapshot_id,
    )


def _validate_provenance(
    observations: Sequence[RawObservation],
    captured: Sequence[_CapturedSource],
    *,
    candidate_id: str | None = None,
) -> None:
    by_binding_id = {item.config.binding_id: item for item in captured}
    by_alias = {item.config.alias: item for item in captured}
    for observation in observations:
        metadata = observation.metadata
        binding_id = metadata.get("binding_id")
        alias = metadata.get("binding_alias")
        role = metadata.get("binding_role")
        revision = metadata.get("binding_revision")
        snapshot_id = metadata.get("snapshot_id")
        manifest_digest = metadata.get("snapshot_manifest_digest")
        relative = metadata.get("source_relative_path")
        source = by_binding_id.get(binding_id) if isinstance(binding_id, str) else None
        if source is None or not isinstance(alias, str) or by_alias.get(alias) is not source:
            raise MultiSourceCaptureError(
                "source observation provenance is invalid", category="source_capture"
            )
        if (
            metadata.get("graph_id") != source.snapshot.binding.graph_id
            or role != source.config.role
            or revision != source.config.revision
            or snapshot_id != source.snapshot.snapshot_id
            or manifest_digest != source.snapshot.manifest_digest
            or not isinstance(relative, str)
            or observation.path != f"{alias}/{relative}"
            or not observation.source_id.startswith(f"{binding_id}:")
            or candidate_id is not None
            and metadata.get("candidate_id") != candidate_id
        ):
            raise MultiSourceCaptureError(
                "source observation provenance is invalid", category="source_capture"
            )


def _resolved_observation(
    resolution: NixResolution,
    *,
    candidate_id: str,
) -> RawObservation:
    observation = resolution.observation
    metadata = dict(observation.metadata)
    metadata.update({
        "candidate_id": candidate_id,
        "resolution_outcome": resolution.outcome.value,
        "resolution_evidence_class": resolution.evidence_class,
        "cross_binding": resolution.cross_binding,
        "source_binding": resolution.source_binding,
        "target_binding": resolution.target_binding,
    })
    if resolution.target_path is not None:
        metadata["resolved_path"] = resolution.target_path
        target = f"file:{resolution.target_path}"
    else:
        reason = f"nix-cross-source-{resolution.outcome.value}"
        if resolution.outcome is ResolutionOutcome.EVALUATION_DEPENDENT:
            metadata["dynamic_reason"] = reason
            target = f"dynamic:file:{reason}"
        else:
            metadata.pop("resolved_path", None)
            target = f"unknown:file:{reason}"
    return replace(observation, kind="nix.import", target=target, metadata=metadata)


__all__ = [
    "MultiSourceCandidateBundle",
    "MultiSourceGenerationScan",
    "SealedSourceBinding",
    "_binding_view",
    "_module_exports",
    "_namespaced_observation",
    "_resolved_observation",
    "_validate_provenance",
]
