from __future__ import annotations



def test_canon_doc_split0_warc_subfamily_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.document_family as document_family
    import repomap_kg.canonicalization.document_warc_family as document_warc_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        document_family._canonicalize_warc_definition_observation
        is document_warc_family._canonicalize_warc_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_warc_reference_observation")
        is document_warc_family._canonicalize_warc_reference_observation
    )
    assert (
        main._canonicalize_warc_definition_observation
        is document_warc_family._canonicalize_warc_definition_observation
    )
    assert (
        document_family._warc_node_metadata
        is document_warc_family._warc_node_metadata
    )


def test_canon_doc_split1_xml_subfamily_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.document_family as document_family
    import repomap_kg.canonicalization.document_xml_family as document_xml_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        document_family._canonicalize_xml_definition_observation
        is document_xml_family._canonicalize_xml_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_xml_reference_observation")
        is document_xml_family._canonicalize_xml_reference_observation
    )
    assert (
        main._canonicalize_xml_definition_observation
        is document_xml_family._canonicalize_xml_definition_observation
    )
    assert (
        document_family._xml_definition_target
        is document_xml_family._xml_definition_target
    )


def test_canon_doc_split2_html_subfamily_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.document_family as document_family
    import repomap_kg.canonicalization.document_html_family as document_html_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        document_family._canonicalize_html_definition_observation
        is document_html_family._canonicalize_html_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_html_reference_observation")
        is document_html_family._canonicalize_html_reference_observation
    )
    assert (
        main._canonicalize_html_definition_observation
        is document_html_family._canonicalize_html_definition_observation
    )
    assert (
        document_family._html_reference_target_key
        is document_html_family._html_reference_target_key
    )


def test_canon_doc_split3_css_subfamily_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.document_family as document_family
    import repomap_kg.canonicalization.edge_helpers as edge_helpers
    import repomap_kg.canonicalization.document_css_family as document_css_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        document_family._canonicalize_css_definition_observation
        is document_css_family._canonicalize_css_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_css_selector_match_observation")
        is document_css_family._canonicalize_css_selector_match_observation
    )
    assert (
        main._canonicalize_css_reference_observation
        is document_css_family._canonicalize_css_reference_observation
    )
    assert document_family._upsert_css_edge is document_css_family._upsert_css_edge
    assert document_css_family._upsert_css_edge is edge_helpers._upsert_css_edge
    assert (
        document_family._css_selector_match_target_key
        is document_css_family._css_selector_match_target_key
    )


def test_canon_doc_split4_markdown_subfamily_module_imports() -> None:
    import repomap_kg.canonicalization as canonicalization
    import repomap_kg.canonicalization.main as main
    import repomap_kg.canonicalization.document_family as document_family
    import repomap_kg.canonicalization.document_markdown_family as document_markdown_family
    assert (
        canonicalization.canonicalize_observations
        is main.canonicalize_observations
    )
    assert (
        document_family._canonicalize_markdown_definition_observation
        is document_markdown_family._canonicalize_markdown_definition_observation
    )
    assert (
        getattr(canonicalization, "_canonicalize_markdown_link_observation")
        is document_markdown_family._canonicalize_markdown_link_observation
    )
    assert (
        main._canonicalize_markdown_page_evidence_observation
        is document_markdown_family._canonicalize_markdown_page_evidence_observation
    )
    assert (
        document_family._markdown_definition_target
        is document_markdown_family._markdown_definition_target
    )
    assert (
        document_family._markdown_link_target_key
        is document_markdown_family._markdown_link_target_key
    )
    assert (
        document_family._upsert_markdown_edge
        is document_markdown_family._upsert_markdown_edge
    )
