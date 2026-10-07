"""Filesystem capture, document routing, and sealed multi-source authority contracts."""

from dataclasses import replace
from pathlib import Path

import pytest

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.graph.keys import (
    config_document_key, config_path_key, css_custom_property_key, css_document_key,
    doc_page_key, doc_section_key, file_key, html_anchor_key, html_document_key,
    xml_document_key,
)
from repomap_kg.graph.multi_source import (
    SourceKind, graph_source_binding_id, source_selection_policy_id,
)
from repomap_kg.graph.multi_source_pipeline import (
    MultiSourceCaptureError, SealedSourceBinding, capture_multi_source_candidate,
    capture_sealed_multi_source_candidate,
)
from repomap_kg.graph import multi_source_pipeline as pipeline
from repomap_kg.ops.config_binding_records import OpsGraphSourceBindingConfig
from repomap_kg.ops.config_records import OpsGraphConfig


def _make_binding(
    root: Path, alias: str, *, role: str = "source", input_name: str | None = None
) -> OpsGraphSourceBindingConfig:
    return OpsGraphSourceBindingConfig(
        schema_version=1, binding_id=graph_source_binding_id("fixture-graph", alias),
        source_definition_id=f"src1:{alias}", alias=alias, revision=1,
        source_kind=SourceKind.FOLDER, root_path=str(root), root_path_expanded=str(root),
        repository_name=f"repo-{alias}", logical_root=".", privacy="public-dev",
        evidence_retention="metadata-only", extractor_profile="default",
        include_paths=(), exclude_paths=(), selection_policy_id=source_selection_policy_id((), ()),
        resolution_policy="allow-declared", enabled=True, role=role, input_name=input_name,
    )



def _make_graph(*bindings: OpsGraphSourceBindingConfig) -> OpsGraphConfig:
    return OpsGraphConfig(
        id="fixture-graph", name="Fixture", root_path="", root_path_expanded="",
        repository_name="repo-fixture", privacy="public-dev", enabled=True,
        mcp_visible=True, extractor_profile="", refresh_policy="manual",
        source_bindings=tuple(bindings), explicit_source_bindings=True,
    )



def test_multi_source_candidate_rebases_web_and_doc_families_into_canonical_graph(
    tmp_path: Path,
) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "styles.css").write_text(
        ":root { --theme-color: #003366; }\nh1.title { color: var(--theme-color); }\n",
        encoding="utf-8",
    )
    (web / "index.html").write_text(
        '<!DOCTYPE html><html><body><h1 id="intro">Title</h1><p><a href="#intro">Link</a></p></body></html>',
        encoding="utf-8",
    )
    (web / "manifest.xml").write_text(
        '<package><component id="c1" active="true">main</component></package>', encoding="utf-8"
    )
    (web / "settings.json").write_text('{"service": {"port": 8080, "name": "web-svc"}}', encoding="utf-8")
    (web / "guide.md").write_text("# Overview\n\nSection details.\n", encoding="utf-8")

    svc = tmp_path / "svc"
    svc.mkdir()
    (svc / "flake.nix").write_text("{ ... }: { nixosModules.default = {}; }\n", encoding="utf-8")

    bundle = capture_multi_source_candidate(_make_graph(_make_binding(web, "web"), _make_binding(svc, "svc")))
    assert bundle.source_generation.startswith("sg1:") and len(bundle.source_generation) == 68
    assert bundle.config_generation.startswith("cg1:") and len(bundle.config_generation) == 68
    assert bundle.privacy == "public-dev"

    targets = {obs.target for obs in bundle.observations if obs.target}
    assert css_document_key("file:web/styles.css") in targets
    assert css_custom_property_key("file:web/styles.css", "--theme-color") in targets
    assert html_document_key("file:web/index.html") in targets
    assert html_anchor_key("file:web/index.html", "intro") in targets
    assert xml_document_key("file:web/manifest.xml") in targets
    assert config_document_key("file:web/settings.json") in targets
    assert config_path_key("file:web/settings.json", "/service") in targets
    assert doc_page_key("file:web/guide.md") in targets
    assert doc_section_key("file:web/guide.md", "overview") in targets

    html_heading = next(obs for obs in bundle.observations if obs.target == html_anchor_key("file:web/index.html", "intro"))
    assert html_heading.metadata["source_element_key"].startswith("html.element:file%3Aweb%2Findex.html")

    doc_heading = next(obs for obs in bundle.observations if obs.target == doc_section_key("file:web/guide.md", "overview"))
    assert doc_heading.metadata["page_key"] == doc_page_key("file:web/guide.md")

    result = canonicalize_observations(bundle.observations)
    assert result.ok
    nodes_by_key = {node.canonical_key: node for node in result.graph.nodes}
    assert nodes_by_key[file_key("web/styles.css")].kind == "file"
    assert nodes_by_key[css_document_key("file:web/styles.css")].kind == "css.document"
    assert nodes_by_key[css_custom_property_key("file:web/styles.css", "--theme-color")].kind == "css.custom_property"
    assert nodes_by_key[html_document_key("file:web/index.html")].kind == "html.document"
    assert nodes_by_key[html_anchor_key("file:web/index.html", "intro")].kind == "html.anchor"
    assert nodes_by_key[xml_document_key("file:web/manifest.xml")].kind == "xml.document"
    assert nodes_by_key[config_document_key("file:web/settings.json")].kind == "config.document"
    assert nodes_by_key[doc_page_key("file:web/guide.md")].kind == "doc.page"
    assert nodes_by_key[doc_section_key("file:web/guide.md", "overview")].kind == "doc.section"

    edges = {(e.source_key, e.target_key, e.kind) for e in result.graph.edges}
    assert (file_key("web/styles.css"), css_document_key("file:web/styles.css"), "defines") in edges
    assert (file_key("web/index.html"), html_document_key("file:web/index.html"), "defines") in edges
    assert (file_key("web/manifest.xml"), xml_document_key("file:web/manifest.xml"), "defines") in edges
    assert (file_key("web/settings.json"), config_document_key("file:web/settings.json"), "defines") in edges
    assert (file_key("web/guide.md"), doc_page_key("file:web/guide.md"), "defines") in edges
    assert (file_key("web/guide.md"), doc_section_key("file:web/guide.md", "overview"), "defines") in edges
    assert len(result.graph.evidence) >= len(bundle.observations)

    # Every graph observation retains its exact source and candidate authority.
    snapshots = {s.binding.alias: s for s in bundle.candidate.snapshots}
    for observation in bundle.observations:
        alias = observation.metadata["binding_alias"]
        snapshot = snapshots[alias]
        assert observation.metadata["binding_id"] == snapshot.binding.binding_id
        assert observation.metadata["snapshot_id"] == snapshot.snapshot_id
        assert observation.metadata["snapshot_manifest_digest"] == snapshot.manifest_digest
        assert observation.metadata["candidate_id"] == bundle.candidate.candidate_id
        assert observation.path == f"{alias}/{observation.metadata['source_relative_path']}"



def test_sealed_multi_source_candidate_public_refusal_boundaries(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "module.nix").write_text("{ ... }: {}\n", encoding="utf-8")

    with pytest.raises(MultiSourceCaptureError, match="sealed source inventory is invalid") as exc:
        capture_sealed_multi_source_candidate("fixture-graph", [], expected_snapshot_vector=[])
    assert exc.value.category == "contract_validation"

    b_a = SealedSourceBinding(
        graph_source_binding_id("fixture-graph", "a"), "src1:a", "a", 1, SourceKind.FOLDER, root,
        "repo-a", ".", "public-dev", "metadata-only", "default",
        source_selection_policy_id((), ()), "allow-declared", "source", None,
    )
    b_b = SealedSourceBinding(
        graph_source_binding_id("fixture-graph", "b"), "src1:b", "b", 1, SourceKind.FOLDER, root,
        "repo-b", ".", "public-dev", "metadata-only", "default",
        source_selection_policy_id((), ()), "allow-declared", "source", None,
    )
    with pytest.raises(MultiSourceCaptureError, match="sealed source inventory is invalid") as exc:
        capture_sealed_multi_source_candidate("fixture-graph", [b_a, b_b], expected_snapshot_vector=[])
    assert exc.value.category == "contract_validation"

    with pytest.raises(MultiSourceCaptureError, match="disagrees with manifest") as exc:
        capture_sealed_multi_source_candidate(
            "fixture-graph", [b_a], expected_snapshot_vector=[("wrong-binding", 1, "wrong-snap")],
        )
    assert exc.value.category == "source_changed"


# One representative per maintained provenance trust contract. Alias/type and
# role mutations duplicate binding association/configuration refusal; manifest
# digest duplicates captured-snapshot authority. All cases assert public capture.
@pytest.mark.parametrize("field,value", [
    pytest.param("binding_id", "bind1:" + "0" * 64, id="binding-association"),
    pytest.param("graph_id", "wrong-graph", id="graph-authority"),
    pytest.param("binding_revision", 999, id="binding-configuration"),
    pytest.param("snapshot_id", "snap1:" + "0" * 64, id="captured-snapshot"),
    pytest.param("source_relative_path", 123, id="typed-source-location"),
    pytest.param("path", "site/tampered.txt", id="routed-source-location"),
    pytest.param("source_id", "other-binding:file:a.txt", id="source-lineage"),
])
def test_public_capture_refuses_tampered_extractor_provenance(tmp_path, monkeypatch, field, value):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.txt").write_text("fixture content", encoding="utf-8")
    graph = _make_graph(_make_binding(root, "site"))
    original = pipeline._namespaced_observation

    def tamper(observation, source):
        routed = original(observation, source)
        if field in {"path", "source_id"}:
            return replace(routed, **{field: value})
        return replace(routed, metadata={**routed.metadata, field: value})

    # Alter one extractor result; keep capture, inventory and validation real.
    monkeypatch.setattr(pipeline, "_namespaced_observation", tamper)
    with pytest.raises(MultiSourceCaptureError, match="provenance is invalid") as exc:
        capture_multi_source_candidate(graph)
    assert exc.value.category == "source_capture"
    assert (root / "a.txt").read_text() == "fixture content"
