"""Feed canonicalization family handlers."""

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
    feed_document_key,
    file_key,
    parse_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation


def _canonicalize_feed_definition_observation(
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
        source_key = _feed_definition_source_key(observation)
        target_key = _feed_definition_target_key(observation)
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
        metadata=_feed_node_metadata(observation.metadata),
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
    define_edge_key = _upsert_config_edge(
        edges,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
        metadata=_feed_define_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=define_edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )
    item_key = _metadata_text(observation.metadata, "item_key")
    if observation.kind in ("feed.author", "feed.category") and item_key is not None:
        parsed = parse_key(item_key)
        if parsed.namespace != "feed.item":
            diagnostics.append(
                CanonicalizationDiagnostic(
                    severity="error",
                    category="invalid_canonical_key",
                    message=f"{observation.kind} item_key must be feed.item",
                    raw_observation_ordinal=ordinal,
                    raw_source_id=observation.source_id,
                    path=observation.path,
                    field="metadata.item_key",
                    value=item_key,
                )
            )
            return
        _upsert_node(
            nodes,
            canonical_key=item_key,
            kind="feed.item",
            display_name=_display_name_from_key(item_key),
            metadata={},
            confidence=observation.confidence,
        )
        node_evidence_links.append(
            CanonicalNodeEvidenceLink(
                canonical_key=item_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            )
        )
        reference_edge_key = _upsert_config_edge(
            edges,
            source_key=item_key,
            kind="references",
            target_key=target_key,
            metadata=_feed_reference_edge_metadata(observation.metadata),
            confidence=observation.confidence,
        )
        edge_evidence_links.append(
            CanonicalEdgeEvidenceLink(
                edge_key=reference_edge_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="supports",
            )
        )

def _canonicalize_feed_reference_observation(
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
        source_key = _feed_reference_source_key(observation)
        target_key = _feed_reference_target_key(observation, ordinal, diagnostics)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.source_key",
                value=observation.metadata.get("source_key"),
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
        metadata=_feed_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _feed_definition_source_key(observation: RawObservation) -> str:
    if observation.kind == "feed.document":
        return file_key(observation.path)
    if observation.kind == "feed.channel":
        document_key = _metadata_text(observation.metadata, "document_key")
        if document_key is None:
            return feed_document_key(observation.path)
        parsed = parse_key(document_key)
        if parsed.namespace != "feed.document":
            raise GraphKeyError("feed.channel document_key must be feed.document")
        return document_key
    channel_key = _metadata_text(observation.metadata, "channel_key")
    if channel_key is None:
        raise GraphKeyError(f"{observation.kind} observation requires channel_key")
    parsed = parse_key(channel_key)
    if parsed.namespace != "feed.channel":
        raise GraphKeyError(f"{observation.kind} channel_key must be feed.channel")
    return channel_key

def _feed_definition_target_key(observation: RawObservation) -> str:
    if observation.kind == "feed.document" and observation.target is None:
        return feed_document_key(observation.path)
    if observation.target is None:
        raise GraphKeyError(f"{observation.kind} observation requires target")
    parsed = parse_key(observation.target)
    expected_namespace = observation.kind
    if parsed.namespace != expected_namespace:
        raise GraphKeyError(
            f"{observation.kind} target must use {expected_namespace} namespace"
        )
    return observation.target

def _feed_reference_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is None:
        raise GraphKeyError(f"{observation.kind} observation requires source_key")
    parsed = parse_key(source_key)
    if parsed.namespace not in ("feed.document", "feed.channel", "feed.item"):
        raise GraphKeyError(
            f"{observation.kind} source_key must be feed.document, feed.channel, or feed.item"
        )
    return source_key

def _feed_reference_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    if observation.target is None:
        placeholder_key = unknown_key("feed.reference", "missing-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message=f"{observation.kind} observation requires target",
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
        placeholder_key = unknown_key("feed.reference", "malformed-target")
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

def _feed_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "feed_format",
        "parser",
        "parser_mode",
        "top_level_type",
        "identity_source",
        "identity_strength",
        "duplicate_identity",
        "duplicate_disambiguator",
        "title",
        "name",
        "published_at",
        "updated_at",
        "email_redacted",
    }
    return {key: value for key, value in metadata.items() if key in allowed}

def _feed_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "feed_format",
        "identity_source",
        "identity_strength",
        "duplicate_identity",
        "duplicate_disambiguator",
        "parser_mode",
        "top_level_type",
    }
    return {key: value for key, value in metadata.items() if key in allowed}

def _feed_reference_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "feed_format",
        "scope",
        "attribute",
        "field",
        "rel",
        "mime_type",
        "length",
        "not_fetched",
        "target_kind",
        "raw_target_summary",
        "email_redacted",
    }
    return {key: value for key, value in metadata.items() if key in allowed}
