"""CSS caller records preserve provenance or refuse malformed row contracts."""
from dataclasses import replace

import pytest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.extractors.documents.css import extract_css_file_observations
from repomap_kg.extractors.documents.css_html_matching import extract_css_selector_match_observations
from repomap_kg.extractors.documents.html import extract_html_file_observations
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.staged_rows import build_staged_rows


@pytest.fixture
def extracted_css():
    html = extract_html_file_observations(
        "index.html", '<html><head><link rel="stylesheet" href="style.css"></head>'
        '<body><div class="card">Card</div><span class="other">Other</span></body></html>',
    )
    css = extract_css_file_observations(
        "style.css", ".card { --accent: blue; color: var(--accent); background: url(icon.svg); }",
    )
    matches = extract_css_selector_match_observations((*html, *css))
    assert len(matches) == 1
    return (*html, *css, *matches)


@pytest.mark.parametrize("kind,changes,metadata,message", [
    ("css.rule", {"name": None}, {"rule_pointer": None}, "requires rule pointer"),
    ("css.selector", {"name": None}, {"selector_pointer": None}, "requires selector pointer"),
    ("css.selector", {}, {"source_rule_key": "file:style.css"}, "source_rule_key must be css.rule"),
    ("css.selector", {}, {"source_rule_key": None, "rule_pointer": None}, "requires rule pointer"),
    ("css.custom_property", {"name": None}, {"property_name": None}, "requires property name"),
    ("css.reference", {}, {"source_key": "file:style.css"}, "source_key must be css.rule"),
    ("css.reference", {"name": None}, {"source_key": None, "rule_pointer": None}, "requires rule pointer"),
    ("css.selector_match", {"name": None}, {"selector_key": None}, "requires selector_key"),
    ("css.selector_match", {}, {"selector_key": "file:style.css"}, "selector_key must be css.selector"),
    ("css.selector_match", {"target": None}, {"html_key": None}, "requires html target"),
    ("css.selector_match", {"target": "file:index.html"}, {}, "target must be html.element or html.anchor"),
], ids=["rule-pointer", "selector-pointer", "selector-owner-kind", "selector-owner-missing",
        "property-name", "reference-owner-kind", "reference-owner-missing", "match-source-missing",
        "match-source-kind", "match-target-missing", "match-target-kind"])
def test_extracted_record_corruption_is_rejected_before_staging(extracted_css, kind, changes, metadata, message):
    selected = next(record for record in extracted_css if record.kind == kind)
    bad = replace(selected, **changes, metadata={**selected.metadata, **metadata})
    result = canonicalize_observations((bad,))
    assert not result.ok
    assert not result.graph.edges and not result.graph.evidence
    assert any(message in diagnostic.message and diagnostic.raw_source_id == selected.source_id
               for diagnostic in result.diagnostics)
    with pytest.raises(StorageSchemaError, match=message):
        build_staged_rows((bad,), repository_name="css-contract", stage_id="fixture-stage")
    # The source-derived control binds the exact edge and its evidence into rows.
    good = canonicalize_observations((selected,))
    assert good.ok and len(good.graph.edges) == 1
    rows = build_staged_rows((selected,), repository_name="css-contract", stage_id="fixture-stage")
    try:
        edge = good.graph.edges[0]
        stored = tuple(rows.family_rows["canonical_edges"])
        assert len(stored) == 1
        assert (stored[0]["source_canonical_key"], stored[0]["target_canonical_key"]) == (edge.source_key, edge.target_key)
        assert rows.row_counts["canonical_edge_evidence"] == 1
        assert rows.row_counts["canonical_node_evidence"] == 2
    finally:
        rows.close()


@pytest.mark.parametrize("target,reason", [(None, "missing-target"), ("bad target", "malformed-target")])
def test_css_reference_warning_retains_unknown_target_and_raw_evidence(extracted_css, target, reason):
    original = next(record for record in extracted_css if record.kind == "css.reference")
    record = replace(original, target=target)
    result = canonicalize_observations((record,))
    assert result.ok and len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert diagnostic.severity == "warning" and diagnostic.placeholder_key is not None
    assert reason in diagnostic.placeholder_key
    edge = result.graph.edges[0]
    assert edge.target_key == diagnostic.placeholder_key
    rows = build_staged_rows((record,), repository_name="css-contract", stage_id="fixture-stage")
    try:
        raw = tuple(rows.family_rows["raw_observations"])
        assert raw[0]["payload_json"] == record.to_dict()
        assert tuple(rows.family_rows["canonical_edges"])[0]["target_canonical_key"] == edge.target_key
        assert rows.row_counts["canonical_edge_evidence"] == 1
    finally:
        rows.close()
