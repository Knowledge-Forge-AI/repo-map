"""HTML document-family canonicalization handlers."""

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
    _append_raw_target_diagnostic,
    _graph_key_error_category,
)
from repomap_kg.canonicalization.evidence_helpers import _evidence_from_observation
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
    file_key,
    html_document_key,
    html_element_key,
    parse_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation

def _canonicalize_html_definition_observation(
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
            _html_definition_target(observation, ordinal, diagnostics)
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
    edge_key = _upsert_html_edge(
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

def _canonicalize_html_reference_observation(
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
        source_key = _html_reference_source_key(observation)
        target_key = _html_reference_target_key(observation, ordinal, diagnostics)
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
        metadata=_html_reference_source_node_metadata(observation.metadata),
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
    edge_key = _upsert_html_edge(
        edges,
        source_key=source_key,
        kind="references",
        target_key=target_key,
        metadata=_html_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _html_definition_target(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    if observation.kind == "html.document":
        target_key = html_document_key(observation.path)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _html_document_node_metadata(observation.metadata)
        display_name = _metadata_text(observation.metadata, "title")
        return (
            target_key,
            display_name or observation.path,
            metadata,
            _html_define_edge_metadata(metadata),
        )
    if observation.kind == "html.element":
        pointer = _metadata_text(observation.metadata, "pointer") or observation.name
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError("html.element observation requires pointer metadata")
        target_key = html_element_key(observation.path, pointer)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _html_element_node_metadata(observation.metadata)
        display_name = _metadata_text(observation.metadata, "tag") or pointer
        return target_key, display_name, metadata, _html_define_edge_metadata(metadata)
    target_key = _html_heading_target_key(observation)
    _append_raw_target_diagnostic(observation, ordinal, diagnostics)
    parsed = parse_key(target_key)
    if parsed.namespace == "html.anchor":
        metadata = _html_anchor_node_metadata(observation.metadata)
    elif parsed.namespace == "html.element":
        metadata = _html_heading_element_node_metadata(observation.metadata)
    else:
        raise GraphKeyError("html.heading target must be html.anchor or html.element")
    display_name = _metadata_text(observation.metadata, "text_summary")
    return target_key, display_name or _display_name_from_key(target_key), metadata, (
        _html_define_edge_metadata(metadata)
    )

def _html_heading_target_key(observation: RawObservation) -> str:
    if observation.target is not None:
        parsed = parse_key(observation.target)
        if parsed.namespace in ("html.anchor", "html.element"):
            return observation.target
        raise GraphKeyError("html.heading target must be html.anchor or html.element")
    source_key = _metadata_text(observation.metadata, "source_element_key")
    if source_key is not None:
        parsed = parse_key(source_key)
        if parsed.namespace == "html.element":
            return source_key
        raise GraphKeyError("html.heading source_element_key must be html.element")
    pointer = _metadata_text(observation.metadata, "source_element_pointer")
    if not isinstance(pointer, str) or not pointer.strip():
        raise GraphKeyError("html.heading observation requires source element pointer")
    return html_element_key(observation.path, pointer)

def _html_reference_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is not None:
        parsed = parse_key(source_key)
        if parsed.namespace in ("html.element", "html.anchor"):
            return source_key
        raise GraphKeyError("html reference source_key must be html.element or html.anchor")
    pointer = (
        _metadata_text(observation.metadata, "source_element_pointer")
        or _metadata_text(observation.metadata, "pointer")
        or observation.name
    )
    if not isinstance(pointer, str) or not pointer.strip():
        raise GraphKeyError("html reference observation requires source pointer")
    return html_element_key(observation.path, pointer)

def _html_reference_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    if observation.target is None:
        placeholder_key = unknown_key("html.reference", "missing-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="html reference observation requires target",
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
        placeholder_key = unknown_key("html.reference", "malformed-target")
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

def _html_document_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "parser_mode",
        "title",
        "doctype",
        "root_element",
        "language",
        "parse_warning_count",
        "element_count",
        "anchor_count",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _html_element_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "parser_mode",
        "tag",
        "pointer",
        "id",
        "id_is_unique",
        "classes",
        "attribute_count",
        "child_count",
        "text_summary",
        "structural_identity",
        "content_policy",
        "content_length",
        "redacted",
        "redaction_reason",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _html_anchor_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "parser_mode",
        "heading_level",
        "source_element_pointer",
        "source_element_key",
        "id",
        "id_is_unique",
        "text_summary",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _html_heading_element_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _html_anchor_node_metadata(metadata)
    summary["heading_without_anchor"] = True
    return summary

def _html_reference_source_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("format", "parser", "parser_mode", "tag", "pointer"):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _html_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("format", "formats"),
        ("tag", "tags"),
        ("pointer", "pointers"),
        ("heading_level", "heading_levels"),
        ("structural_identity", "structural_identity_modes"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    return summary

def _html_reference_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("reference_kind", "reference_kinds"),
        ("attribute", "attributes"),
        ("raw_value_summary", "raw_value_summaries"),
        ("resolution_reason", "resolution_reasons"),
        ("tag", "tags"),
        ("pointer", "pointers"),
        ("source_element_pointer", "source_element_pointers"),
        ("method", "methods"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    field_count = metadata.get("field_count")
    if isinstance(field_count, int):
        summary["field_counts"] = [field_count]
    redacted = metadata.get("redacted")
    if isinstance(redacted, bool):
        summary["redacted_observed"] = redacted
    return summary

def _upsert_html_edge(
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
