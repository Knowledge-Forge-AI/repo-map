import json
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[6]
from repomap_test_support.cli_integration import CliIntegrationTestCase


class CliDiscoverGoIntegrationTests(CliIntegrationTestCase):
    def test_discover_command_emits_static_go_metadata_as_jsonl(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "go"

        exit_code, stdout, stderr = self.run_module_entrypoint(
            "discover", str(fixture), "--jsonl"
        )

        self.assertEqual(exit_code, 0, stderr)
        observations = [
            json.loads(line) for line in stdout.splitlines() if line.strip()
        ]
        kinds = {observation["kind"] for observation in observations}
        self.assertTrue(
            {
                "go.file",
                "go.module",
                "go.module_require",
                "go.module_replace",
                "go.workspace",
                "go.workspace_use",
                "go.metadata_parse_error",
                "go.package",
                "go.import",
                "go.const",
                "go.var",
                "go.type",
                "go.type_alias",
                "go.function",
                "go.method",
                "go.receiver",
                "go.parameter",
                "go.result",
                "go.struct",
                "go.interface",
                "go.field",
                "go.embedded_field",
                "go.type_parameter",
                "go.constraint",
                "go.union_term",
                "go.reference",
                "go.selector",
                "go.call",
                "go.method_expression",
                "go.construct",
                "go.conversion",
                "go.type_assertion",
                "go.type_switch",
                "go.index",
                "go.slice",
                "go.map_access",
                "go.instantiation",
                "go.closure",
                "go.goroutine",
                "go.defer",
                "go.send",
                "go.receive",
                "go.select",
                "go.panic",
                "go.recover",
                "go.return",
                "go.break",
                "go.continue",
                "go.goto",
                "go.dynamic",
                "go.build_constraint",
                "go.generated_marker",
                "go.cgo",
                "go.assembly_companion",
                "go.test",
                "go.benchmark",
                "go.fuzz",
                "go.example",
                "go.test_main",
                "go.vendor_package",
            }.issubset(kinds)
        )
        package = next(
            observation
            for observation in observations
            if observation["kind"] == "go.package"
            and observation["path"].endswith("syntax_basic/declarations.go")
        )
        self.assertEqual(package["name"], "sample")
        self.assertGreater(package["end_line"], 0)
        self.assertNotIn("source", package["metadata"])
        exported = next(
            observation
            for observation in observations
            if observation["kind"] == "go.function"
            and observation.get("name") == "Exported"
        )
        self.assertEqual(exported["metadata"]["parameter_count"], 4)
        self.assertTrue(exported["metadata"]["variadic"])
        self.assertNotIn("signature", exported["metadata"])
        pair = next(
            observation
            for observation in observations
            if observation["kind"] == "go.struct"
            and observation.get("name") == "Pair"
        )
        self.assertEqual(pair["metadata"]["embedded_count"], 1)
        self.assertNotIn("type_text", pair["metadata"])
        generated = next(
            observation
            for observation in observations
            if observation["kind"] == "go.file"
            and observation["path"].endswith("zz_generated_test.go")
        )
        self.assertTrue(generated["metadata"]["generated"])
        self.assertNotIn("package direct", stdout)
        self.assertNotIn("fixture-key", stdout)
        self.assertNotIn("fixture-value", stdout)
        self.assertNotIn("fixture-panic", stdout)
        self.assertNotIn("REPO_MAP_FIXTURE", stdout)
        self.assertNotIn(str(fixture), stdout)

    def test_discover_syntax_malformed_emits_parse_error_without_helper_crash(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "go" / "syntax_malformed"

        exit_code, stdout, stderr = self.run_module_entrypoint(
            "discover", str(fixture), "--jsonl"
        )

        self.assertEqual(exit_code, 0, stderr)
        observations = [
            json.loads(line) for line in stdout.splitlines() if line.strip()
        ]
        kinds = {observation["kind"] for observation in observations}
        self.assertIn("go.parse_error", kinds)
        self.assertIn("go.package", kinds)
        self.assertIn("go.const", kinds)
        parse_error = next(
            obs for obs in observations if obs["kind"] == "go.parse_error"
        )
        self.assertEqual(parse_error["path"], "partial.go")
        self.assertEqual(parse_error["extractor"], "repo-go-ast")
        self.assertEqual(stderr, "")

    def test_discover_refuses_symlinks_pointing_outside_repository_root(self):
        import tempfile

        from repomap_test_support.test_scratch import select_scratch_root

        with tempfile.TemporaryDirectory(dir=select_scratch_root()) as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            outside_root = Path(tmpdir) / "outside"
            outside_root.mkdir()
            (outside_root / "secret.go").write_text(
                "package secret\nvar Token = 123\n", encoding="utf-8"
            )
            (repo_root / "main.go").write_text(
                "package main\nfunc Main() {}\n", encoding="utf-8"
            )
            (repo_root / "symlink_escape.go").symlink_to(outside_root / "secret.go")

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(repo_root), "--jsonl"
            )

            self.assertEqual(exit_code, 0, stderr)
            observations = [
                json.loads(line) for line in stdout.splitlines() if line.strip()
            ]
            paths = {obs["path"] for obs in observations}
            self.assertIn("main.go", paths)
            self.assertNotIn("symlink_escape.go", paths)
            self.assertNotIn("secret.go", paths)
            self.assertNotIn("Token", stdout)
            self.assertNotIn(str(outside_root), stdout)

    def test_discover_redaction_and_public_safe_output(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "go" / "syntax_basic"

        exit_code, stdout, stderr = self.run_module_entrypoint(
            "discover", str(fixture), "--jsonl"
        )

        self.assertEqual(exit_code, 0, stderr)
        observations = [
            json.loads(line) for line in stdout.splitlines() if line.strip()
        ]
        self.assertTrue(len(observations) > 0)
        for obs in observations:
            obs_path = Path(obs["path"])
            self.assertFalse(obs_path.is_absolute())
            self.assertNotIn("..", obs_path.parts)
        self.assertNotIn(str(fixture), stdout)
        self.assertNotIn(str(REPO_ROOT), stdout)
        self.assertEqual(stderr, "")

    def test_discover_fails_safely_for_explicit_missing_helper(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "go" / "syntax_basic"

        with patch.dict(
            "os.environ",
            {"REPOMAP_GO_HELPER": "/missing/repomap-go-extract"},
        ):
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture), "--jsonl"
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Go parser helper is unavailable", stderr)
        self.assertNotIn(str(fixture), stderr)

    def test_discover_go_workspace_and_module_replacement_hierarchy(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "go" / "workspace_basic"
        exit_code, stdout, stderr = self.run_module_entrypoint(
            "discover", str(fixture), "--jsonl"
        )

        self.assertEqual(exit_code, 0, stderr)
        observations = [
            json.loads(line) for line in stdout.splitlines() if line.strip()
        ]

        workspace = next(o for o in observations if o["kind"] == "go.workspace")
        self.assertEqual(workspace["path"], "go.work")
        self.assertEqual(workspace["name"], "go.work")
        self.assertEqual(workspace["metadata"]["directive"], "workspace")

        go_version = next(
            o for o in observations if o["kind"] == "go.workspace_go_version"
        )
        self.assertEqual(go_version["name"], "1.25")
        self.assertEqual(go_version["metadata"]["owner_workspace_path"], "go.work")

        toolchain = next(
            o for o in observations if o["kind"] == "go.workspace_toolchain"
        )
        self.assertEqual(toolchain["name"], "go1.25.3")

        use_obs = [o for o in observations if o["kind"] == "go.workspace_use"]
        self.assertEqual(
            [(o["name"], o["target"], o["metadata"]["resolved_under_root"]) for o in use_obs],
            [("app", "file:app", True), ("lib", "file:lib", True)],
        )

        replace_obs = next(
            o for o in observations if o["kind"] == "go.workspace_replace"
        )
        self.assertEqual(replace_obs["name"], "example.invalid/shared")
        self.assertEqual(replace_obs["target"], "file:lib")
        self.assertEqual(replace_obs["metadata"]["replacement_kind"], "local")

        modules = {
            o["path"]: o["name"] for o in observations if o["kind"] == "go.module"
        }
        self.assertEqual(
            modules,
            {"app/go.mod": "example.invalid/app", "lib/go.mod": "example.invalid/lib"},
        )
        self.assertNotIn(str(fixture), stdout)

    def test_discover_go_malformed_directive_recovery_and_preservation(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "go" / "malformed"
        exit_code, stdout, stderr = self.run_module_entrypoint(
            "discover", str(fixture), "--jsonl"
        )

        self.assertEqual(exit_code, 0, stderr)
        observations = [
            json.loads(line) for line in stdout.splitlines() if line.strip()
        ]

        parse_errors = [
            o for o in observations if o["kind"] == "go.metadata_parse_error"
        ]
        error_kinds = {o["metadata"]["error_kind"] for o in parse_errors}
        self.assertTrue({"invalid-quoting", "unterminated-block"}.issubset(error_kinds))

        recovered_module = next(
            o for o in observations if o["kind"] == "go.module"
        )
        self.assertEqual(recovered_module["name"], "example.invalid/recovered")
        self.assertEqual(recovered_module["path"], "go.mod")
        self.assertEqual(recovered_module["start_line"], 2)

        commented_require = next(
            o for o in observations if o["kind"] == "go.module_require"
        )
        self.assertEqual(commented_require["name"], "example.invalid/commented")
        self.assertEqual(
            commented_require["target"],
            "go.module-ref:example.invalid%2Fcommented@v0.5.0",
        )
        self.assertFalse(commented_require["metadata"]["indirect"])
        self.assertNotIn(str(fixture), stdout)


if __name__ == "__main__":
    import sys

    sys.exit(
        "Direct execution unsupported: RepoMap integration tests require container sandbox admission via pytest"
    )
