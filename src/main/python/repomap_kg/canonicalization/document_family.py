"""Document and web-content canonicalization family handlers."""

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
    document_column_key,
    document_file_key,
    document_latex_command_key,
    document_section_key,
    document_sheet_key,
    document_table_key,
    file_key,
    parse_key,
    unknown_key,
)
from repomap_kg.observations.raw import RawObservation

from repomap_kg.canonicalization.document_markdown_family import (
    _canonicalize_markdown_definition_observation,
    _canonicalize_markdown_link_observation,
    _canonicalize_markdown_page_evidence_observation,
    _markdown_adr_node_metadata,
    _markdown_define_edge_metadata,
    _markdown_definition_target,
    _markdown_document_node_metadata,
    _markdown_heading_node_metadata,
    _markdown_link_edge_metadata,
    _markdown_link_source_key,
    _markdown_link_target_key,
    _markdown_page_evidence_metadata,
    _markdown_skill_node_metadata,
    _upsert_markdown_edge,
)

def _canonicalize_document_definition_observation(
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
        definition = _document_definition(observation, ordinal, diagnostics)
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
    for node_key, display_name, metadata, link_kind in definition["nodes"]:
        _upsert_node(
            nodes,
            canonical_key=node_key,
            kind=_node_kind_from_key(node_key),
            display_name=display_name,
            metadata=metadata,
            confidence=observation.confidence,
        )
        node_evidence_links.append(
            CanonicalNodeEvidenceLink(
                canonical_key=node_key,
                evidence_key=evidence_record.evidence_key,
                link_kind=link_kind,
            )
        )
    for source_key, target_key, edge_metadata in definition["edges"]:
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

def _canonicalize_document_reference_observation(
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
        source_key = _document_reference_source_key(observation)
        target_key = _document_reference_target_key(observation, ordinal, diagnostics)
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
        metadata=_document_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

from repomap_kg.canonicalization.document_warc_family import (
    _canonicalize_warc_definition_observation,
    _canonicalize_warc_reference_observation,
    _warc_define_edge_metadata,
    _warc_definition_source_key,
    _warc_definition_target_key,
    _warc_node_metadata,
    _warc_reference_edge_metadata,
    _warc_reference_source_key,
    _warc_reference_target_key,
)

from repomap_kg.canonicalization.document_html_family import (
    _canonicalize_html_definition_observation,
    _canonicalize_html_reference_observation,
    _html_anchor_node_metadata,
    _html_define_edge_metadata,
    _html_definition_target,
    _html_document_node_metadata,
    _html_element_node_metadata,
    _html_heading_element_node_metadata,
    _html_heading_target_key,
    _html_reference_edge_metadata,
    _html_reference_source_key,
    _html_reference_source_node_metadata,
    _html_reference_target_key,
    _upsert_html_edge,
)

from repomap_kg.canonicalization.document_xml_family import (
    _canonicalize_xml_definition_observation,
    _canonicalize_xml_reference_observation,
    _upsert_xml_edge,
    _xml_attribute_node_metadata,
    _xml_define_edge_metadata,
    _xml_definition_target,
    _xml_document_node_metadata,
    _xml_element_node_metadata,
    _xml_reference_edge_metadata,
    _xml_reference_source_key,
    _xml_reference_source_node_metadata,
    _xml_reference_target_key,
)

from repomap_kg.canonicalization.document_css_family import (
    _canonicalize_css_definition_observation,
    _canonicalize_css_reference_observation,
    _canonicalize_css_selector_match_observation,
    _css_custom_property_node_metadata,
    _css_define_edge_metadata,
    _css_definition_parts,
    _css_document_node_metadata,
    _css_reference_edge_metadata,
    _css_reference_source_key,
    _css_reference_source_node_metadata,
    _css_reference_target_key,
    _css_rule_node_metadata,
    _css_selector_match_edge_metadata,
    _css_selector_match_source_key,
    _css_selector_match_source_node_metadata,
    _css_selector_match_target_key,
    _css_selector_match_target_node_metadata,
    _css_selector_node_metadata,
    _css_selector_source_key,
    _upsert_css_edge,
)

def _document_definition(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> dict[str, Any]:
    file_node_key = file_key(observation.path)
    document_key = _document_file_node_key(observation)
    nodes: list[tuple[str, str, dict[str, Any], str]] = [
        (file_node_key, observation.path, {}, "inferred_from_edge"),
        (
            document_key,
            observation.path,
            _document_file_node_metadata(observation.metadata),
            "observed",
        ),
    ]
    edges: list[tuple[str, str, dict[str, Any]]] = [
        (
            file_node_key,
            document_key,
            _document_define_edge_metadata(observation.metadata),
        )
    ]

    if observation.kind in (
        "document.text_document",
        "document.latex_document",
        "document.odf_document",
    ):
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        return {"nodes": nodes, "edges": edges}

    if observation.kind in (
        "document.text_section",
        "document.latex_section",
        "document.odf_text",
    ):
        pointer = _metadata_text(observation.metadata, "pointer") or observation.name
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError(f"{observation.kind} observation requires pointer")
        section_key = document_section_key(observation.path, pointer)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        nodes.append(
            (
                section_key,
                _metadata_text(observation.metadata, "heading_summary") or pointer,
                _document_section_node_metadata(observation.metadata),
                "observed",
            )
        )
        edges.append(
            (
                document_key,
                section_key,
                _document_define_edge_metadata(observation.metadata),
            )
        )
        return {"nodes": nodes, "edges": edges}

    if observation.kind in ("document.table_document", "document.odf_table"):
        pointer = _metadata_text(observation.metadata, "pointer") or observation.name
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError(f"{observation.kind} observation requires pointer")
        table_key = document_table_key(observation.path, pointer)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        nodes.append(
            (
                table_key,
                _metadata_text(observation.metadata, "display_name") or pointer,
                _document_table_node_metadata(observation.metadata),
                "observed",
            )
        )
        edges.append(
            (
                document_key,
                table_key,
                _document_define_edge_metadata(observation.metadata),
            )
        )
        return {"nodes": nodes, "edges": edges}

    if observation.kind == "document.odf_sheet":
        pointer = _metadata_text(observation.metadata, "pointer") or observation.name
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError("document.odf_sheet observation requires pointer")
        sheet_key = document_sheet_key(observation.path, pointer)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        nodes.append(
            (
                sheet_key,
                _metadata_text(observation.metadata, "display_name") or pointer,
                _document_sheet_node_metadata(observation.metadata),
                "observed",
            )
        )
        edges.append(
            (
                document_key,
                sheet_key,
                _document_define_edge_metadata(observation.metadata),
            )
        )
        return {"nodes": nodes, "edges": edges}

    if observation.kind in ("document.table_column", "document.odf_column"):
        pointer = _metadata_text(observation.metadata, "pointer") or observation.name
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError(f"{observation.kind} observation requires pointer")
        parent_key = _metadata_text(observation.metadata, "parent_key")
        parent_key_source = "parent_key"
        if parent_key is None:
            parent_key = _metadata_text(observation.metadata, "table_key")
            parent_key_source = "table_key"
        if parent_key is None:
            parent_key = document_table_key(observation.path, "/table")
        parsed_parent = parse_key(parent_key)
        if parsed_parent.namespace not in ("document.table", "document.sheet"):
            if parent_key_source == "table_key":
                raise GraphKeyError(
                    "document.table_column table_key must be document.table"
                )
            raise GraphKeyError(
                f"{observation.kind} parent_key must be document.table or document.sheet"
            )
        column_key = document_column_key(observation.path, pointer)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        nodes.extend(
            (
                (parent_key, _display_name_from_key(parent_key), {}, "inferred_from_edge"),
                (
                    column_key,
                    _metadata_text(observation.metadata, "column_name_summary") or pointer,
                    _document_column_node_metadata(observation.metadata),
                    "observed",
                ),
            )
        )
        edges.append(
            (
                parent_key,
                column_key,
                _document_define_edge_metadata(observation.metadata),
            )
        )
        return {"nodes": nodes, "edges": edges}

    if observation.kind == "document.latex_command":
        pointer = _metadata_text(observation.metadata, "pointer") or observation.name
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError("document.latex_command observation requires pointer")
        command_key = document_latex_command_key(observation.path, pointer)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        nodes.append(
            (
                command_key,
                _metadata_text(observation.metadata, "command") or pointer,
                _document_latex_command_node_metadata(observation.metadata),
                "observed",
            )
        )
        edges.append(
            (
                document_key,
                command_key,
                _document_define_edge_metadata(observation.metadata),
            )
        )
        return {"nodes": nodes, "edges": edges}

    raise GraphKeyError(f"unsupported document observation kind: {observation.kind}")

def _document_file_node_key(observation: RawObservation) -> str:
    document_key = _metadata_text(observation.metadata, "document_key")
    if document_key is not None:
        parsed = parse_key(document_key)
        if parsed.namespace != "document.file":
            raise GraphKeyError("document_key must be document.file")
        return document_key
    return document_file_key(observation.path)

def _document_reference_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is None:
        return document_file_key(observation.path)
    parsed = parse_key(source_key)
    if parsed.namespace in (
        "document.file",
        "document.section",
        "document.table",
        "document.sheet",
        "document.column",
        "document.latex_command",
    ):
        return source_key
    raise GraphKeyError("document.reference source_key must be a document key")

def _document_reference_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    if observation.target is None:
        placeholder_key = unknown_key("document.reference", "missing-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="document.reference observation requires target",
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
        placeholder_key = unknown_key("document.reference", "malformed-target")
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

def _document_file_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "byte_count",
        "line_count",
        "paragraph_count",
        "section_count",
        "reference_count",
        "summary_redacted",
        "compiled",
        "document_kind",
        "template",
        "package_byte_count",
        "package_part_count",
        "parsed_part_count",
        "skipped_part_count",
        "total_uncompressed_bytes",
        "paragraph_count",
        "heading_count",
        "table_count",
        "sheet_count",
        "row_count_summary",
        "column_count_summary",
        "formulas_evaluated",
        "formula_count",
        "macro_script_ignored",
        "style_count",
        "title_summary",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _document_section_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "pointer",
        "heading_level",
        "heading_summary",
        "command",
        "redacted",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _document_table_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "pointer",
        "row_count",
        "column_count",
        "header_present",
        "delimiter",
        "display_name",
        "formula_count",
        "formulas_evaluated",
        "redacted",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _document_sheet_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "pointer",
        "display_name",
        "row_count",
        "column_count",
        "header_present",
        "formula_count",
        "formulas_evaluated",
        "redacted",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _document_column_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "pointer",
        "column_index",
        "column_name_summary",
        "type_summary",
        "non_empty_count",
        "redacted",
        "redaction_reason",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _document_latex_command_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "pointer",
        "command",
        "argument_summary",
        "redacted",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary

def _document_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("format", "formats"),
        ("pointer", "pointers"),
        ("command", "commands"),
        ("type_summary", "type_summaries"),
        ("document_kind", "document_kinds"),
        ("source_part", "source_parts"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    template = metadata.get("template")
    if isinstance(template, bool):
        summary["template_observed"] = template
    return summary

def _document_reference_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("format", "formats"),
        ("reference_kind", "reference_kinds"),
        ("raw_value_summary", "raw_value_summaries"),
        ("resolution_reason", "resolution_reasons"),
        ("command", "commands"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    redacted = metadata.get("redacted")
    if isinstance(redacted, bool):
        summary["redacted_observed"] = redacted
    not_fetched = metadata.get("not_fetched")
    if isinstance(not_fetched, bool):
        summary["not_fetched"] = not_fetched
    return summary
