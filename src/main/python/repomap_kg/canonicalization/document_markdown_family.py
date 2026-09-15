"""Markdown document-family canonicalization handlers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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
    doc_adr_key,
    doc_page_key,
    doc_section_key,
    doc_skill_key,
    file_key,
    parse_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation

def _canonicalize_markdown_definition_observation(
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
            _markdown_definition_target(observation, ordinal, diagnostics)
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

    edge_key = _upsert_markdown_edge(
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

def _canonicalize_markdown_page_evidence_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        page_key = _metadata_text(observation.metadata, "page_key") or doc_page_key(
            observation.path
        )
        parsed_page_key = parse_key(page_key)
        if parsed_page_key.namespace != "doc.page":
            raise GraphKeyError("markdown page evidence requires a doc.page key")
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.page_key",
                value=observation.metadata.get("page_key"),
            )
        )
        return

    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=page_key,
        kind="doc.page",
        display_name=observation.path,
        metadata=_markdown_page_evidence_metadata(observation),
        confidence=observation.confidence,
    )
    node_evidence_links.append(
        CanonicalNodeEvidenceLink(
            canonical_key=page_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="observed",
        )
    )

def _canonicalize_markdown_link_observation(
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
        source_key = _markdown_link_source_key(observation)
        target_key = _markdown_link_target_key(observation, ordinal, diagnostics)
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
    edge_key = _upsert_markdown_edge(
        edges,
        source_key=source_key,
        kind="links_to",
        target_key=target_key,
        metadata=_markdown_link_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _markdown_definition_target(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    if observation.kind == "markdown.document":
        target_key = doc_page_key(observation.path)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        title = _metadata_text(observation.metadata, "title")
        display_name = title or observation.path
        metadata = _markdown_document_node_metadata(observation.metadata)
        return target_key, display_name, metadata, _markdown_define_edge_metadata(metadata)
    if observation.kind == "markdown.heading":
        anchor = _metadata_text(observation.metadata, "anchor")
        if anchor is None:
            raise GraphKeyError("markdown.heading observation requires anchor metadata")
        target_key = doc_section_key(observation.path, anchor)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        text = _metadata_text(observation.metadata, "text") or observation.name or anchor
        metadata = _markdown_heading_node_metadata(observation.metadata)
        return target_key, text, metadata, _markdown_define_edge_metadata(metadata)
    if observation.kind == "markdown.adr_metadata":
        number = _metadata_text(observation.metadata, "adr_number") or observation.name
        if not isinstance(number, str) or not number.strip():
            raise GraphKeyError("markdown.adr_metadata observation requires ADR number")
        target_key = doc_adr_key(number)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        title = _metadata_text(observation.metadata, "title") or number
        metadata = _markdown_adr_node_metadata(observation.metadata)
        return target_key, title, metadata, _markdown_define_edge_metadata(metadata)
    if observation.kind == "markdown.skill_metadata":
        skill_name = _metadata_text(observation.metadata, "skill_name") or observation.name
        if not isinstance(skill_name, str) or not skill_name.strip():
            raise GraphKeyError("markdown.skill_metadata observation requires skill name")
        target_key = doc_skill_key(skill_name)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _markdown_skill_node_metadata(observation.metadata)
        return target_key, skill_name, metadata, _markdown_define_edge_metadata(metadata)
    raise GraphKeyError(f"unsupported Markdown definition kind: {observation.kind}")

def _markdown_link_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is not None:
        parsed = parse_key(source_key)
        if parsed.namespace in ("doc.page", "doc.section"):
            return source_key
        raise GraphKeyError("markdown.link source_key must be doc.page or doc.section")
    source_anchor = _metadata_text(observation.metadata, "source_anchor")
    if source_anchor is not None:
        return doc_section_key(observation.path, source_anchor)
    return doc_page_key(observation.path)

def _markdown_link_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    if observation.target is None:
        placeholder_key = unknown_key("external.url", "missing-markdown-link-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="markdown.link observation requires target",
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
        placeholder_key = unknown_key("external.url", "malformed-markdown-link")
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

def _markdown_document_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "doc_path",
        "doc_role",
        "title",
        "frontmatter_present",
        "content_hash",
        "generated",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _markdown_heading_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "level",
        "text",
        "anchor",
        "base_anchor",
        "duplicate_index",
        "parent_anchor",
        "page_key",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _markdown_adr_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "adr_number",
        "title",
        "status",
        "date",
        "filename_slug",
        "heading_anchor",
        "metadata_source",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _markdown_skill_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "skill_name",
        "description",
        "skill_path",
        "frontmatter_keys",
        "metadata_source",
        "parse_status",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _markdown_page_evidence_metadata(observation: RawObservation) -> dict[str, Any]:
    if observation.kind == "markdown.frontmatter":
        summary: dict[str, Any] = {}
        keys = observation.metadata.get("keys")
        if isinstance(keys, Sequence) and not isinstance(keys, (str, bytes)):
            summary["frontmatter_keys"] = list(keys)
        parse_status = _metadata_text(observation.metadata, "parse_status")
        if parse_status is not None:
            summary["frontmatter_parse_statuses"] = [parse_status]
        return summary
    if observation.kind == "markdown.code_fence":
        summary = {}
        language = _metadata_text(observation.metadata, "language")
        if language is not None:
            summary["code_fence_languages"] = [language]
        closed = observation.metadata.get("closed")
        if isinstance(closed, bool):
            summary["code_fence_closed_observed"] = closed
        return summary
    return {}

def _markdown_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("doc_role", "doc_roles"),
        ("title", "titles"),
        ("anchor", "anchors"),
        ("adr_number", "adr_numbers"),
        ("skill_name", "skill_names"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    return summary

def _markdown_link_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("link_text", "link_texts"),
        ("raw_target", "raw_targets"),
        ("link_syntax", "syntaxes"),
        ("resolved_path", "resolved_paths"),
        ("resolved_anchor", "resolved_anchors"),
        ("resolution_reason", "resolution_reasons"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    is_image = metadata.get("is_image")
    if isinstance(is_image, bool):
        summary["image_link_observed"] = is_image
    return summary

def _upsert_markdown_edge(
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
