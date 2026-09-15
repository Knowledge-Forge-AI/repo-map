"""CSS document-family canonicalization handlers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
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
from repomap_kg.canonicalization.edge_helpers import _upsert_css_edge
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
    css_custom_property_key,
    css_document_key,
    css_rule_key,
    css_selector_key,
    file_key,
    parse_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation

def _canonicalize_css_definition_observation(
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
        source_key, source_display, target_key, display_name, node_metadata, edge_metadata = (
            _css_definition_parts(observation, ordinal, diagnostics)
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
        kind=_node_kind_from_key(source_key),
        display_name=source_display,
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
    edge_key = _upsert_css_edge(
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

def _canonicalize_css_reference_observation(
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
        source_key = _css_reference_source_key(observation)
        target_key = _css_reference_target_key(observation, ordinal, diagnostics)
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
        metadata=_css_reference_source_node_metadata(observation.metadata),
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
    edge_key = _upsert_css_edge(
        edges,
        source_key=source_key,
        kind="references",
        target_key=target_key,
        metadata=_css_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _canonicalize_css_selector_match_observation(
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
        source_key = _css_selector_match_source_key(observation)
        target_key = _css_selector_match_target_key(observation)
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
        metadata=_css_selector_match_source_node_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=_display_name_from_key(target_key),
        metadata=_css_selector_match_target_node_metadata(observation.metadata),
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
    edge_key = _upsert_css_edge(
        edges,
        source_key=source_key,
        kind="styles",
        target_key=target_key,
        metadata=_css_selector_match_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

def _css_definition_parts(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> tuple[str, str, str, str, dict[str, Any], dict[str, Any]]:
    if observation.kind == "css.document":
        source_key = file_key(observation.path)
        target_key = css_document_key(observation.path)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _css_document_node_metadata(observation.metadata)
        return (
            source_key,
            observation.path,
            target_key,
            observation.path,
            metadata,
            _css_define_edge_metadata(metadata),
        )
    if observation.kind == "css.rule":
        source_key = file_key(observation.path)
        pointer = _metadata_text(observation.metadata, "rule_pointer") or observation.name
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError("css.rule observation requires rule pointer metadata")
        target_key = css_rule_key(observation.path, pointer)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _css_rule_node_metadata(observation.metadata)
        display = _metadata_text(observation.metadata, "selector_text") or pointer
        return (
            source_key,
            observation.path,
            target_key,
            display,
            metadata,
            _css_define_edge_metadata(metadata),
        )
    if observation.kind == "css.selector":
        source_key = _css_selector_source_key(observation)
        pointer = _metadata_text(observation.metadata, "selector_pointer") or observation.name
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError("css.selector observation requires selector pointer metadata")
        target_key = css_selector_key(observation.path, pointer)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _css_selector_node_metadata(observation.metadata)
        display = _metadata_text(observation.metadata, "selector_text") or pointer
        return (
            source_key,
            _display_name_from_key(source_key),
            target_key,
            display,
            metadata,
            _css_define_edge_metadata(metadata),
        )
    if observation.kind == "css.custom_property":
        source_key = file_key(observation.path)
        property_name = observation.name or _metadata_text(
            observation.metadata, "property_name"
        )
        if not isinstance(property_name, str) or not property_name.strip():
            raise GraphKeyError("css.custom_property observation requires property name")
        target_key = css_custom_property_key(observation.path, property_name)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _css_custom_property_node_metadata(observation.metadata)
        return (
            source_key,
            observation.path,
            target_key,
            property_name,
            metadata,
            _css_define_edge_metadata(metadata),
        )
    raise GraphKeyError(f"unsupported CSS definition kind: {observation.kind}")

def _css_selector_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_rule_key")
    if source_key is not None:
        parsed = parse_key(source_key)
        if parsed.namespace == "css.rule":
            return source_key
        raise GraphKeyError("css.selector source_rule_key must be css.rule")
    rule_pointer = _metadata_text(observation.metadata, "rule_pointer")
    if not isinstance(rule_pointer, str) or not rule_pointer.strip():
        raise GraphKeyError("css.selector observation requires rule pointer metadata")
    return css_rule_key(observation.path, rule_pointer)

def _css_reference_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is not None:
        parsed = parse_key(source_key)
        if parsed.namespace == "css.rule":
            return source_key
        raise GraphKeyError("css.reference source_key must be css.rule")
    rule_pointer = _metadata_text(observation.metadata, "rule_pointer") or observation.name
    if not isinstance(rule_pointer, str) or not rule_pointer.strip():
        raise GraphKeyError("css.reference observation requires rule pointer metadata")
    return css_rule_key(observation.path, rule_pointer)

def _css_reference_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    if observation.target is None:
        placeholder_key = unknown_key("css.reference", "missing-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="css.reference observation requires target",
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
        placeholder_key = unknown_key("css.reference", "malformed-target")
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

def _css_selector_match_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "selector_key") or observation.name
    if not isinstance(source_key, str) or not source_key.strip():
        raise GraphKeyError("css.selector_match observation requires selector_key")
    parsed = parse_key(source_key)
    if parsed.namespace != "css.selector":
        raise GraphKeyError("css.selector_match selector_key must be css.selector")
    return source_key

def _css_selector_match_target_key(observation: RawObservation) -> str:
    target_key = observation.target or _metadata_text(observation.metadata, "html_key")
    if not isinstance(target_key, str) or not target_key.strip():
        raise GraphKeyError("css.selector_match observation requires html target")
    parsed = parse_key(target_key)
    if parsed.namespace not in ("html.element", "html.anchor"):
        raise GraphKeyError("css.selector_match target must be html.element or html.anchor")
    return target_key

def _css_document_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "parser_mode",
        "source_kind",
        "rule_count",
        "selector_count",
        "custom_property_count",
        "reference_count",
        "parse_error_count",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _css_rule_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "parser_mode",
        "rule_pointer",
        "rule_type",
        "selector_text",
        "at_rule_name",
        "at_rule_prelude_summary",
        "declaration_count",
        "custom_property_names",
        "reference_count",
        "parent_rule_pointer",
        "identity_mode",
        "font_family_summary",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _css_selector_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "parser_mode",
        "selector_pointer",
        "rule_pointer",
        "selector_text",
        "selector_index",
        "classes",
        "ids",
        "element_names",
        "attributes",
        "pseudo_classes",
        "pseudo_elements",
        "selector_kind",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _css_custom_property_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "parser_mode",
        "property_name",
        "rule_pointer",
        "definition_count",
        "value_type",
        "value_summary",
        "redacted",
        "redaction_reason",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _css_selector_match_source_node_metadata(
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("selector_text", "css_file", "scope", "not_runtime_style"):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _css_selector_match_target_node_metadata(
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("html_pointer", "html_file", "scope", "not_runtime_style"):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _css_reference_source_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("format", "parser", "parser_mode", "rule_pointer", "rule_type"):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _css_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("format", "formats"),
        ("rule_pointer", "rule_pointers"),
        ("selector_pointer", "selector_pointers"),
        ("property_name", "custom_properties"),
        ("rule_type", "rule_types"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    return summary

def _css_selector_match_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("match_kind", "match_kinds"),
        ("css_file", "css_files"),
        ("html_file", "html_files"),
        ("stylesheet_reference_source", "stylesheet_reference_sources"),
        ("scope", "scopes"),
        ("html_pointer", "html_pointers"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    matched_components = metadata.get("matched_components")
    if isinstance(matched_components, Mapping):
        summary["matched_components"] = [dict(matched_components)]
    limitations = metadata.get("limitations")
    if isinstance(limitations, Sequence) and not isinstance(limitations, (str, bytes)):
        summary["limitations"] = [
            value for value in limitations if isinstance(value, str) and value.strip()
        ]
    not_runtime_style = metadata.get("not_runtime_style")
    if isinstance(not_runtime_style, bool):
        summary["not_runtime_style_observed"] = not_runtime_style
    return summary

def _css_reference_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("reference_kind", "reference_kinds"),
        ("source_kind", "source_kinds"),
        ("raw_value_summary", "raw_value_summaries"),
        ("resolution_reason", "resolution_reasons"),
        ("rule_pointer", "rule_pointers"),
        ("property_name", "properties"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    redacted = metadata.get("redacted")
    if isinstance(redacted, bool):
        summary["redacted_observed"] = redacted
    return summary
