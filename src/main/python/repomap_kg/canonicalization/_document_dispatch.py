"""Private config, document, web, and feed canonicalization dispatch."""

from __future__ import annotations

from repomap_kg.canonicalization.config_family import (
    _canonicalize_config_definition_observation,
    _canonicalize_config_reference_observation,
)
from repomap_kg.canonicalization.dispatch import CanonicalizationState
from repomap_kg.canonicalization.dispatch_helpers import (
    JS5_FRAMEWORK_RAW_OBSERVATION_KINDS,
    TFJSON_PROFILE_RAW_OBSERVATION_KINDS,
)
from repomap_kg.canonicalization.document_family import (
    _canonicalize_css_definition_observation,
    _canonicalize_css_reference_observation,
    _canonicalize_css_selector_match_observation,
    _canonicalize_document_definition_observation,
    _canonicalize_document_reference_observation,
    _canonicalize_html_definition_observation,
    _canonicalize_html_reference_observation,
    _canonicalize_markdown_definition_observation,
    _canonicalize_markdown_link_observation,
    _canonicalize_markdown_page_evidence_observation,
    _canonicalize_warc_definition_observation,
    _canonicalize_warc_reference_observation,
    _canonicalize_xml_definition_observation,
    _canonicalize_xml_reference_observation,
)
from repomap_kg.canonicalization.evidence_helpers import _evidence_from_observation
from repomap_kg.canonicalization.feed_family import (
    _canonicalize_feed_definition_observation,
    _canonicalize_feed_reference_observation,
)
from repomap_kg.observations.raw import RawObservation


def _try_canonicalize_document_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    state: CanonicalizationState,
) -> bool:
    nodes = state.nodes
    edges = state.edges
    evidence = state.evidence
    node_evidence_links = state.node_evidence_links
    edge_evidence_links = state.edge_evidence_links
    diagnostics = state.diagnostics

    if observation.kind in (
        "markdown.document",
        "markdown.heading",
        "markdown.adr_metadata",
        "markdown.skill_metadata",
    ):
        _canonicalize_markdown_definition_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "markdown.link":
        _canonicalize_markdown_link_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in ("markdown.frontmatter", "markdown.code_fence"):
        _canonicalize_markdown_page_evidence_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in ("config.document", "config.path"):
        _canonicalize_config_definition_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "config.reference":
        _canonicalize_config_reference_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in ("config.jsonl_record", "config.parse_error"):
        evidence.append(_evidence_from_observation(observation, ordinal))
        return True
    if observation.kind in TFJSON_PROFILE_RAW_OBSERVATION_KINDS:
        evidence.append(_evidence_from_observation(observation, ordinal))
        return True
    if observation.kind in JS5_FRAMEWORK_RAW_OBSERVATION_KINDS:
        evidence.append(_evidence_from_observation(observation, ordinal))
        return True
    if observation.kind in ("html.document", "html.element", "html.heading"):
        _canonicalize_html_definition_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in ("html.link", "html.asset", "html.form"):
        _canonicalize_html_reference_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "html.parse_error":
        evidence.append(_evidence_from_observation(observation, ordinal))
        return True
    if observation.kind in ("xml.document", "xml.element", "xml.attribute"):
        _canonicalize_xml_definition_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "xml.reference":
        _canonicalize_xml_reference_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "xml.parse_error":
        evidence.append(_evidence_from_observation(observation, ordinal))
        return True
    if observation.kind in (
        "css.document",
        "css.rule",
        "css.selector",
        "css.custom_property",
    ):
        _canonicalize_css_definition_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "css.reference":
        _canonicalize_css_reference_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "css.selector_match":
        _canonicalize_css_selector_match_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in ("css.declaration", "css.parse_error"):
        evidence.append(_evidence_from_observation(observation, ordinal))
        return True
    if observation.kind in (
        "feed.document",
        "feed.channel",
        "feed.item",
        "feed.author",
        "feed.category",
    ):
        _canonicalize_feed_definition_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in ("feed.link", "feed.enclosure"):
        _canonicalize_feed_reference_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in ("feed.content", "feed.parse_error"):
        evidence.append(_evidence_from_observation(observation, ordinal))
        return True
    if observation.kind in ("warc.document", "warc.record"):
        _canonicalize_warc_definition_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "warc.reference":
        _canonicalize_warc_reference_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind in (
        "warc.header",
        "warc.payload",
        "warc.parse_error",
    ):
        evidence.append(_evidence_from_observation(observation, ordinal))
        return True
    if observation.kind in (
        "document.text_document",
        "document.text_section",
        "document.table_document",
        "document.table_column",
        "document.latex_document",
        "document.latex_section",
        "document.latex_command",
        "document.odf_document",
        "document.odf_text",
        "document.odf_table",
        "document.odf_sheet",
        "document.odf_column",
    ):
        _canonicalize_document_definition_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "document.reference":
        _canonicalize_document_reference_observation(
            observation=observation,
            ordinal=ordinal,
            nodes=nodes,
            edges=edges,
            evidence=evidence,
            node_evidence_links=node_evidence_links,
            edge_evidence_links=edge_evidence_links,
            diagnostics=diagnostics,
        )
        return True
    if observation.kind == "document.parse_error":
        evidence.append(_evidence_from_observation(observation, ordinal))
        return True
    return False
