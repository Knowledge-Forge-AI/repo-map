import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
import repomap_kg.graph.keys as k
from repomap_kg.observations.raw import RawObservation


class Slice6LanguagePipelineIntegrationTests(unittest.TestCase):
    """Integration scenarios for Slice 6 Group S6-A language pipelines."""

    def test_s6_a01_python_nested_ownership_and_method_evidence(self) -> None:
        """Python module, class, and method ownership with evidence attribution."""
        module_target = k.python_module_key("service")
        func_target = k.python_function_key("service", "start")
        class_target = k.python_class_key("service", "Server")
        method_target = k.python_method_key("service", "Server", "listen")
        file_node = k.file_key("src/service.py")

        obs = [
            RawObservation(
                kind="python.module", source_id="src/service.py#mod:service",
                path="src/service.py", name="service", target=module_target,
                confidence="extracted", extractor="repo-python", extractor_version="0.1.0",
                metadata={"module": "service"},
            ),
            RawObservation(
                kind="python.function", source_id="src/service.py#func:start",
                path="src/service.py", start_line=1, end_line=5, name="start",
                target=func_target, confidence="extracted", extractor="repo-python",
                extractor_version="0.1.0", metadata={"module": "service"},
            ),
            RawObservation(
                kind="python.class", source_id="src/service.py#class:Server",
                path="src/service.py", start_line=6, end_line=20, name="Server",
                target=class_target, confidence="extracted", extractor="repo-python",
                extractor_version="0.1.0", metadata={"module": "service"},
            ),
            RawObservation(
                kind="python.method", source_id="src/service.py#method:listen",
                path="src/service.py", start_line=10, end_line=15, name="listen",
                target=method_target, confidence="extracted", extractor="repo-python",
                extractor_version="0.1.0", metadata={"module": "service", "class": "Server"},
            ),
        ]
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        payload = res.to_dict()

        nodes_by_key = {node["canonical_key"]: node["kind"] for node in payload["nodes"]}
        self.assertEqual(nodes_by_key.get(module_target), "python.module")
        self.assertEqual(nodes_by_key.get(func_target), "python.function")
        self.assertEqual(nodes_by_key.get(class_target), "python.class")
        self.assertEqual(nodes_by_key.get(method_target), "python.method")

        edge_triples = {(e["source_key"], e["kind"], e["target_key"]) for e in payload["edges"]}
        self.assertIn((file_node, "defines", module_target), edge_triples)
        self.assertIn((file_node, "defines", func_target), edge_triples)
        self.assertIn((file_node, "defines", class_target), edge_triples)
        self.assertIn((file_node, "defines", method_target), edge_triples)

        node_evidence = {
            (link["canonical_key"], link["link_kind"])
            for link in payload.get("node_evidence_links", [])
        }
        self.assertIn((file_node, "inferred_from_edge"), node_evidence)
        self.assertIn((method_target, "observed"), node_evidence)

    def test_s6_a02_ruby_nested_ownership_singleton_and_instance_methods(self) -> None:
        """Ruby file -> module -> class -> instance/singleton method ownership."""
        rb_file = k.ruby_file_key("src/app.rb")
        rb_mod = k.ruby_module_key("App")
        rb_cls = k.ruby_class_key("Worker")
        rb_inst = k.ruby_method_key("Worker", "perform")
        rb_sing = k.ruby_singleton_method_key("Worker", "batch")
        file_node = k.file_key("src/app.rb")

        obs = [
            RawObservation(
                kind="ruby.file", source_id="src/app.rb", path="src/app.rb",
                name="app.rb", target=rb_file, confidence="extracted",
                extractor="repo-ruby", extractor_version="0.1.0",
            ),
            RawObservation(
                kind="ruby.module", source_id="src/app.rb#module:App", path="src/app.rb",
                name="App", target=rb_mod, confidence="extracted", extractor="repo-ruby",
                extractor_version="0.1.0", metadata={"owner": "src/app.rb", "owner_kind": "ruby.file"},
            ),
            RawObservation(
                kind="ruby.class", source_id="src/app.rb#class:Worker", path="src/app.rb",
                name="Worker", target=rb_cls, confidence="extracted", extractor="repo-ruby",
                extractor_version="0.1.0", metadata={"source_key": rb_mod},
            ),
            RawObservation(
                kind="ruby.method", source_id="src/app.rb#method:perform", path="src/app.rb",
                name="perform", target=rb_inst, confidence="extracted", extractor="repo-ruby",
                extractor_version="0.1.0", metadata={"owner": "Worker", "owner_kind": "ruby.class"},
            ),
            RawObservation(
                kind="ruby.singleton_method", source_id="src/app.rb#smethod:batch", path="src/app.rb",
                name="batch", target=rb_sing, confidence="extracted", extractor="repo-ruby",
                extractor_version="0.1.0", metadata={"owner": "Worker", "owner_kind": "ruby.class"},
            ),
        ]
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        payload = res.to_dict()

        edge_triples = {(e["source_key"], e["kind"], e["target_key"]) for e in payload["edges"]}
        self.assertIn((file_node, "defines", rb_file), edge_triples)
        self.assertIn((rb_file, "defines", rb_mod), edge_triples)
        self.assertIn((rb_mod, "defines", rb_cls), edge_triples)
        self.assertIn((rb_cls, "defines", rb_inst), edge_triples)
        self.assertIn((rb_cls, "defines", rb_sing), edge_triples)

    def test_s6_a03_js_class_method_explicit_and_inferred_owners(self) -> None:
        """JS class method ownership via explicit class_key vs inferred class_name."""
        js_mod = k.js_module_key("src/client.js")
        js_cls = k.js_class_key("src/client.js", "Client")
        js_meth_exp = k.js_method_key(js_cls, "fetchData")
        js_meth_inf = k.js_method_key(js_cls, "disconnect")
        js_file = k.js_file_key("src/client.js")

        obs = [
            RawObservation(
                kind="js.module", source_id="src/client.js", path="src/client.js",
                name="client.js", target=js_mod, confidence="extracted",
                extractor="repo-js", extractor_version="0.1.0",
            ),
            RawObservation(
                kind="js.class", source_id="src/client.js#class:Client", path="src/client.js",
                name="Client", target=js_cls, confidence="extracted",
                extractor="repo-js", extractor_version="0.1.0",
            ),
            RawObservation(
                kind="js.method", source_id="src/client.js#method:fetchData", path="src/client.js",
                name="fetchData", target=js_meth_exp, confidence="extracted",
                extractor="repo-js", extractor_version="0.1.0", metadata={"class_key": js_cls},
            ),
            RawObservation(
                kind="js.method", source_id="src/client.js#method:disconnect", path="src/client.js",
                name="disconnect", target=js_meth_inf, confidence="extracted",
                extractor="repo-js", extractor_version="0.1.0", metadata={"class_name": "Client"},
            ),
        ]
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        payload = res.to_dict()

        edge_triples = {(e["source_key"], e["kind"], e["target_key"]) for e in payload["edges"]}
        self.assertIn((js_file, "defines", js_mod), edge_triples)
        self.assertIn((js_mod, "defines", js_cls), edge_triples)
        self.assertIn((js_cls, "defines", js_meth_exp), edge_triples)
        self.assertIn((js_cls, "defines", js_meth_inf), edge_triples)

    def test_s6_a04_source_key_namespace_validation_and_refusal(self) -> None:
        """Disallowed source namespace produces diagnostic error and refuses edge."""
        obs = [
            RawObservation(
                kind="ruby.class", source_id="src/bad.rb#class:Bad", path="src/bad.rb",
                start_line=1, end_line=10, name="Bad", target="ruby.class:Bad",
                confidence="extracted", extractor="repo-ruby", extractor_version="0.1.0",
                metadata={"source_key": "disallowed.ns:foo"},
            ),
            RawObservation(
                kind="js.function", source_id="src/bad.js#func:bad", path="src/bad.js",
                start_line=1, end_line=5, name="bad", target=k.js_function_key("src/bad.js", "bad"),
                confidence="extracted", extractor="repo-js", extractor_version="0.1.0",
                metadata={"source_key": "unsupported.js.ns:bar"},
            ),
        ]
        res = canonicalize_observations(obs)
        self.assertFalse(res.ok)
        payload = res.to_dict()
        self.assertEqual(len(payload["edges"]), 0)
        diagnostics = payload.get("diagnostics", [])
        categories = {d.get("category") for d in diagnostics}
        self.assertIn("invalid_canonical_key", categories)
        severities = {d.get("severity") for d in diagnostics}
        self.assertIn("error", severities)

    def test_s6_a05_reference_targets_concrete_and_diagnostics(self) -> None:
        """Concrete call target vs missing target vs malformed target diagnostics."""
        target_meth = k.ruby_method_key("Worker", "perform")
        missing_ph = k.unknown_key("ruby.reference", "missing-target")
        malformed_ph = k.unknown_key("ruby.reference", "malformed-target")

        obs = [
            RawObservation(
                kind="ruby.reference", source_id="src/app.rb#ref:concrete", path="src/app.rb",
                confidence="extracted", extractor="repo-ruby", extractor_version="0.1.0", target=target_meth,
            ),
            RawObservation(
                kind="ruby.reference", source_id="src/app.rb#ref:missing", path="src/app.rb",
                confidence="extracted", extractor="repo-ruby", extractor_version="0.1.0", target=None,
            ),
            RawObservation(
                kind="ruby.reference", source_id="src/app.rb#ref:malformed", path="src/app.rb",
                confidence="extracted", extractor="repo-ruby", extractor_version="0.1.0", target="malformed-not-a-key",
            ),
        ]
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        payload = res.to_dict()
        targets = {e["target_key"] for e in payload["edges"]}
        self.assertIn(target_meth, targets)
        self.assertIn(missing_ph, targets)
        self.assertIn(malformed_ph, targets)

        diag_cats = {d.get("category") for d in payload.get("diagnostics", [])}
        self.assertIn("missing_required_metadata", diag_cats)
        self.assertIn("invalid_canonical_key", diag_cats)

    def test_s6_a06_polyglot_same_name_namespace_isolation(self) -> None:
        """Same identifier 'Config' across Python, Ruby, and JS maintains clean separation."""
        py_key = k.python_class_key("config", "Config")
        rb_key = k.ruby_class_key("Config")
        js_key = k.js_class_key("src/config.js", "Config")

        obs = [
            RawObservation(
                kind="python.class", source_id="src/config.py#class:Config", path="src/config.py",
                name="Config", target=py_key, confidence="extracted", extractor="repo-python",
                extractor_version="0.1.0", metadata={"module": "config"},
            ),
            RawObservation(
                kind="ruby.class", source_id="src/config.rb#class:Config", path="src/config.rb",
                name="Config", target=rb_key, confidence="extracted", extractor="repo-ruby",
                extractor_version="0.1.0",
            ),
            RawObservation(
                kind="js.class", source_id="src/config.js#class:Config", path="src/config.js",
                name="Config", target=js_key, confidence="extracted", extractor="repo-js",
                extractor_version="0.1.0",
            ),
        ]
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        payload = res.to_dict()
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn(py_key, node_keys)
        self.assertIn(rb_key, node_keys)
        self.assertIn(js_key, node_keys)
        config_keys = {node["canonical_key"] for node in payload["nodes"] if "Config" in node["canonical_key"]}
        self.assertEqual(len(config_keys), 3)

    def test_s6_a07_canonical_evidence_attribution_and_raw_provenance(self) -> None:
        """Definitions receive observed target and inferred source evidence links."""
        func_key = k.python_function_key("service", "run")
        file_key = k.file_key("src/service.py")

        obs = [
            RawObservation(
                kind="python.function", source_id="src/service.py#func:run", path="src/service.py",
                start_line=1, end_line=10, name="run", target=func_key,
                confidence="extracted", extractor="repo-python", extractor_version="0.1.0",
                metadata={"module": "service"},
            )
        ]
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        payload = res.to_dict()

        evidence = payload.get("evidence", [])
        self.assertEqual(len(evidence), 1)
        ev_key = evidence[0]["evidence_key"]
        self.assertEqual(evidence[0]["raw_source_id"], "src/service.py#func:run")

        node_links = payload.get("node_evidence_links", [])
        self.assertTrue(
            any(
                link["canonical_key"] == func_key
                and link["evidence_key"] == ev_key
                and link["link_kind"] == "observed"
                for link in node_links
            )
        )
        self.assertTrue(
            any(
                link["canonical_key"] == file_key
                and link["evidence_key"] == ev_key
                and link["link_kind"] == "inferred_from_edge"
                for link in node_links
            )
        )
        edge_links = payload.get("edge_evidence_links", [])
        self.assertTrue(
            any(link["evidence_key"] == ev_key and link["link_kind"] == "supports" for link in edge_links)
        )

    def test_s6_a08_deterministic_identities_under_reordered_observations(self) -> None:
        """Deterministic canonical node and edge sets regardless of observation ordering."""
        py_func = k.python_function_key("app", "init")
        rb_cls = k.ruby_class_key("App")
        js_func = k.js_function_key("src/index.js", "main")

        obs1 = [
            RawObservation(
                kind="python.function", source_id="src/app.py#func:init", path="src/app.py",
                name="init", target=py_func, confidence="extracted", extractor="repo-python",
                extractor_version="0.1.0", metadata={"module": "app"},
            ),
            RawObservation(
                kind="ruby.class", source_id="src/app.rb#class:App", path="src/app.rb",
                name="App", target=rb_cls, confidence="extracted", extractor="repo-ruby",
                extractor_version="0.1.0",
            ),
            RawObservation(
                kind="js.function", source_id="src/index.js#func:main", path="src/index.js",
                name="main", target=js_func, confidence="extracted", extractor="repo-js",
                extractor_version="0.1.0",
            ),
        ]
        obs2 = list(reversed(obs1))

        res1 = canonicalize_observations(obs1)
        res2 = canonicalize_observations(obs2)

        keys1 = {n["canonical_key"] for n in res1.to_dict()["nodes"]}
        keys2 = {n["canonical_key"] for n in res2.to_dict()["nodes"]}
        self.assertEqual(keys1, keys2)

        edges1 = {(e["source_key"], e["kind"], e["target_key"]) for e in res1.to_dict()["edges"]}
        edges2 = {(e["source_key"], e["kind"], e["target_key"]) for e in res2.to_dict()["edges"]}
        self.assertEqual(edges1, edges2)
