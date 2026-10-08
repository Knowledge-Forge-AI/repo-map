from __future__ import annotations

import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.extractors.languages.javascript import extract_javascript_file_observations
from repomap_kg.extractors.languages.python import PythonModuleIndex, extract_python_file_observations
from repomap_kg.extractors.languages.ruby import extract_ruby_file_observations
import repomap_kg.graph.keys as k
from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.canonical_rows import prepare_canonical_load


class Slice7LanguagePipelineIntegrationTests(unittest.TestCase):
    """Integration scenarios for Slice 7 Group S7-A real source to canonical graph and typed rows."""

    def test_s7_a01_python_source_to_canonical_graph_and_typed_rows(self) -> None:
        """Real Python source extracts module, class, methods, and functions into typed storage rows."""
        py_source = (
            '"""Worker pool implementation."""\n'
            "from __future__ import annotations\n\n"
            "class WorkerPool:\n"
            '    """Manages worker instances."""\n\n'
            "    def schedule(self, task: str) -> bool:\n"
            "        return True\n\n"
            "def init_pool(workers: int) -> WorkerPool:\n"
            "    return WorkerPool()\n"
        )
        rel_path = "service/worker_pool.py"
        idx = PythonModuleIndex.from_modules({"service.worker_pool": rel_path})
        obs = extract_python_file_observations(rel_path, py_source, module_index=idx)
        self.assertGreater(len(obs), 0)

        load = prepare_canonical_load(obs)
        self.assertTrue(load.result.ok)
        self.assertGreater(len(load.raw_rows), 0)

        file_node = k.file_key(rel_path)
        mod_node = k.python_module_key("service.worker_pool")
        class_node = k.python_class_key("service.worker_pool", "WorkerPool")
        method_node = k.python_method_key("service.worker_pool", "WorkerPool", "schedule")
        func_node = k.python_function_key("service.worker_pool", "init_pool")

        node_map = {n.canonical_key: n.kind for n in load.canonical_rows.nodes}
        self.assertEqual(node_map.get(mod_node), "python.module")
        self.assertEqual(node_map.get(class_node), "python.class")
        self.assertEqual(node_map.get(method_node), "python.method")
        self.assertEqual(node_map.get(func_node), "python.function")

        edge_triples = {
            (e.source_key, e.edge_kind, e.target_key)
            for e in load.canonical_rows.edges
        }
        self.assertIn((file_node, "defines", mod_node), edge_triples)
        self.assertIn((file_node, "defines", class_node), edge_triples)
        self.assertIn((file_node, "defines", method_node), edge_triples)
        self.assertIn((file_node, "defines", func_node), edge_triples)

        self.assertGreater(len(load.canonical_rows.evidence), 0)
        self.assertGreater(len(load.canonical_rows.node_evidence_links), 0)
        self.assertGreater(len(load.canonical_rows.edge_evidence_links), 0)
        self.assertTrue(all(len(r.payload_hash) > 0 for r in load.raw_rows))

    def test_s7_a02_python_source_import_resolution_and_non_py_refusal(self) -> None:
        """Python non-.py path refusal and external import reference diagnostics."""
        non_py = extract_python_file_observations(
            "service/data.txt",
            "hello",
            module_index=PythonModuleIndex.empty(),
        )
        self.assertEqual(non_py, ())

        py_source = (
            "import os\n"
            "from math import sqrt\n\n"
            "def calculate(v: float) -> float:\n"
            "    return sqrt(v)\n"
        )
        rel_path = "service/math_calc.py"
        idx = PythonModuleIndex.from_modules({"service.math_calc": rel_path})
        obs = extract_python_file_observations(rel_path, py_source, module_index=idx)
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        self.assertEqual(res.diagnostics, ())

        # Explicitly labelled boundary-negative hand-built RawObservation for missing module metadata
        boundary_neg_obs = RawObservation(
            kind="python.import",
            source_id="service/math_calc.py#import:neg",
            path=rel_path,
            target=k.external_key("python", "unresolved.lib"),
            confidence="extracted",
            extractor="repo-python",
            extractor_version="0.1.0",
            metadata={},
        )
        neg_res = canonicalize_observations((boundary_neg_obs,))
        self.assertTrue(neg_res.ok)
        self.assertTrue(any(d.category == "missing_required_metadata" for d in neg_res.diagnostics))

    def test_s7_a03_ruby_source_nested_module_class_and_methods_to_rows(self) -> None:
        """Ruby source extraction establishes module-to-class-to-method defining hierarchy."""
        rb_source = (
            "module Engine\n"
            "  class Processor\n"
            "    def process\n"
            "      100\n"
            "    end\n\n"
            "    def self.spawn\n"
            "      new\n"
            "    end\n"
            "  end\n"
            "end\n"
        )
        rel_path = "lib/engine/processor.rb"
        obs = extract_ruby_file_observations(rel_path, rb_source)
        load = prepare_canonical_load(obs)
        self.assertTrue(load.result.ok)

        file_node = k.ruby_file_key(rel_path)
        mod_node = k.ruby_module_key("Engine")
        class_node = k.ruby_class_key("Engine::Processor")
        inst_method = k.ruby_method_key("Engine::Processor", "process")
        sing_method = k.ruby_singleton_method_key("Engine::Processor", "spawn")

        nodes_by_key = {n.canonical_key: n.kind for n in load.canonical_rows.nodes}
        self.assertEqual(nodes_by_key.get(mod_node), "ruby.module")
        self.assertEqual(nodes_by_key.get(class_node), "ruby.class")
        self.assertEqual(nodes_by_key.get(inst_method), "ruby.method")
        self.assertEqual(nodes_by_key.get(sing_method), "ruby.singleton_method")

        top_file_node = k.file_key(rel_path)
        edge_triples = {
            (e.source_key, e.edge_kind, e.target_key)
            for e in load.canonical_rows.edges
        }
        self.assertIn((top_file_node, "defines", file_node), edge_triples)
        self.assertIn((file_node, "defines", mod_node), edge_triples)
        self.assertIn((file_node, "defines", class_node), edge_triples)
        self.assertIn((class_node, "defines", inst_method), edge_triples)
        self.assertIn((class_node, "defines", sing_method), edge_triples)

    def test_s7_a04_ruby_source_reference_resolution_and_repaired_recovery(self) -> None:
        """Ruby relative require resolves local target vs uncommitted candidate and escaping refusal."""
        repo_paths = frozenset({"lib/app.rb", "lib/helper.rb"})
        src_valid = 'require_relative "helper"\n'
        obs_valid = extract_ruby_file_observations("lib/app.rb", src_valid, repository_paths=repo_paths)
        self.assertTrue(any(o.metadata.get("resolution_reason") == "repo-local" for o in obs_valid))

        src_candidate = 'require_relative "pending_module"\n'
        obs_candidate = extract_ruby_file_observations("lib/app.rb", src_candidate, repository_paths=repo_paths)
        self.assertTrue(any(o.metadata.get("resolution_reason") == "repo-local-candidate" for o in obs_candidate))

        src_escape = 'require_relative "../../outside"\n'
        obs_escape = extract_ruby_file_observations("lib/app.rb", src_escape, repository_paths=repo_paths)
        self.assertTrue(any("repo-escaping" in str(o.target) for o in obs_escape))

        # Explicitly labelled boundary-negative hand-built RawObservation with target=None
        boundary_neg_ruby = RawObservation(
            kind="ruby.reference",
            source_id="lib/app.rb#reference:none",
            path="lib/app.rb",
            target=None,
            confidence="extracted",
            extractor="repo-ruby",
            extractor_version="0.1.0",
            metadata={},
        )
        neg_res = canonicalize_observations((boundary_neg_ruby,))
        self.assertTrue(neg_res.ok)
        self.assertTrue(any(d.category == "missing_required_metadata" and "missing-target" in str(d.placeholder_key) for d in neg_res.diagnostics))

    def test_s7_a05_js_source_es_module_classes_and_functions_to_rows(self) -> None:
        """JavaScript ES module extraction defines classes, functions, and methods into typed rows."""
        js_source = (
            "export class Dispatcher {\n"
            "  route(req) {\n"
            "    return true;\n"
            "  }\n"
            "}\n\n"
            "export function makeDispatcher() {\n"
            "  return new Dispatcher();\n"
            "}\n"
        )
        rel_path = "src/dispatcher.js"
        obs = extract_javascript_file_observations(rel_path, js_source)
        load = prepare_canonical_load(obs)
        self.assertTrue(load.result.ok)

        mod_node = k.js_module_key(rel_path)
        class_node = k.js_class_key(rel_path, "Dispatcher")
        method_node = k.js_method_key(class_node, "route")
        func_node = k.js_function_key(rel_path, "makeDispatcher")

        nodes_by_key = {n.canonical_key: n.kind for n in load.canonical_rows.nodes}
        self.assertEqual(nodes_by_key.get(class_node), "js.class")
        self.assertEqual(nodes_by_key.get(method_node), "js.method")
        self.assertEqual(nodes_by_key.get(func_node), "js.function")

        edge_triples = {
            (e.source_key, e.edge_kind, e.target_key)
            for e in load.canonical_rows.edges
        }
        self.assertIn((mod_node, "defines", class_node), edge_triples)
        self.assertIn((mod_node, "defines", func_node), edge_triples)
        self.assertIn((class_node, "defines", method_node), edge_triples)

    def test_s7_a06_polyglot_same_path_isolation_and_reorder_determinism(self) -> None:
        """Multi-language sources at identical relative paths preserve namespaces and permutation determinism."""
        py_src = "class CoreRunner:\n    def execute(self): pass\n"
        rb_src = "module CoreRunner\n  def self.execute; end\nend\n"
        js_src = "export class CoreRunner { execute() {} }\n"

        py_path = "shared/runner.py"
        rb_path = "shared/runner.rb"
        js_path = "shared/runner.js"

        idx = PythonModuleIndex.from_modules({"shared.runner": py_path})
        obs_py = extract_python_file_observations(py_path, py_src, module_index=idx)
        obs_rb = extract_ruby_file_observations(rb_path, rb_src)
        obs_js = extract_javascript_file_observations(js_path, js_src)

        res_fwd = canonicalize_observations((*obs_py, *obs_rb, *obs_js))
        res_rev = canonicalize_observations((*obs_js, *obs_rb, *obs_py))
        self.assertTrue(res_fwd.ok)
        self.assertTrue(res_rev.ok)

        fwd_nodes = {n.canonical_key for n in res_fwd.graph.nodes}
        rev_nodes = {n.canonical_key for n in res_rev.graph.nodes}
        self.assertEqual(fwd_nodes, rev_nodes)

        fwd_edges = {(e.source_key, e.kind, e.target_key) for e in res_fwd.graph.edges}
        rev_edges = {(e.source_key, e.kind, e.target_key) for e in res_rev.graph.edges}
        self.assertEqual(fwd_edges, rev_edges)

        # Verify key namespace separation
        self.assertTrue(any(key.startswith("python.") for key in fwd_nodes))
        self.assertTrue(any(key.startswith("ruby.") for key in fwd_nodes))
        self.assertTrue(any(key.startswith("js.") for key in fwd_nodes))
