"""Integration wave for multi-source Languages and Documents canonical contracts.

Exercises:
1. Polyglot extraction and canonicalization across Python, JavaScript, Go,
   HTML5, CSS, Markdown, YAML, and XML.
2. Cross-layer document linking: CSS selector matching against HTML elements,
   Markdown anchor navigation to local documents, POM and Spring XML structures.
3. Boundary error diagnostics and clean recovery following repair.
4. Multi-source isolation, exclusion policies, and sealed artifact verification.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.graph.keys import ruby_class_key, ruby_method_key, ruby_singleton_method_key
from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_test_support.run25_wave2_corpus import (
    create_run25_wave2_graph_config,
    inject_malformed_plist,
    inject_malformed_yaml,
    populate_run25_language_document_project,
    restore_file_content,
    seal_and_verify_run25_artifacts,
)
from repomap_test_support.test_scratch import select_scratch_root


class Run25LanguageDocumentWaveIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(
            tempfile.mkdtemp(dir=select_scratch_root(), prefix="repomap-int-lang-doc-")
        ).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_nested_language_ownership_survives_multisource_capture_and_replay(self) -> None:
        dirs = populate_run25_language_document_project(self.tmpdir / "proj")
        (dirs["primary"] / "release.rb").write_text(
            "module Release\n  class Runner\n    VALUE = 1\n"
            "    def run\n      VALUE\n    end\n"
            "    def self.build\n      new\n    end\n  end\nend\n",
            encoding="utf-8",
        )
        (dirs["secondary"] / "widget.jsx").write_text(
            'import React, {useState} from "react";\n'
            "export class Runner {\n  run() { return 1; }\n}\n"
            "export function Widget() {\n  const [value] = useState(0);\n"
            "  return <section>{value}</section>;\n}\n",
            encoding="utf-8",
        )
        (dirs["primary"] / "app/model.py").write_text(
            "class Job:\n    def execute(self):\n        return 1\n",
            encoding="utf-8",
        )
        graph = create_run25_wave2_graph_config(dirs["primary"], dirs["secondary"])
        captured = capture_multi_source_candidate(graph)
        canonical = canonicalize_observations(
            captured.observations, repository_scope="repomap-wave2"
        )
        self.assertTrue(canonical.ok)
        kinds = {observation.kind for observation in captured.observations}
        self.assertTrue({"ruby.class", "ruby.method", "ruby.singleton_method", "python.class", "python.method"} <= kinds)
        edges = {(edge.source_key, edge.kind, edge.target_key) for edge in canonical.graph.edges}
        self.assertIn((ruby_class_key("Release::Runner"), "defines", ruby_method_key("Release::Runner", "run")), edges)
        self.assertIn((ruby_class_key("Release::Runner"), "defines", ruby_singleton_method_key("Release::Runner", "build")), edges)
        paths = {observation.path for observation in captured.observations}
        self.assertTrue({"primary/release.rb", "secondary/widget.jsx", "primary/app/model.py"} <= paths)
        replay = capture_multi_source_candidate(graph)
        self.assertEqual(replay.candidate, captured.candidate)
        self.assertEqual(replay.observations, captured.observations)

    def test_polyglot_language_document_pipeline_and_artifact_sealing(self) -> None:
        dirs = populate_run25_language_document_project(self.tmpdir / "proj")
        graph_cfg = create_run25_wave2_graph_config(
            dirs["primary"], dirs["secondary"], graph_id="lang-doc-wave"
        )

        # 1. Sealed artifact roundtrip & wire contract
        store_dir = self.tmpdir / "artifacts"
        manifest, reference, candidate_id = seal_and_verify_run25_artifacts(graph_cfg, store_dir)
        self.assertTrue(manifest.manifest_id.startswith("snapmanifest1:"))
        self.assertTrue(candidate_id.startswith("cand1:"))
        self.assertEqual(len(manifest.bindings), 2)
        self.assertGreater(manifest.total_files, 10)

        # 2. Multi-source extraction
        candidate = capture_multi_source_candidate(graph_cfg)
        self.assertGreater(len(candidate.observations), 50)

        observed_kinds = {obs.kind for obs in candidate.observations}
        for expected_kind in (
            "file", "html.document", "html.element", "html.heading", "html.link",
            "css.document", "css.selector", "css.declaration", "css.selector_match",
            "markdown.document", "markdown.heading", "markdown.code_fence",
            "config.document", "xml.document", "xml.element", "xml.attribute",
            "python.module", "python.function", "python.import",
        ):
            self.assertIn(expected_kind, observed_kinds)

        # 3. Canonicalization
        can_res = canonicalize_observations(
            candidate.observations, repository_scope="repomap-wave2"
        )
        self.assertTrue(can_res.ok, [d.message for d in can_res.diagnostics if d.severity == "error"])
        self.assertGreater(len(can_res.graph.nodes), 50)
        self.assertGreater(len(can_res.graph.edges), 40)

        node_keys = {node.canonical_key for node in can_res.graph.nodes}
        self.assertIn("file:primary/app/server.py", node_keys)
        self.assertIn("python.module:app.server", node_keys)
        self.assertIn("python.function:app.server:health_check", node_keys)
        self.assertIn("file:primary/templates/index.html", node_keys)
        self.assertIn("html.document:file%3Aprimary%2Ftemplates%2Findex.html", node_keys)
        self.assertIn("file:primary/static/style.css", node_keys)
        self.assertIn("css.document:file%3Aprimary%2Fstatic%2Fstyle.css", node_keys)
        self.assertIn("file:primary/docs/overview.md", node_keys)
        self.assertIn("file:primary/pom.xml", node_keys)
        self.assertIn("file:primary/beans.xml", node_keys)
        self.assertIn("file:secondary/guide.md", node_keys)

        # 4. Deterministic edge relationships
        edge_triples = {(e.source_key, e.kind, e.target_key) for e in can_res.graph.edges}
        expected_triples = (
            ("file:primary/app/server.py", "defines", "python.module:app.server"),
            ("file:primary/app/server.py", "defines", "python.function:app.server:health_check"),
            ("file:primary/templates/index.html", "defines", "html.document:file%3Aprimary%2Ftemplates%2Findex.html"),
            ("file:primary/static/style.css", "defines", "css.document:file%3Aprimary%2Fstatic%2Fstyle.css"),
        )
        for triple in expected_triples:
            self.assertIn(triple, edge_triples)

        # 5. Evidence link attribution
        linked_edges = {link.edge_key for link in can_res.graph.edge_evidence_links}
        for edge in can_res.graph.edges:
            if (edge.source_key, edge.kind, edge.target_key) in expected_triples:
                self.assertIn(edge.edge_key, linked_edges)

    def test_html_css_selector_matching_and_markdown_anchor_navigation(self) -> None:
        dirs = populate_run25_language_document_project(self.tmpdir / "proj")
        graph_cfg = create_run25_wave2_graph_config(dirs["primary"], dirs["secondary"])
        candidate = capture_multi_source_candidate(graph_cfg)

        selector_matches = [
            obs for obs in candidate.observations if obs.kind == "css.selector_match"
        ]
        self.assertGreater(len(selector_matches), 0)

        # Verify selectors matched to HTML targets
        matched_selectors = {str(obs.metadata["selector_text"]) for obs in selector_matches}
        self.assertTrue(any("top-bar" in s or "primary-nav" in s or "item-card" in s for s in matched_selectors))

        can_res = canonicalize_observations(
            candidate.observations, repository_scope="repomap-wave2"
        )
        self.assertTrue(can_res.ok)

        # Markdown cross-references to local documents
        md_links = [
            obs for obs in candidate.observations if obs.kind == "markdown.link"
        ]
        self.assertGreater(len(md_links), 0)
        link_targets = {obs.target for obs in md_links if obs.target}
        self.assertTrue(
            any("index.html" in t or "server.py" in t or "example.com" in t for t in link_targets)
        )

        # XML POM and Spring beans element structure
        xml_elements = [
            obs for obs in candidate.observations if obs.kind == "xml.element"
        ]
        self.assertGreater(len(xml_elements), 4)
        xml_names = {obs.metadata.get("local_name") for obs in xml_elements}
        self.assertTrue({"project", "dependencies", "beans", "bean"} <= xml_names)

    def test_language_document_malformed_input_recovery(self) -> None:
        dirs = populate_run25_language_document_project(self.tmpdir / "proj")
        primary = dirs["primary"]
        yaml_file = primary / "config.yaml"

        # 1. Tamper YAML with duplicate conflicting keys
        orig_yaml = inject_malformed_yaml(yaml_file)
        graph_cfg = create_run25_wave2_graph_config(primary, dirs["secondary"])

        cand_tampered = capture_multi_source_candidate(graph_cfg)
        tampered_kinds = {obs.kind for obs in cand_tampered.observations}
        self.assertIn("config.parse_error", tampered_kinds)

        # 2. Repair YAML and verify state change and recovery
        restore_file_content(yaml_file, orig_yaml)
        cand_repaired = capture_multi_source_candidate(graph_cfg)
        self.assertNotEqual(
            cand_tampered.source_generation, cand_repaired.source_generation
        )

        repaired_kinds = {obs.kind for obs in cand_repaired.observations if obs.path == "primary/config.yaml"}
        self.assertNotIn("config.parse_error", repaired_kinds)

        # 3. Tamper Plist XML and verify recovery
        plist_file = primary / "Info.plist"
        orig_plist = inject_malformed_plist(plist_file)
        cand_plist_tampered = capture_multi_source_candidate(graph_cfg)
        plist_errs = [
            obs for obs in cand_plist_tampered.observations
            if obs.path == "primary/Info.plist" and obs.kind == "config.parse_error"
        ]
        self.assertGreater(len(plist_errs), 0)

        restore_file_content(plist_file, orig_plist)
        cand_plist_repaired = capture_multi_source_candidate(graph_cfg)
        repaired_plist_errs = [
            obs for obs in cand_plist_repaired.observations
            if obs.path == "primary/Info.plist" and obs.kind == "config.parse_error"
        ]
        self.assertEqual(len(repaired_plist_errs), 0)

    def test_language_document_exclusion_policy_and_candidate_invariance(self) -> None:
        dirs = populate_run25_language_document_project(self.tmpdir / "proj")
        primary, secondary = dirs["primary"], dirs["secondary"]

        # 1. Capture with secondary guide and theme excluded
        excludes = ("guide.md", "theme.css")
        graph_cfg = create_run25_wave2_graph_config(
            primary, secondary, exclude_secondary=excludes
        )
        candidate1 = capture_multi_source_candidate(graph_cfg)

        obs_paths = {obs.path for obs in candidate1.observations}
        self.assertNotIn("secondary/guide.md", obs_paths)
        self.assertNotIn("secondary/theme.css", obs_paths)
        self.assertIn("secondary/settings.yaml", obs_paths)

        # 2. Modify excluded file and prove candidate invariance
        (secondary / "guide.md").write_text("# Changed Content\nShould be ignored\n", encoding="utf-8")
        candidate2 = capture_multi_source_candidate(graph_cfg)

        self.assertEqual(candidate1.source_generation, candidate2.source_generation)
        self.assertEqual(candidate1.candidate.candidate_id, candidate2.candidate.candidate_id)
        self.assertEqual(candidate1.observations, candidate2.observations)


if __name__ == "__main__":
    import sys

    sys.exit(
        "Direct execution unsupported: RepoMap integration tests require container sandbox admission via pytest"
    )
