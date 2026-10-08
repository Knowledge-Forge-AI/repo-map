"""Document, language, and shell uncertainty survives canonical row composition."""

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_test_support.composition_extraction_fixtures import create_composition_graph_config


def _capture_rows(project):
    candidate = capture_multi_source_candidate(create_composition_graph_config(project))
    result = canonicalize_observations(candidate.observations, repository_scope="slice20")
    assert result.ok
    rows = build_staged_rows(candidate.observations, repository_name="slice20", stage_id="static")
    try:
        raw = list(rows.family_rows["raw_observations"])
        assert rows.row_counts["raw_observations"] == len(candidate.observations)
        assert rows.row_counts["canonical_edges"] == len(result.graph.edges)
        assert {row["source_id"] for row in raw} == {item.source_id for item in candidate.observations}
    finally:
        rows.close()
    return candidate, result


def test_markdown_unlabelled_fence_and_missing_target_recover(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "README.md").write_text('```\n[not a link](hidden.md)\n```\n\n[Guide](guide.md)\n')
    missing, missing_graph = _capture_rows(project)
    fences = [item for item in missing.observations if item.kind == "markdown.code_fence"]
    assert len(fences) == 1
    assert fences[0].metadata["closed"] is True
    assert "language" not in fences[0].metadata and "section_anchor" not in fences[0].metadata
    links = [item for item in missing.observations if item.kind == "markdown.link"]
    assert len(links) == 1
    assert "source_anchor" not in links[0].metadata
    assert "source_key" not in links[0].metadata
    assert links[0].metadata["resolution_reason"] == "missing-markdown-link-target"
    (project / "guide.md").write_text("# Guide\n")
    recovered, recovered_graph = _capture_rows(project)
    links = [item for item in recovered.observations if item.kind == "markdown.link"]
    assert len(links) == 1 and links[0].target == "doc.page:file%3Aprimary%2Fguide.md"
    assert recovered.source_generation != missing.source_generation
    assert any(edge.kind == "links_to" and edge.target_key == links[0].target
               for edge in recovered_graph.graph.edges)
    assert not any(edge.kind == "links_to" and edge.target_key == links[0].target
                   for edge in missing_graph.graph.edges)


def test_fastapi_unknown_dependency_is_not_invented_or_executed(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    module = project / "app.py"
    module.write_text('''raise RuntimeError("static source must not execute")
from fastapi import FastAPI, Depends
app = FastAPI()
@app.get("/items")
async def items(value=Depends()):
    return Depends()
''')
    unknown, unknown_graph = _capture_rows(project)
    dependencies = [item for item in unknown.observations if item.kind == "python.fastapi_dependency"]
    assert len(dependencies) == 2
    assert {item.name for item in dependencies} == {"unknown"}
    assert {item.metadata["dependency_kind"] for item in dependencies} == {"depends_default", "depends_call"}
    module.write_text(module.read_text().replace("Depends()", "Depends(provider)"))
    resolved, resolved_graph = _capture_rows(project)
    dependencies = [item for item in resolved.observations if item.kind == "python.fastapi_dependency"]
    assert len(dependencies) == 2 and {item.name for item in dependencies} == {"provider"}
    assert resolved.source_generation != unknown.source_generation
    # Framework profile records are raw-only; never invent canonical support.
    for result in (unknown_graph, resolved_graph):
        assert not any(item.raw_kind == "python.fastapi_dependency" for item in result.graph.evidence)
        assert any(item.category == "unsupported_raw_observation_kind" for item in result.diagnostics)


def test_dynamic_shell_wrapper_does_not_invent_a_file_write(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    script = project / "prepare.sh"
    script.write_text('#!/bin/bash\nenv MODE=fixture "$ACTION" marker\nsudo env "$ACTION" marker\n')
    dynamic, dynamic_graph = _capture_rows(project)
    assert not any(item.kind == "shell.host_mutation" for item in dynamic.observations)
    script.write_text('#!/bin/bash\nenv MODE=fixture mkdir marker\nsudo env mkdir marker\n')
    literal, literal_graph = _capture_rows(project)
    mutations = [item for item in literal.observations if item.kind == "shell.host_mutation"]
    assert len(mutations) == 2
    assert not (project / "marker").exists()
    assert literal.source_generation != dynamic.source_generation
    assert not any(edge.kind == "mutates_host" for edge in dynamic_graph.graph.edges)
    effects = [edge for edge in literal_graph.graph.edges if edge.kind == "mutates_host"]
    assert effects and all(edge.source_key == "file:primary/prepare.sh" for edge in effects)
    supported = {link.edge_key for link in literal_graph.graph.edge_evidence_links}
    assert all(edge.edge_key in supported for edge in effects)
