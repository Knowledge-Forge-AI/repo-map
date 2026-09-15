"""Nix canonicalization handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
    canonical_edge_key,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.diagnostic_helpers import (
    _graph_key_error_category,
)
from repomap_kg.canonicalization.evidence_helpers import _evidence_from_observation
from repomap_kg.canonicalization._nix_multi_source import (
    multi_source_opaque_target_key,
    nix_import_edge_metadata as _nix_import_edge_metadata,
)
from repomap_kg.canonicalization.metadata_helpers import (
    _append_metadata_text,
    _metadata_text,
)
from repomap_kg.canonicalization.node_edge_helpers import (
    _display_name_from_key,
    _node_kind_from_key,
    _upsert_edge,
    _upsert_node,
)
from repomap_kg.graph.keys import (
    GRAPH_KEY_VERSION,
    GraphKeyError,
    dynamic_key,
    file_key,
    nix_app_key,
    nix_check_key,
    nix_dev_shell_key,
    nix_output_key,
    nix_package_key,
    parse_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


NIX_OUTPUT_SECTION_NAMES = frozenset(
    (
        "packages",
        "apps",
        "devShells",
        "checks",
        "nixosModules",
        "darwinModules",
        "homeManagerModules",
        "overlays",
        "formatter",
        "templates",
        "legacyPackages",
    )
)


def _canonicalize_nix_import_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        source_key = file_key(observation.path)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="path",
                value=observation.path,
            )
        )
        return

    target_key = _nix_import_target_key(observation, ordinal, diagnostics)
    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)

    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=_display_name_from_key(target_key),
        metadata={},
        confidence=observation.confidence,
    )
    node_evidence_links.extend(
        (
            CanonicalNodeEvidenceLink(
                canonical_key=source_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
            CanonicalNodeEvidenceLink(
                canonical_key=target_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
        )
    )

    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind="sources",
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind="sources",
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=_nix_import_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_nix_output_section_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        source_key = file_key(observation.path)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="path",
                value=observation.path,
            )
        )
        return

    section = _metadata_text(observation.metadata, "section") or observation.name
    if section not in NIX_OUTPUT_SECTION_NAMES:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="unregistered_nix_output_section",
                message="nix output section is not registered",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.section",
                value=section,
            )
        )
        return

    target_key = nix_output_key(source_key, f"section/{section}")
    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)

    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind="nix.output",
        display_name=f"{section} output section",
        metadata=_nix_output_section_node_metadata(observation.metadata, section),
        confidence=observation.confidence,
    )
    node_evidence_links.extend(
        (
            CanonicalNodeEvidenceLink(
                canonical_key=source_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
            CanonicalNodeEvidenceLink(
                canonical_key=target_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="observed",
            ),
        )
    )

    define_edge_key = _upsert_nix_edge(
        edges,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
        metadata=_nix_output_section_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=define_edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_nix_output_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        source_key = file_key(observation.path)
        target_key, target_display_name, define_metadata = _nix_output_target(
            observation,
            ordinal,
            diagnostics,
        )
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=observation.target,
            )
        )
        return

    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)

    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=target_display_name,
        metadata={},
        confidence=observation.confidence,
    )
    node_evidence_links.extend(
        (
            CanonicalNodeEvidenceLink(
                canonical_key=source_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
            CanonicalNodeEvidenceLink(
                canonical_key=target_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="observed",
            ),
        )
    )

    define_edge_key = _upsert_nix_edge(
        edges,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
        metadata=define_metadata,
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=define_edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

    program_path = _metadata_text(observation.metadata, "program_path")
    if observation.kind != "nix.app" or program_path is None:
        return
    try:
        program_key = file_key(program_path)
    except GraphKeyError as error:
        program_key = unknown_key("file", "repo-escaping-nix-app-program")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.program_path",
                value=program_path,
                placeholder_key=program_key,
            )
        )

    _upsert_node(
        nodes,
        canonical_key=program_key,
        kind=_node_kind_from_key(program_key),
        display_name=_display_name_from_key(program_key),
        metadata={},
        confidence=observation.confidence,
    )
    node_evidence_links.append(
        CanonicalNodeEvidenceLink(
            canonical_key=program_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="inferred_from_edge",
        )
    )
    exposes_edge_key = _upsert_nix_edge(
        edges,
        source_key=target_key,
        kind="exposes_script",
        target_key=program_key,
        metadata=_nix_app_exposes_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=exposes_edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _nix_output_section_node_metadata(
    metadata: Mapping[str, Any],
    section: str,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "section": section,
        "identity_precision": "section_category",
        "concrete_output_identity": False,
    }
    for key in ("section_family", "scope", "shape", "confidence_reason"):
        value = _metadata_text(metadata, key)
        if value is not None:
            summary[key] = value
    return summary


def _nix_output_section_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("section_family", "scope", "shape", "confidence_reason"):
        value = _metadata_text(metadata, key)
        if value is not None:
            summary[key] = value
    return summary


def _nix_import_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    opaque_target = multi_source_opaque_target_key(observation, ordinal, diagnostics)
    if opaque_target is not None:
        return opaque_target
    resolved_path = _metadata_text(observation.metadata, "resolved_path")
    if resolved_path is not None:
        try:
            return file_key(resolved_path)
        except GraphKeyError as error:
            placeholder_key = unknown_key("file", "repo-escaping-nix-import")
            diagnostics.append(
                CanonicalizationDiagnostic(
                    severity="warning",
                    category=_graph_key_error_category(error),
                    message=str(error),
                    raw_observation_ordinal=ordinal,
                    raw_source_id=observation.source_id,
                    path=observation.path,
                    field="metadata.resolved_path",
                    value=resolved_path,
                    placeholder_key=placeholder_key,
                )
            )
            return placeholder_key

    dynamic_reason = _metadata_text(observation.metadata, "dynamic_reason")
    if dynamic_reason is not None:
        placeholder_key = dynamic_key("file", dynamic_reason)
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="info",
                category="dynamic_target",
                message="dynamic Nix import represented by placeholder",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.dynamic_reason",
                value=dynamic_reason,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key

    if observation.target is not None:
        try:
            parsed = parse_key(observation.target)
        except GraphKeyError as error:
            placeholder_key = unknown_key("file", "unresolved-nix-import")
            diagnostics.append(
                CanonicalizationDiagnostic(
                    severity="warning",
                    category=_graph_key_error_category(error),
                    message=f"raw target is not a valid canonical key: {error}",
                    raw_observation_ordinal=ordinal,
                    raw_source_id=observation.source_id,
                    path=observation.path,
                    field="target",
                    value=observation.target,
                    placeholder_key=placeholder_key,
                )
            )
            return placeholder_key
        if parsed.namespace in ("file", "unknown", "dynamic", "external"):
            return observation.target

    placeholder_key = unknown_key("file", "unresolved-nix-import")
    diagnostics.append(
        CanonicalizationDiagnostic(
            severity="warning",
            category="unknown_target",
            message="Nix import target could not be resolved",
            raw_observation_ordinal=ordinal,
            raw_source_id=observation.source_id,
            path=observation.path,
            field="metadata.resolved_path",
            value=resolved_path,
            placeholder_key=placeholder_key,
        )
    )
    return placeholder_key


def _nix_output_target(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> tuple[str, str, dict[str, Any]]:
    flake_ref = _metadata_text(observation.metadata, "flake_ref")
    system = _metadata_text(observation.metadata, "system")
    name = _metadata_text(observation.metadata, "name") or observation.name
    missing_fields = []
    if flake_ref is None:
        missing_fields.append("metadata.flake_ref")
    if system is None:
        missing_fields.append("metadata.system")
    if not isinstance(name, str) or not name.strip():
        missing_fields.append("metadata.name")
    if missing_fields:
        placeholder_key = unknown_key(observation.kind, "missing-output-identity")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message=f"{observation.kind} observation requires flake_ref, system, and name metadata",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field=",".join(missing_fields),
                value=None,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key, "missing-output-identity", {}

    assert flake_ref is not None
    assert system is not None
    assert isinstance(name, str)
    if observation.kind == "nix.app":
        target_key = nix_app_key(flake_ref, system, name)
    elif observation.kind == "nix.package":
        target_key = nix_package_key(flake_ref, system, name)
    elif observation.kind == "nix.devShell":
        target_key = nix_dev_shell_key(flake_ref, system, name)
    elif observation.kind == "nix.check":
        target_key = nix_check_key(flake_ref, system, name)
    else:
        raise GraphKeyError(f"unsupported Nix output kind: {observation.kind}")
    return target_key, name, _nix_define_edge_metadata(observation.metadata)


def _nix_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    _append_metadata_text(summary, metadata, "flake_ref", "flake_refs")
    _append_metadata_text(summary, metadata, "system", "systems")
    _append_metadata_text(summary, metadata, "attr_path", "attr_paths")
    output_kind = _metadata_text(metadata, "output_kind")
    name = _metadata_text(metadata, "name")
    if output_kind is not None:
        summary["output_kinds"] = [output_kind]
    if output_kind == "app":
        _append_metadata_text(summary, metadata, "name", "apps")
    elif output_kind == "package":
        _append_metadata_text(summary, metadata, "name", "packages")
    elif output_kind == "devShell":
        _append_metadata_text(summary, metadata, "name", "devShells")
    elif output_kind == "check":
        _append_metadata_text(summary, metadata, "name", "checks")
    elif name is not None:
        summary["names"] = [name]
    return summary


def _nix_app_exposes_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    _append_metadata_text(summary, metadata, "flake_ref", "flake_refs")
    _append_metadata_text(summary, metadata, "system", "systems")
    _append_metadata_text(summary, metadata, "name", "apps")
    _append_metadata_text(summary, metadata, "program", "programs")
    _append_metadata_text(summary, metadata, "program_path", "program_paths")
    return summary


def _upsert_nix_edge(
    edges: dict[str, CanonicalEdge],
    *,
    source_key: str,
    kind: str,
    target_key: str,
    metadata: Mapping[str, Any],
    confidence: str,
) -> str:
    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=metadata,
        confidence=confidence,
    )
    return edge_key
