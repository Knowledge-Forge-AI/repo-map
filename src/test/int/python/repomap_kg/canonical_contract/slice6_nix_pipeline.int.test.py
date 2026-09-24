import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
import repomap_kg.extractors.config.nix as nix
import repomap_kg.graph.keys as k
from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.canonical_rows import canonical_rows_from_result, prepare_canonical_load


class Slice6NixPipelineIntegrationTests(unittest.TestCase):
    """Integration scenarios for Slice 6 Group S6-B Nix pipelines."""

    def test_s6_b01_nix_concrete_outputs_and_canonical_edge_keys(self) -> None:
        """Concrete packages, apps, devShells, and checks outputs receive defines edges."""
        flake_file = k.file_key("flake.nix")
        pkg_key = k.nix_package_key("flake:default", "x86_64-linux", "default")
        app_key = k.nix_app_key("flake:default", "x86_64-linux", "default")
        dev_key = k.nix_dev_shell_key("flake:default", "x86_64-linux", "default")
        chk_key = k.nix_check_key("flake:default", "x86_64-linux", "unit")

        obs = [
            RawObservation(
                kind="nix.package", source_id="flake.nix#pkg:default", path="flake.nix",
                name="default", target=pkg_key, confidence="extracted", extractor="repo-nix",
                extractor_version="0.1.0", metadata={"flake_ref": "flake:default", "system": "x86_64-linux", "name": "default", "output_kind": "package"},
            ),
            RawObservation(
                kind="nix.app", source_id="flake.nix#app:default", path="flake.nix",
                name="default", target=app_key, confidence="extracted", extractor="repo-nix",
                extractor_version="0.1.0", metadata={"flake_ref": "flake:default", "system": "x86_64-linux", "name": "default", "output_kind": "app"},
            ),
            RawObservation(
                kind="nix.devShell", source_id="flake.nix#devShell:default", path="flake.nix",
                name="default", target=dev_key, confidence="extracted", extractor="repo-nix",
                extractor_version="0.1.0", metadata={"flake_ref": "flake:default", "system": "x86_64-linux", "name": "default", "output_kind": "devShell"},
            ),
            RawObservation(
                kind="nix.check", source_id="flake.nix#check:unit", path="flake.nix",
                name="unit", target=chk_key, confidence="extracted", extractor="repo-nix",
                extractor_version="0.1.0", metadata={"flake_ref": "flake:default", "system": "x86_64-linux", "name": "unit", "output_kind": "check"},
            ),
        ]
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        payload = res.to_dict()

        nodes_by_key = {node["canonical_key"]: node["kind"] for node in payload["nodes"]}
        self.assertEqual(nodes_by_key.get(pkg_key), "nix.package")
        self.assertEqual(nodes_by_key.get(app_key), "nix.app")
        self.assertEqual(nodes_by_key.get(dev_key), "nix.devShell")
        self.assertEqual(nodes_by_key.get(chk_key), "nix.check")

        edge_triples = {(e["source_key"], e["kind"], e["target_key"]) for e in payload["edges"]}
        self.assertIn((flake_file, "defines", pkg_key), edge_triples)
        self.assertIn((flake_file, "defines", app_key), edge_triples)
        self.assertIn((flake_file, "defines", dev_key), edge_triples)
        self.assertIn((flake_file, "defines", chk_key), edge_triples)

    def test_s6_b02_nix_app_program_forms_exposing_scripts(self) -> None:
        """App program forms resolve paths and construct exposes_script edges."""
        self.assertEqual(nix.resolve_repo_path("flake.nix", "${self}/bin/tool"), "bin/tool")
        self.assertEqual(nix.resolve_repo_path("flake.nix", "./scripts/run.sh"), "scripts/run.sh")
        self.assertIsNone(nix.resolve_repo_path("flake.nix", "bin/runner"))
        self.assertIsNone(nix.resolve_repo_path("flake.nix", "../outside/bin/tool"))

        app_tool = k.nix_app_key("flake:default", "x86_64-linux", "tool")
        script_tool = k.file_key("bin/tool")

        obs = [
            RawObservation(
                kind="nix.app", source_id="flake.nix#app:tool", path="flake.nix",
                name="tool", target=app_tool, confidence="extracted", extractor="repo-nix",
                extractor_version="0.1.0",
                metadata={"flake_ref": "flake:default", "system": "x86_64-linux", "name": "tool", "output_kind": "app", "program_path": "bin/tool"},
            )
        ]
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        payload = res.to_dict()

        edge_triples = {(e["source_key"], e["kind"], e["target_key"]) for e in payload["edges"]}
        self.assertIn((app_tool, "exposes_script", script_tool), edge_triples)

    def test_s6_b03_nix_app_dynamic_and_escaping_program_paths(self) -> None:
        """Escaping program paths produce bounded placeholders and diagnostics."""
        app_key = k.nix_app_key("flake:default", "x86_64-linux", "escaping")
        placeholder = k.unknown_key("file", "repo-escaping-nix-app-program")

        obs = [
            RawObservation(
                kind="nix.app", source_id="flake.nix#app:escaping", path="flake.nix",
                name="escaping", target=app_key, confidence="extracted", extractor="repo-nix",
                extractor_version="0.1.0",
                metadata={"flake_ref": "flake:default", "system": "x86_64-linux", "name": "escaping", "output_kind": "app", "program_path": "../outside/bin/tool"},
            )
        ]
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        payload = res.to_dict()

        edge_triples = {(e["source_key"], e["kind"], e["target_key"]) for e in payload["edges"]}
        self.assertIn((app_key, "exposes_script", placeholder), edge_triples)
        diagnostics = [d for d in payload.get("diagnostics", []) if d.get("field") == "metadata.program_path"]
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0]["category"], "repo_escaping_path")
        self.assertEqual(diagnostics[0]["severity"], "warning")

    def test_s6_b04_nix_output_section_and_unregistered_section_diagnostics(self) -> None:
        """Registered sections create output nodes; unregistered sections emit warning diagnostics."""
        sec_reg_key = k.nix_output_key("file:flake.nix", "section/nixosModules")
        sec_custom_key = k.nix_output_key("file:flake.nix", "section/customSection")
        flake_file = k.file_key("flake.nix")

        obs = [
            RawObservation(
                kind="nix.output_section", source_id="flake.nix#sec:nixosModules", path="flake.nix",
                name="nixosModules", target=sec_reg_key, confidence="extracted", extractor="repo-nix",
                extractor_version="0.1.0", metadata={"section": "nixosModules"},
            ),
            RawObservation(
                kind="nix.output_section", source_id="flake.nix#sec:custom", path="flake.nix",
                name="customSection", target=sec_custom_key, confidence="extracted", extractor="repo-nix",
                extractor_version="0.1.0", metadata={"section": "customSection"},
            ),
        ]
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        payload = res.to_dict()

        nodes_by_key = {n["canonical_key"]: n for n in payload["nodes"]}
        self.assertIn(sec_reg_key, nodes_by_key)
        self.assertEqual(nodes_by_key[sec_reg_key]["metadata"]["identity_precision"], "section_category")

        edge_triples = {(e["source_key"], e["kind"], e["target_key"]) for e in payload["edges"]}
        self.assertIn((flake_file, "defines", sec_reg_key), edge_triples)

        diagnostics = payload.get("diagnostics", [])
        self.assertTrue(any(d.get("category") == "unregistered_nix_output_section" and d.get("severity") == "warning" for d in diagnostics))

    def test_s6_b05_nix_import_resolution_in_repo_and_escape_refusal(self) -> None:
        """In-repo imports source target files; escaping imports emit repo-escaping placeholder."""
        flake_file = k.file_key("flake.nix")
        in_repo_target = k.file_key("modules/base.nix")
        escape_placeholder = k.unknown_key("file", "repo-escaping-nix-import")
        dynamic_placeholder = k.dynamic_key("file", "path-expression")

        obs = [
            RawObservation(
                kind="nix.import", source_id="flake.nix#import:base", path="flake.nix",
                confidence="extracted", extractor="repo-nix", extractor_version="0.1.0",
                metadata={"resolved_path": "modules/base.nix"},
            ),
            RawObservation(
                kind="nix.import", source_id="flake.nix#import:escape", path="flake.nix",
                confidence="extracted", extractor="repo-nix", extractor_version="0.1.0",
                metadata={"resolved_path": "../outside.nix"},
            ),
            RawObservation(
                kind="nix.import", source_id="flake.nix#import:dyn", path="flake.nix",
                confidence="extracted", extractor="repo-nix", extractor_version="0.1.0",
                metadata={"dynamic_reason": "path-expression"},
            ),
        ]
        res = canonicalize_observations(obs)
        self.assertTrue(res.ok)
        payload = res.to_dict()

        edge_triples = {(e["source_key"], e["kind"], e["target_key"]) for e in payload["edges"]}
        self.assertIn((flake_file, "sources", in_repo_target), edge_triples)
        self.assertIn((flake_file, "sources", escape_placeholder), edge_triples)
        self.assertIn((flake_file, "sources", dynamic_placeholder), edge_triples)

        diagnostics = payload.get("diagnostics", [])
        self.assertTrue(any(d.get("category") == "repo_escaping_path" for d in diagnostics))
        self.assertTrue(any(d.get("category") == "dynamic_target" for d in diagnostics))

    def test_s6_b06_nix_flake_input_extraction_metadata(self) -> None:
        """Flake input extraction classifies fixed archive vs interpolated URLs and produces diagnostics."""
        content = """{
  inputs = {
    pkg_fixed.url = "https://example.com/archive-1.0.tar.gz";
    pkg_dynamic.url = "https://example.com/${version}/archive.tar.gz";
    nixpkgs.inputs.nixpkgs.follows = "nixpkgs";
  };
  outputs = { self, nixpkgs }: {};
}"""
        obs = list(nix.extract_nix_file_observations("flake.nix", content, flake_ref="flake:default"))
        self.assertTrue(obs)
        input_obs = {o.name: o for o in obs if o.kind == "nix.flake_input"}
        self.assertIn("pkg_fixed", input_obs)
        self.assertIn("pkg_dynamic", input_obs)
        self.assertEqual(input_obs["pkg_fixed"].metadata["source_type"], "tarball")
        self.assertEqual(input_obs["pkg_dynamic"].metadata["source_type"], "dynamic")
        self.assertTrue(input_obs["pkg_fixed"].metadata["has_url"])
        self.assertTrue(input_obs["pkg_dynamic"].metadata["has_url"])

        res = canonicalize_observations(list(input_obs.values()))
        self.assertTrue(res.ok)
        diagnostics = res.to_dict().get("diagnostics", [])
        self.assertTrue(any(d.get("category") == "unsupported_raw_observation_kind" and d.get("severity") == "warning" for d in diagnostics))

    def test_s6_b07_nix_multi_source_opaque_target_and_edge_metadata(self) -> None:
        """Validated multi-source non-exact relations construct deterministic opaque targets."""
        obs_eval = RawObservation(
            kind="nix.import", source_id="src-a:flake.nix#import:dep", path="flake.nix",
            confidence="extracted", extractor="repo-nix", extractor_version="0.1.0",
            metadata={"binding_id": "src-a", "snapshot_id": "snap-1", "resolution_outcome": "evaluation-dependent", "import_path": "./dep.nix"},
        )
        obs_div = RawObservation(
            kind="nix.import", source_id="src-b:flake.nix#import:divergent", path="flake.nix",
            confidence="extracted", extractor="repo-nix", extractor_version="0.1.0",
            metadata={"binding_id": "src-b", "snapshot_id": "snap-2", "resolution_outcome": "divergent", "import_path": "./divergent.nix"},
        )
        res = canonicalize_observations([obs_eval, obs_div])
        self.assertTrue(res.ok)
        payload = res.to_dict()
        node_keys = {n["canonical_key"] for n in payload["nodes"]}
        target_eval = next(k for k in node_keys if "evaluation-dependent" in k)
        target_div = next(k for k in node_keys if "divergent" in k)
        self.assertTrue(target_eval.startswith("dynamic:file:nix-cross-source-evaluation-dependent#"))
        self.assertTrue(target_div.startswith("unknown:file:nix-cross-source-divergent#"))

        edges = {e["target_key"]: e for e in payload["edges"]}
        self.assertIn(target_eval, edges)
        self.assertEqual(edges[target_eval]["kind"], "sources")
        self.assertEqual(edges[target_eval]["metadata"].get("resolution_outcome"), "evaluation-dependent")

    def test_s6_b08_nix_graph_storage_serialization_and_readback_integrity(self) -> None:
        """Roundtrip storage load row preparation preserves node and edge collections."""
        pkg_key = k.nix_package_key("flake:default", "x86_64-linux", "hello")
        app_key = k.nix_app_key("flake:default", "x86_64-linux", "hello")
        script_key = k.file_key("bin/hello")

        obs = [
            RawObservation(
                kind="nix.package", source_id="flake.nix#pkg:hello", path="flake.nix",
                name="hello", target=pkg_key, confidence="extracted", extractor="repo-nix",
                extractor_version="0.1.0",
                metadata={"flake_ref": "flake:default", "system": "x86_64-linux", "name": "hello", "output_kind": "package"},
            ),
            RawObservation(
                kind="nix.app", source_id="flake.nix#app:hello", path="flake.nix",
                name="hello", target=app_key, confidence="extracted", extractor="repo-nix",
                extractor_version="0.1.0",
                metadata={"flake_ref": "flake:default", "system": "x86_64-linux", "name": "hello", "output_kind": "app", "program_path": "bin/hello"},
            ),
        ]
        prep = prepare_canonical_load(obs, repository_scope="nix-test-repo")
        self.assertTrue(prep.result.ok)
        load_rows = canonical_rows_from_result(prep.result)

        row_node_keys = {node.canonical_key for node in load_rows.nodes}
        self.assertIn(pkg_key, row_node_keys)
        self.assertIn(app_key, row_node_keys)
        self.assertIn(script_key, row_node_keys)

        row_edge_pairs = {(edge.source_key, edge.edge_kind, edge.target_key) for edge in load_rows.edges}
        self.assertIn((app_key, "exposes_script", script_key), row_edge_pairs)
        self.assertTrue(len(load_rows.evidence) >= 2)
