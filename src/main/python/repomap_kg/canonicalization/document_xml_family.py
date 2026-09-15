"""XML document-family canonicalization handlers."""

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
from repomap_kg.canonicalization.diagnostic_helpers import _graph_key_error_category
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
    parse_key,
    unknown_key,
    xml_attribute_key,
    xml_document_key,
    xml_element_key,
)
from repomap_kg.observations.raw import RawObservation

def _canonicalize_xml_definition_observation(
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
            _xml_definition_target(observation)
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
    edge_key = _upsert_xml_edge(
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

def _canonicalize_xml_reference_observation(
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
        source_key = _xml_reference_source_key(observation)
        target_key = _xml_reference_target_key(observation, ordinal, diagnostics)
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
        metadata=_xml_reference_source_node_metadata(observation.metadata),
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
    edge_key = _upsert_xml_edge(
        edges,
        source_key=source_key,
        kind="references",
        target_key=target_key,
        metadata=_xml_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _xml_definition_target(
    observation: RawObservation,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    if observation.kind == "xml.document":
        target_key = xml_document_key(observation.path)
        metadata = _xml_document_node_metadata(observation.metadata)
        return target_key, observation.path, metadata, _xml_define_edge_metadata(metadata)
    if observation.kind == "xml.element":
        pointer = _metadata_text(observation.metadata, "xml_pointer") or observation.name
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError("xml.element observation requires xml_pointer metadata")
        target_key = xml_element_key(observation.path, pointer)
        metadata = _xml_element_node_metadata(observation.metadata)
        display = _metadata_text(observation.metadata, "element_name") or pointer
        return target_key, display, metadata, _xml_define_edge_metadata(metadata)
    if observation.kind == "xml.attribute":
        pointer = _metadata_text(observation.metadata, "element_pointer")
        attribute_name = _metadata_text(observation.metadata, "attribute_name")
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError("xml.attribute observation requires element_pointer metadata")
        if not isinstance(attribute_name, str) or not attribute_name.strip():
            raise GraphKeyError("xml.attribute observation requires attribute_name metadata")
        target_key = xml_attribute_key(observation.path, pointer, attribute_name)
        metadata = _xml_attribute_node_metadata(observation.metadata)
        return target_key, attribute_name, metadata, _xml_define_edge_metadata(metadata)
    raise GraphKeyError(f"unsupported XML definition kind: {observation.kind}")

def _xml_reference_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is None:
        raise GraphKeyError("xml.reference observation requires source_key metadata")
    parsed = parse_key(source_key)
    if parsed.namespace not in ("xml.element", "xml.attribute"):
        raise GraphKeyError("xml.reference source_key must be xml.element or xml.attribute")
    return source_key

def _xml_reference_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    if observation.target is None:
        placeholder_key = unknown_key("xml.reference", "missing-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="xml.reference observation requires target",
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
        placeholder_key = unknown_key("xml.reference", "malformed-target")
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

def _xml_document_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "safety_mode",
        "root_tag",
        "root_local_name",
        "root_namespace_uri",
        "namespace_summary",
        "document_role",
        "element_count",
        "attribute_count",
        "reference_count",
        "parse_error_count",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _xml_element_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "safety_mode",
        "element_name",
        "local_name",
        "namespace_uri",
        "xml_pointer",
        "attribute_count",
        "child_count",
        "identity_mode",
        "role_hint",
        "text_summary",
        "bean_id",
        "class_name",
        "property_name",
        "bean_ref",
        "maven_group_id",
        "maven_artifact_id",
        "maven_version",
        "redacted",
        "redaction_reason",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _xml_attribute_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "safety_mode",
        "element_pointer",
        "attribute_name",
        "local_name",
        "namespace_uri",
        "semantic_key",
        "value_type",
        "value_summary",
        "redacted",
        "redaction_reason",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _xml_reference_source_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("format", "parser", "safety_mode", "element_pointer", "source_kind"):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _xml_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("format", "formats"),
        ("xml_pointer", "xml_pointers"),
        ("element_pointer", "element_pointers"),
        ("attribute_name", "attributes"),
        ("document_role", "document_roles"),
        ("role_hint", "role_hints"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    return summary

def _xml_reference_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("reference_kind", "reference_kinds"),
        ("source_kind", "source_kinds"),
        ("raw_value_summary", "raw_value_summaries"),
        ("resolution_reason", "resolution_reasons"),
        ("element_pointer", "element_pointers"),
        ("attribute_name", "attributes"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    redacted = metadata.get("redacted")
    if isinstance(redacted, bool):
        summary["redacted_observed"] = redacted
    return summary

def _upsert_xml_edge(
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
