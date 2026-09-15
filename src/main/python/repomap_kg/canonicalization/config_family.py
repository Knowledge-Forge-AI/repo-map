"""Configuration canonicalization family handlers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repomap_kg.canonicalization.records import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
)
from repomap_kg.canonicalization.diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization.diagnostic_helpers import (
    _append_raw_target_diagnostic,
    _graph_key_error_category,
)
from repomap_kg.canonicalization.edge_helpers import _upsert_config_edge
from repomap_kg.canonicalization.evidence_helpers import _evidence_from_observation
from repomap_kg.canonicalization.metadata_helpers import (
    _append_metadata_text,
    _metadata_text,
)
from repomap_kg.canonicalization.node_edge_helpers import (
    _display_name_from_key,
    _node_kind_from_key,
    _upsert_node,
)
from repomap_kg.graph.keys import (
    GraphKeyError,
    config_document_key,
    config_path_key,
    file_key,
    parse_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


def _canonicalize_config_definition_observation(
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
        target_key, display_name, node_metadata, edge_metadata = (
            _config_definition_target(observation, ordinal, diagnostics)
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
        display_name=display_name,
        metadata=node_metadata,
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
    edge_key = _upsert_config_edge(
        edges,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
        metadata=edge_metadata,
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_config_reference_observation(
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
        source_key = _config_reference_source_key(observation)
        target_key = _config_reference_target_key(observation, ordinal, diagnostics)
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
        kind=_node_kind_from_key(source_key),
        display_name=_display_name_from_key(source_key),
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
    edge_key = _upsert_config_edge(
        edges,
        source_key=source_key,
        kind="references",
        target_key=target_key,
        metadata=_config_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _config_definition_target(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    if observation.kind == "config.document":
        target_key = config_document_key(observation.path)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _config_document_node_metadata(observation.metadata)
        display_name = _metadata_text(observation.metadata, "document_role")
        return (
            target_key,
            display_name or observation.path,
            metadata,
            _config_define_edge_metadata(metadata),
        )
    pointer = _metadata_text(observation.metadata, "pointer") or observation.name
    if not isinstance(pointer, str) or not pointer.strip():
        raise GraphKeyError("config.path observation requires pointer metadata")
    target_key = config_path_key(observation.path, pointer)
    _append_raw_target_diagnostic(observation, ordinal, diagnostics)
    metadata = _config_path_node_metadata(observation.metadata)
    return target_key, pointer, metadata, _config_define_edge_metadata(metadata)

def _config_reference_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_path_key")
    if source_key is not None:
        parsed = parse_key(source_key)
        if parsed.namespace == "config.path":
            return source_key
        raise GraphKeyError("config.reference source_path_key must be config.path")
    pointer = _metadata_text(observation.metadata, "pointer") or observation.name
    if not isinstance(pointer, str) or not pointer.strip():
        raise GraphKeyError("config.reference observation requires pointer metadata")
    return config_path_key(observation.path, pointer)

def _config_reference_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    if observation.target is None:
        placeholder_key = unknown_key("config.reference", "missing-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="config.reference observation requires target",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=None,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key
    try:
        parse_key(observation.target)
    except GraphKeyError as error:
        placeholder_key = unknown_key("config.reference", "malformed-target")
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
    return observation.target

def _config_document_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "top_level_type",
        "document_role",
        "path_count",
        "record_count",
        "parse_error_count",
        "profile",
        "document_count",
        "duplicate_key_policy",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _config_path_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "pointer",
        "display_path",
        "value_type",
        "container_type",
        "redacted",
        "redaction_reason",
        "value_summary",
        "array_policy",
        "item_count",
        "value_summaries",
        "stable_member_key",
        "profile",
        "document_index",
        "yaml_tag",
        "anchor",
        "alias",
        "merge_key",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _config_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("format", "formats"),
        ("document_role", "document_roles"),
        ("pointer", "pointers"),
        ("value_type", "value_types"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    return summary

def _config_reference_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("reference_kind", "reference_kinds"),
        ("raw_key", "raw_keys"),
        ("raw_value_summary", "raw_value_summaries"),
        ("resolution_reason", "resolution_reasons"),
        ("pointer", "pointers"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    redacted = metadata.get("redacted")
    if isinstance(redacted, bool):
        summary["redacted_observed"] = redacted
    return summary
