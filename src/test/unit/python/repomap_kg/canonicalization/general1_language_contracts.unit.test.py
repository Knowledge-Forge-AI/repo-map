from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repomap_kg.canonicalization.main import canonicalize_observations
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.canonicalization import canonicalize_observations
    from repomap_kg.observations import RawObservation

from repomap_kg.graph.keys import (
    file_key,
    js_class_key,
    js_component_key,
    js_file_key,
    js_function_key,
    js_method_key,
    js_module_key,
    js_route_key,
    js_test_case_key,
    js_test_suite_key,
    ruby_class_key,
    ruby_constant_key,
    ruby_file_key,
    ruby_method_key,
    ruby_module_key,
    ruby_route_key,
    ruby_singleton_method_key,
    ruby_test_case_key,
    ruby_test_method_key,
)


class General1LanguageContractsUnitTests(unittest.TestCase):
    """Public contract tests for Ruby and JavaScript canonicalization behaviors."""

    def _make_obs(
        self,
        kind: str,
        path: str,
        *,
        name: str | None = None,
        target: str | None = None,
        metadata: dict[str, object] | None = None,
        source_id: str | None = None,
        confidence: str = "extracted",
    ) -> RawObservation:
        return RawObservation(
            kind=kind,
            source_id=source_id or f"{path}#{kind}:{name or 'target'}",
            path=path,
            name=name,
            target=target,
            confidence=confidence,
            extractor="general1-contract-test",
            extractor_version="1.0.0",
            metadata=metadata or {},
        )

    def test_ruby_definition_malformed_and_missing_metadata_refusals(self) -> None:
        """Malformed or missing Ruby definition metadata produces error diagnostics and ok=False."""
        cases = [
            (self._make_obs("ruby.method", "lib/calc.rb", name="calculate"), "ruby.method observation requires owner metadata"),
            (self._make_obs("ruby.test_method", "test/test_app.rb", name="test_run"), "ruby.test_method observation requires test_case_key"),
            (self._make_obs("ruby.route", "app.rb", name="GET /api"), "ruby.route observation requires route_pointer metadata"),
            (self._make_obs("ruby.module", "lib/mod.rb", name="   "), "ruby.module observation requires name or target"),
            (self._make_obs("ruby.class", "lib/app.rb", name="App", metadata={"source_key": "python.module:other"}), "ruby.class source_key has unsupported namespace"),
            (self._make_obs("ruby.singleton_method", "lib/app.rb", name="build", metadata={"owner": "App", "owner_kind": "bad_kind"}), "ruby.singleton_method owner_kind has unsupported namespace"),
        ]
        for obs, expected_message in cases:
            with self.subTest(kind=obs.kind, expected=expected_message):
                res = canonicalize_observations([obs])
                self.assertFalse(res.ok)
                self.assertEqual(len(res.diagnostics), 1)
                diag = res.diagnostics[0]
                self.assertEqual(diag.severity, "error")
                self.assertEqual(diag.category, "invalid_canonical_key")
                self.assertIn(expected_message, diag.message)
                self.assertEqual(diag.raw_source_id, obs.source_id)
                self.assertEqual(len(res.graph.edges), 0)

    def test_javascript_definition_malformed_and_missing_metadata_refusals(self) -> None:
        """Malformed or missing JavaScript definition metadata produces error diagnostics and ok=False."""
        cases = [
            (self._make_obs("js.method", "src/service.js", name="execute"), "js.method observation requires class metadata"),
            (self._make_obs("js.route", "src/routes.js", name="GET /items"), "js.route observation requires route_pointer metadata"),
            (self._make_obs("js.function", "src/util.js", name=""), "js.function observation requires name or target"),
            (self._make_obs("js.class", "src/models.js", name="Item", metadata={"source_key": "ruby.class:Base"}), "js.class source_key has unsupported namespace"),
        ]
        for obs, expected_message in cases:
            with self.subTest(kind=obs.kind, expected=expected_message):
                res = canonicalize_observations([obs])
                self.assertFalse(res.ok)
                self.assertEqual(len(res.diagnostics), 1)
                diag = res.diagnostics[0]
                self.assertEqual(diag.severity, "error")
                self.assertEqual(diag.category, "invalid_canonical_key")
                self.assertIn(expected_message, diag.message)
                self.assertEqual(len(res.graph.edges), 0)

    def test_ruby_permitted_explicit_namespaces_and_fallbacks(self) -> None:
        """Ruby canonicalization supports explicit source namespaces and falls back predictably."""
        tc_key = ruby_test_case_key("test/unit_test.rb", "UnitTest")
        obs_explicit = [
            self._make_obs("ruby.file", "lib/app.rb", name="lib/app.rb", metadata={"source_key": "file:lib/app.rb"}),
            self._make_obs("ruby.module", "lib/app.rb", name="Core", metadata={"source_key": "ruby.file:file%3Alib%2Fapp.rb"}),
            self._make_obs("ruby.class", "lib/app.rb", name="Worker", metadata={"source_key": "ruby.module:Core"}),
            self._make_obs("ruby.method", "lib/app.rb", name="run", metadata={"source_key": "ruby.class:Core%3A%3AWorker", "owner": "Core::Worker"}),
            self._make_obs("ruby.singleton_method", "lib/app.rb", name="create", metadata={"source_key": "ruby.class:Core%3A%3AWorker", "owner": "Core::Worker"}),
            self._make_obs("ruby.test_method", "test/unit_test.rb", name="test_one", metadata={"source_key": tc_key, "test_case_key": tc_key}),
            self._make_obs("ruby.route", "config/routes.rb", name="GET /status", metadata={"source_key": "ruby.file:file%3Aconfig%2Froutes.rb", "route_pointer": "/routes/get:/status"}),
        ]
        res_exp = canonicalize_observations(obs_explicit)
        self.assertTrue(res_exp.ok, res_exp.diagnostics)
        edges_exp = {(e.source_key, e.kind, e.target_key) for e in res_exp.graph.edges}
        self.assertIn(("ruby.file:file%3Alib%2Fapp.rb", "defines", ruby_module_key("Core")), edges_exp)
        self.assertIn(("ruby.module:Core", "defines", ruby_class_key("Worker")), edges_exp)
        self.assertIn(("ruby.class:Core%3A%3AWorker", "defines", ruby_method_key("Core::Worker", "run")), edges_exp)
        self.assertIn(("ruby.class:Core%3A%3AWorker", "defines", ruby_singleton_method_key("Core::Worker", "create")), edges_exp)
        self.assertIn((tc_key, "defines", ruby_test_method_key(tc_key, "test_one")), edges_exp)
        self.assertIn(("ruby.file:file%3Aconfig%2Froutes.rb", "defines", ruby_route_key("config/routes.rb", "/routes/get:/status")), edges_exp)

        obs_fallbacks = [
            self._make_obs("ruby.file", "lib/default.rb", name="lib/default.rb"),
            self._make_obs("ruby.module", "lib/default.rb", name="DefaultMod"),
            self._make_obs("ruby.method", "lib/default.rb", name="mod_method", metadata={"owner": "DefaultMod", "owner_kind": "ruby.module"}),
            self._make_obs("ruby.constant", "lib/default.rb", name="LIMIT", metadata={"owner": "DefaultMod", "owner_kind": "ruby.class"}),
        ]
        res_fb = canonicalize_observations(obs_fallbacks)
        self.assertTrue(res_fb.ok, res_fb.diagnostics)
        edges_fb = {(e.source_key, e.kind, e.target_key) for e in res_fb.graph.edges}
        self.assertIn((file_key("lib/default.rb"), "defines", ruby_file_key("lib/default.rb")), edges_fb)
        self.assertIn((ruby_file_key("lib/default.rb"), "defines", ruby_module_key("DefaultMod")), edges_fb)
        self.assertIn((ruby_module_key("DefaultMod"), "defines", ruby_method_key("DefaultMod", "mod_method")), edges_fb)
        self.assertIn((ruby_class_key("DefaultMod"), "defines", ruby_constant_key("DefaultMod", "LIMIT")), edges_fb)

        obs_display = [
            self._make_obs("ruby.class", "lib/disp.rb", name="Short", metadata={"qualified_name": "Full::Qualified::Class"}),
            self._make_obs("ruby.constant", "lib/disp.rb", name="C", metadata={"owner": "Full::Qualified::Class", "constant_name": "MY_CONST"}),
        ]
        res_disp = canonicalize_observations(obs_display)
        nodes_by_key = {n.canonical_key: n for n in res_disp.graph.nodes}
        self.assertEqual(nodes_by_key[ruby_class_key("Short")].display_name, "Full::Qualified::Class")
        self.assertEqual(nodes_by_key[ruby_constant_key("Full::Qualified::Class", "C")].display_name, "MY_CONST")

    def test_javascript_permitted_explicit_namespaces_and_fallbacks(self) -> None:
        """JavaScript canonicalization supports explicit source namespaces and falls back predictably."""
        obs_js_explicit = [
            self._make_obs("js.file", "src/app.js", name="src/app.js", metadata={"source_key": "file:src/app.js"}),
            self._make_obs("js.module", "src/app.js", name="src/app.js", metadata={"source_key": "js.file:file%3Asrc%2Fapp.js"}),
            self._make_obs("js.function", "src/app.js", name="init", metadata={"source_key": "js.class:file%3Asrc%2Fapp.js:Service"}),
            self._make_obs("js.component", "src/app.js", name="Card", metadata={"source_key": "js.module:file%3Asrc%2Fapp.js"}),
            self._make_obs("js.route", "src/routes.js", name="route1", metadata={"source_key": "js.module:file%3Asrc%2Froutes.js", "route_pointer": "/routes/1"}),
        ]
        res_js_exp = canonicalize_observations(obs_js_explicit)
        self.assertTrue(res_js_exp.ok, res_js_exp.diagnostics)
        edges_js_exp = {(e.source_key, e.kind, e.target_key) for e in res_js_exp.graph.edges}
        self.assertIn(("file:src/app.js", "defines", js_file_key("src/app.js")), edges_js_exp)
        self.assertIn(("js.file:file%3Asrc%2Fapp.js", "defines", js_module_key("src/app.js")), edges_js_exp)
        self.assertIn(("js.class:file%3Asrc%2Fapp.js:Service", "defines", js_function_key("src/app.js", "init")), edges_js_exp)
        self.assertIn(("js.module:file%3Asrc%2Fapp.js", "defines", js_component_key("src/app.js", "Card")), edges_js_exp)
        self.assertIn(("js.module:file%3Asrc%2Froutes.js", "defines", js_route_key("src/routes.js", "/routes/1")), edges_js_exp)

        obs_js_fallbacks = [
            self._make_obs("js.file", "src/client.js", name="src/client.js"),
            self._make_obs("js.module", "src/client.js", name="src/client.js"),
            self._make_obs("js.method", "src/client.js", name="start", metadata={"class_name": "Engine"}),
            self._make_obs("js.test_suite", "src/suite.test.js", name="suiteA"),
            self._make_obs("js.test_case", "src/suite.test.js", name="caseA"),
        ]
        res_js_fb = canonicalize_observations(obs_js_fallbacks)
        self.assertTrue(res_js_fb.ok, res_js_fb.diagnostics)
        edges_js_fb = {(e.source_key, e.kind, e.target_key) for e in res_js_fb.graph.edges}
        self.assertIn((file_key("src/client.js"), "defines", js_file_key("src/client.js")), edges_js_fb)
        self.assertIn((js_file_key("src/client.js"), "defines", js_module_key("src/client.js")), edges_js_fb)
        expected_class = js_class_key("src/client.js", "Engine")
        self.assertIn((expected_class, "defines", js_method_key(expected_class, "start")), edges_js_fb)
        self.assertIn((js_file_key("src/suite.test.js"), "defines", js_test_case_key(js_file_key("src/suite.test.js"), "/tests/caseA")), edges_js_fb)
        self.assertIn((js_module_key("src/suite.test.js"), "defines", js_test_suite_key("src/suite.test.js", "/tests/suiteA")), edges_js_fb)

    def test_ruby_unresolved_reference_classification_and_diagnostics(self) -> None:
        """Unresolved Ruby references emit warning diagnostics and deterministic placeholder keys."""
        obs_missing = self._make_obs("ruby.reference", "lib/service.rb", name="missing_ref")
        res_missing = canonicalize_observations([obs_missing])
        self.assertTrue(res_missing.ok)
        self.assertEqual(len(res_missing.diagnostics), 1)
        diag_missing = res_missing.diagnostics[0]
        self.assertEqual(diag_missing.severity, "warning")
        self.assertEqual(diag_missing.category, "missing_required_metadata")
        self.assertEqual(diag_missing.placeholder_key, "unknown:ruby.reference:missing-target")
        self.assertEqual(len(res_missing.graph.edges), 1)
        edge_missing = res_missing.graph.edges[0]
        self.assertEqual(edge_missing.source_key, ruby_file_key("lib/service.rb"))
        self.assertEqual(edge_missing.target_key, "unknown:ruby.reference:missing-target")
        self.assertEqual(edge_missing.kind, "references")

        obs_malformed = self._make_obs("ruby.reference", "lib/service.rb", target="malformed target key with spaces")
        res_malformed = canonicalize_observations([obs_malformed])
        self.assertTrue(res_malformed.ok)
        self.assertEqual(len(res_malformed.diagnostics), 1)
        diag_mal = res_malformed.diagnostics[0]
        self.assertEqual(diag_mal.severity, "warning")
        self.assertEqual(diag_mal.category, "invalid_canonical_key")
        self.assertEqual(diag_mal.placeholder_key, "unknown:ruby.reference:malformed-target")
        self.assertEqual(res_malformed.graph.edges[0].target_key, "unknown:ruby.reference:malformed-target")

        obs_percent = self._make_obs("ruby.reference", "lib/service.rb", target="ruby.module:Bad%ZZEscape")
        res_percent = canonicalize_observations([obs_percent])
        self.assertTrue(res_percent.ok)
        self.assertEqual(res_percent.diagnostics[0].category, "malformed_percent_escape")
        self.assertEqual(res_percent.diagnostics[0].placeholder_key, "unknown:ruby.reference:malformed-target")

        obs_bad_src = self._make_obs("ruby.reference", "lib/service.rb", target="file:lib/other.rb", metadata={"source_key": "python.module:invalid"})
        res_bad_src = canonicalize_observations([obs_bad_src])
        self.assertFalse(res_bad_src.ok)
        self.assertEqual(res_bad_src.diagnostics[0].severity, "error")
        self.assertIn("ruby.reference source_key has unsupported namespace", res_bad_src.diagnostics[0].message)

        obs_meta_target = self._make_obs("ruby.reference", "lib/service.rb", metadata={"target_key": "ruby.class:ResolvedClass"})
        res_meta_target = canonicalize_observations([obs_meta_target])
        self.assertTrue(res_meta_target.ok)
        self.assertEqual(len(res_meta_target.diagnostics), 0)
        self.assertEqual(res_meta_target.graph.edges[0].target_key, "ruby.class:ResolvedClass")

    def test_javascript_unresolved_reference_classification_and_diagnostics(self) -> None:
        """Unresolved JavaScript references emit warning diagnostics and deterministic placeholder keys."""
        obs_js_missing = self._make_obs("js.reference", "src/client.js", name="missing_js_ref")
        res_js_missing = canonicalize_observations([obs_js_missing])
        self.assertTrue(res_js_missing.ok)
        self.assertEqual(len(res_js_missing.diagnostics), 1)
        diag_js_missing = res_js_missing.diagnostics[0]
        self.assertEqual(diag_js_missing.severity, "warning")
        self.assertEqual(diag_js_missing.category, "missing_required_metadata")
        self.assertEqual(diag_js_missing.placeholder_key, "unknown:js.reference:missing-target")
        self.assertEqual(res_js_missing.graph.edges[0].target_key, "unknown:js.reference:missing-target")

        obs_js_malformed = self._make_obs("js.reference", "src/client.js", target="invalid key without namespace")
        res_js_malformed = canonicalize_observations([obs_js_malformed])
        self.assertTrue(res_js_malformed.ok)
        self.assertEqual(len(res_js_malformed.diagnostics), 1)
        diag_js_mal = res_js_malformed.diagnostics[0]
        self.assertEqual(diag_js_mal.severity, "warning")
        self.assertEqual(diag_js_mal.category, "invalid_canonical_key")
        self.assertEqual(diag_js_mal.placeholder_key, "unknown:js.reference:malformed-target")
        self.assertEqual(res_js_malformed.graph.edges[0].target_key, "unknown:js.reference:malformed-target")

        obs_js_percent = self._make_obs("js.reference", "src/client.js", target="js.class:file%3Asrc%2Fclient.js%ZZ:Bad")
        res_js_percent = canonicalize_observations([obs_js_percent])
        self.assertTrue(res_js_percent.ok)
        self.assertEqual(res_js_percent.diagnostics[0].category, "malformed_percent_escape")
        self.assertEqual(res_js_percent.diagnostics[0].placeholder_key, "unknown:js.reference:malformed-target")

        obs_js_bad_src = self._make_obs("js.reference", "src/client.js", target="file:src/other.js", metadata={"source_key": "ruby.file:file%3Alib%2Fapp.rb"})
        res_js_bad_src = canonicalize_observations([obs_js_bad_src])
        self.assertFalse(res_js_bad_src.ok)
        self.assertEqual(res_js_bad_src.diagnostics[0].severity, "error")
        self.assertIn("js.reference source_key has unsupported namespace", res_js_bad_src.diagnostics[0].message)

        obs_js_meta_target = self._make_obs("js.reference", "src/client.js", metadata={"target_key": "js.module:file%3Asrc%2Fhelper.js"})
        res_js_meta_target = canonicalize_observations([obs_js_meta_target])
        self.assertTrue(res_js_meta_target.ok)
        self.assertEqual(len(res_js_meta_target.diagnostics), 0)
        self.assertEqual(res_js_meta_target.graph.edges[0].target_key, "js.module:file%3Asrc%2Fhelper.js")

    def test_ruby_and_javascript_evidence_links_and_edge_metadata_accumulation(self) -> None:
        """Node/edge evidence links retain provenance and multiple references merge metadata cleanly."""
        obs_def = self._make_obs("ruby.class", "lib/app.rb", name="Runner", target=ruby_class_key("Runner"))
        obs_ref = self._make_obs("ruby.reference", "lib/app.rb", target="file:lib/util.rb", metadata={"source_key": ruby_class_key("Runner")})
        res = canonicalize_observations([obs_def, obs_ref])
        self.assertTrue(res.ok)
        node_links = {(nl.canonical_key, nl.link_kind) for nl in res.graph.node_evidence_links}
        self.assertIn((ruby_file_key("lib/app.rb"), "inferred_from_edge"), node_links)
        self.assertIn((ruby_class_key("Runner"), "observed"), node_links)
        self.assertIn(("file:lib/util.rb", "inferred_from_edge"), node_links)
        edge_links = {el.link_kind for el in res.graph.edge_evidence_links}
        self.assertEqual(edge_links, {"supports"})

        ref1 = self._make_obs(
            "js.reference",
            "src/index.js",
            target="file:src/util.js",
            confidence="heuristic",
            metadata={"profile": "p1", "reference_kind": "require", "not_fetched": True},
        )
        ref2 = self._make_obs(
            "js.reference",
            "src/index.js",
            target="file:src/util.js",
            confidence="extracted",
            metadata={"profile": "p2", "reference_kind": "import", "dynamic": True},
        )
        res_merged = canonicalize_observations([ref1, ref2])
        self.assertTrue(res_merged.ok)
        self.assertEqual(len(res_merged.graph.edges), 1)
        edge = res_merged.graph.edges[0]
        self.assertEqual(edge.confidence, "extracted")
        self.assertEqual(edge.metadata["profiles"], ["p1", "p2"])
        self.assertEqual(edge.metadata["reference_kinds"], ["require", "import"])
        self.assertTrue(edge.metadata["not_fetched"])
        self.assertTrue(edge.metadata["dynamic_observed"])
