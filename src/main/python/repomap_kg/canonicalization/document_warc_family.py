"""WARC document-family canonicalization handlers."""

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
from repomap_kg.canonicalization.diagnostic_helpers import _graph_key_error_category
from repomap_kg.canonicalization.edge_helpers import _upsert_config_edge
from repomap_kg.canonicalization.evidence_helpers import _evidence_from_observation
from repomap_kg.canonicalization.metadata_helpers import _metadata_text
from repomap_kg.canonicalization.node_edge_helpers import (
    _display_name_from_key,
    _node_kind_from_key,
    _upsert_node,
)
from repomap_kg.graph.keys import (
    GraphKeyError,
    file_key,
    parse_key,
    unknown_key,
    warc_document_key,
)
from repomap_kg.observations.raw import RawObservation

def _canonicalize_warc_definition_observation(
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
        source_key = _warc_definition_source_key(observation)
        target_key = _warc_definition_target_key(observation)
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
        display_name=observation.name or _display_name_from_key(target_key),
        metadata=_warc_node_metadata(observation.metadata),
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
        metadata=_warc_define_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_warc_reference_observation(
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
        source_key = _warc_reference_source_key(observation)
        target_key = _warc_reference_target_key(observation)
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
        metadata=_warc_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _warc_definition_source_key(observation: RawObservation) -> str:
    if observation.kind == "warc.document":
        return file_key(observation.path)
    document_key = _metadata_text(observation.metadata, "document_key")
    if document_key is None:
        raise GraphKeyError("warc.record observation requires document_key")
    parsed = parse_key(document_key)
    if parsed.namespace != "warc.document":
        raise GraphKeyError("warc.record document_key must be warc.document")
    return document_key

def _warc_definition_target_key(observation: RawObservation) -> str:
    if observation.kind == "warc.document" and observation.target is None:
        return warc_document_key(observation.path)
    if observation.target is None:
        raise GraphKeyError(f"{observation.kind} observation requires target")
    parsed = parse_key(observation.target)
    if parsed.namespace != observation.kind:
        raise GraphKeyError(f"{observation.kind} target must use {observation.kind}")
    return observation.target

def _warc_reference_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is None:
        raise GraphKeyError("warc.reference observation requires source_key")
    parsed = parse_key(source_key)
    if parsed.namespace not in ("warc.document", "warc.record"):
        raise GraphKeyError(
            "warc.reference source_key must be warc.document or warc.record"
        )
    return source_key

def _warc_reference_target_key(observation: RawObservation) -> str:
    if observation.target is None:
        return unknown_key("warc.reference", "missing-target")
    parse_key(observation.target)
    return observation.target

def _warc_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "format",
        "warc_version",
        "record_count",
        "parsed_record_count",
        "skipped_record_count",
        "routed_payload_count",
        "record_type",
        "record_ordinal",
        "identity_source",
        "identity_strength",
        "duplicate_identity",
        "duplicate_disambiguator",
        "target_uri_summary",
        "target_uri_redacted",
        "warc_date",
        "content_type",
        "payload_byte_length",
        "extractor_route",
        "skip_reason",
    }
    return {key: value for key, value in metadata.items() if key in allowed}

def _warc_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "format",
        "warc_version",
        "record_type",
        "record_ordinal",
        "identity_source",
        "identity_strength",
        "duplicate_identity",
        "extractor_route",
        "skip_reason",
    }
    return {key: value for key, value in metadata.items() if key in allowed}

def _warc_reference_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "reference_kind",
        "not_fetched",
        "target_kind",
        "target_uri_summary",
        "target_uri_redacted",
        "record_type",
        "record_ordinal",
    }
    return {key: value for key, value in metadata.items() if key in allowed}
