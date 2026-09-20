"""Integration wave for multi-source Configuration and Shell canonical contracts.

Exercises:
1. Multi-source extraction and canonicalization across Nix, Terraform HCL/JSON,
   OpenAPI, Bash, Zsh, Awk, Bats, Zunit, and PowerShell.
2. Shell constructs, side-effect commands, traps, aliases, environment writes,
   and PowerShell module manifests.
3. Malformed config error handling and deterministic candidate recovery.
4. Selection policies, exclusion isolation, and sealed artifact verification.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.graph.multi_source_pipeline import capture_multi_source_candidate
from repomap_test_support.run25_wave2_corpus import (
    create_run25_wave2_graph_config,
    populate_run25_config_shell_project,
    restore_file_content,
    seal_and_verify_run25_artifacts,
)
from repomap_test_support.test_scratch import select_scratch_root


class Run25ConfigShellWaveIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(
            tempfile.mkdtemp(dir=select_scratch_root(), prefix="repomap-int-cfg-sh-")
        ).resolve()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_config_shell_multisource_pipeline_and_artifact_sealing(self) -> None:
        dirs = populate_run25_config_shell_project(self.tmpdir / "proj")
        graph_cfg = create_run25_wave2_graph_config(
            dirs["infra"], dirs["scripts"], graph_id="cfg-sh-wave"
        )

        # 1. Sealed artifact roundtrip & wire contract
        store_dir = self.tmpdir / "artifacts"
        manifest, reference, candidate_id = seal_and_verify_run25_artifacts(graph_cfg, store_dir)
        self.assertTrue(manifest.manifest_id.startswith("snapmanifest1:"))
        self.assertTrue(candidate_id.startswith("cand1:"))
        self.assertEqual(len(manifest.bindings), 2)
        self.assertGreater(manifest.total_files, 8)

        # 2. Multi-source extraction
        candidate = capture_multi_source_candidate(graph_cfg)
        self.assertGreater(len(candidate.observations), 50)

        observed_kinds = {obs.kind for obs in candidate.observations}
        for expected_kind in (
            "file", "nix.output_section", "terraform.file", "terraform.block",
            "terraform.required_version", "terraform.backend", "terraform.resource",
            "openapi.document", "openapi.path", "openapi.operation",
            "shell.script", "shell.function", "shell.command", "shell.source",
            "shell.export", "shell.env_write", "bash.trap", "bash.shell_option",
            "zsh.script", "zsh.zstyle", "awk.program", "awk.begin", "awk.end",
            "bats.file", "bats.test_case", "zunit.file",
            "powershell.script", "powershell.manifest", "powershell.command",
        ):
            self.assertIn(expected_kind, observed_kinds)

        # 3. Canonicalization
        can_res = canonicalize_observations(candidate.observations)
        self.assertTrue(can_res.ok, [d.message for d in can_res.diagnostics if d.severity == "error"])
        self.assertGreater(len(can_res.graph.nodes), 40)
        self.assertGreater(len(can_res.graph.edges), 30)

        node_keys = {node.canonical_key for node in can_res.graph.nodes}
        self.assertIn("file:primary/main.tf", node_keys)
        self.assertIn("file:primary/flake.nix", node_keys)
        self.assertIn("file:secondary/orchestrate.sh", node_keys)
        self.assertIn("bash.script:file%3Asecondary%2Forchestrate.sh", node_keys)
        self.assertIn("file:secondary/environment.zsh", node_keys)
        self.assertIn("zsh.script:file%3Asecondary%2Fenvironment.zsh", node_keys)
        self.assertIn("file:secondary/metrics.awk", node_keys)
        self.assertIn("awk.program:file%3Asecondary%2Fmetrics.awk", node_keys)
        self.assertIn("file:secondary/suite.bats", node_keys)
        self.assertIn("file:secondary/Wave2Module.psd1", node_keys)
        self.assertIn("file:secondary/deploy.ps1", node_keys)

        # 4. Deterministic edge relationships
        edge_triples = {(e.source_key, e.kind, e.target_key) for e in can_res.graph.edges}
        expected_triples = (
            ("file:secondary/orchestrate.sh", "defines", "bash.script:file%3Asecondary%2Forchestrate.sh"),
            ("file:secondary/environment.zsh", "defines", "zsh.script:file%3Asecondary%2Fenvironment.zsh"),
            ("file:secondary/metrics.awk", "defines", "awk.program:file%3Asecondary%2Fmetrics.awk"),
        )
        for triple in expected_triples:
            self.assertIn(triple, edge_triples)

        # 5. Evidence link attribution
        linked_edges = {link.edge_key for link in can_res.graph.edge_evidence_links}
        for edge in can_res.graph.edges:
            if (edge.source_key, edge.kind, edge.target_key) in expected_triples:
                self.assertIn(edge.edge_key, linked_edges)

    def test_shell_constructs_side_effects_and_mutations(self) -> None:
        dirs = populate_run25_config_shell_project(self.tmpdir / "proj")
        graph_cfg = create_run25_wave2_graph_config(dirs["infra"], dirs["scripts"])
        candidate = capture_multi_source_candidate(graph_cfg)

        # Verify command observations capturing side effects
        commands = [
            obs for obs in candidate.observations if obs.kind in ("shell.command", "powershell.command")
        ]
        self.assertGreater(len(commands), 5)
        command_names = {obs.name for obs in commands if obs.name}
        self.assertTrue(
            {"npm", "git", "aws", "gpg", "scp"} & command_names or
            any("npm" in str(c.metadata) or "aws" in str(c.metadata) for c in commands)
        )

        # Verify bash traps and environment writes
        traps = [obs for obs in candidate.observations if obs.kind == "bash.trap"]
        self.assertGreater(len(traps), 0)

        env_writes = [
            obs for obs in candidate.observations
            if obs.kind in ("shell.env_write", "shell.export", "powershell.env_write")
        ]
        self.assertGreater(len(env_writes), 0)
        env_vars = {obs.name for obs in env_writes if obs.name}
        self.assertTrue(
            {"DEPLOY_STAGE", "REGION", "EXECUTION_TIER"} & env_vars or
            any("DEPLOY_STAGE" in str(e.metadata) for e in env_writes)
        )

        # Verify PowerShell manifest exports
        pwsh_manifest_obs = [
            obs for obs in candidate.observations if obs.kind.startswith("powershell.manifest")
        ]
        self.assertGreater(len(pwsh_manifest_obs), 0)

        # Verify Awk blocks
        awk_blocks = [obs for obs in candidate.observations if obs.kind.startswith("awk.")]
        awk_kinds = {obs.kind for obs in awk_blocks}
        self.assertTrue({"awk.program", "awk.begin", "awk.end"} <= awk_kinds)

    def test_config_shell_malformed_recovery_and_tamper_detection(self) -> None:
        dirs = populate_run25_config_shell_project(self.tmpdir / "proj")
        infra = dirs["infra"]
        tf_json_file = infra / "terraform.tf.json"

        # 1. Tamper terraform.tf.json with invalid syntax
        orig_json = tf_json_file.read_text(encoding="utf-8")
        tf_json_file.write_text("{ unquoted_invalid_json: true \n", encoding="utf-8")

        graph_cfg = create_run25_wave2_graph_config(infra, dirs["scripts"])
        cand_tampered = capture_multi_source_candidate(graph_cfg)
        parse_errs = [
            obs for obs in cand_tampered.observations
            if obs.path == "primary/terraform.tf.json" and obs.kind == "config.parse_error"
        ]
        self.assertGreater(len(parse_errs), 0)

        # 2. Repair and verify recovery
        restore_file_content(tf_json_file, orig_json)
        cand_repaired = capture_multi_source_candidate(graph_cfg)
        self.assertNotEqual(
            cand_tampered.source_generation, cand_repaired.source_generation
        )

        repaired_errs = [
            obs for obs in cand_repaired.observations
            if obs.path == "primary/terraform.tf.json" and obs.kind == "config.parse_error"
        ]
        self.assertEqual(len(repaired_errs), 0)

        # 3. Tamper OpenAPI spec and verify recovery
        openapi_file = infra / "openapi.yaml"
        orig_openapi = openapi_file.read_text(encoding="utf-8")
        openapi_file.write_text("openapi: [malformed array instead of string\n", encoding="utf-8")

        cand_openapi_tampered = capture_multi_source_candidate(graph_cfg)
        openapi_errs = [
            obs for obs in cand_openapi_tampered.observations
            if obs.path == "primary/openapi.yaml" and obs.kind == "config.parse_error"
        ]
        self.assertGreater(len(openapi_errs), 0)

        restore_file_content(openapi_file, orig_openapi)
        cand_openapi_repaired = capture_multi_source_candidate(graph_cfg)
        repaired_openapi_errs = [
            obs for obs in cand_openapi_repaired.observations
            if obs.path == "primary/openapi.yaml" and obs.kind == "config.parse_error"
        ]
        self.assertEqual(len(repaired_openapi_errs), 0)

    def test_config_shell_exclusion_policy_and_candidate_invariance(self) -> None:
        dirs = populate_run25_config_shell_project(self.tmpdir / "proj")
        infra, scripts = dirs["infra"], dirs["scripts"]

        # 1. Exclude PowerShell and deploy script from scripts binding
        excludes = ("deploy.ps1", "Wave2Module.*")
        graph_cfg = create_run25_wave2_graph_config(
            infra, scripts, exclude_secondary=excludes
        )
        candidate1 = capture_multi_source_candidate(graph_cfg)

        obs_paths = {obs.path for obs in candidate1.observations}
        self.assertNotIn("secondary/deploy.ps1", obs_paths)
        self.assertNotIn("secondary/Wave2Module.psd1", obs_paths)
        self.assertIn("secondary/orchestrate.sh", obs_paths)

        # 2. Mutate excluded file and confirm candidate invariance
        (scripts / "deploy.ps1").write_text("# Mutated script\nWrite-Host 'ignored'\n", encoding="utf-8")
        candidate2 = capture_multi_source_candidate(graph_cfg)

        self.assertEqual(candidate1.source_generation, candidate2.source_generation)
        self.assertEqual(candidate1.candidate.candidate_id, candidate2.candidate.candidate_id)
        self.assertEqual(candidate1.observations, candidate2.observations)


if __name__ == "__main__":
    raise SystemExit("Integration execution requires canonical sandbox admission")
