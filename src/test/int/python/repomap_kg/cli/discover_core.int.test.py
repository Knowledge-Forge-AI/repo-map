import json
import shutil
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[6]
from repomap_test_support.cli_integration import CliIntegrationTestCase


class CliDiscoverCoreIntegrationTests(CliIntegrationTestCase):
    def test_discover_command_emits_file_observations_for_fixture_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            self.write_fixture(fixture / "bin" / "tool", "#!/usr/bin/env bash\nnix build .#checks\n")
            (fixture / "bin" / "tool").chmod((fixture / "bin" / "tool").stat().st_mode | 0o111)
            self.write_fixture(fixture / "src" / "main" / "python" / "app.py", "print('ok')\n")
            self.write_fixture(fixture / "src" / "test" / "unit" / "python" / "app.unit.test.py", "import unittest\n")
            self.write_fixture(fixture / "flake.nix", "{ outputs = _: {}; }\n")
            self.write_fixture(fixture / "generated" / "report.json", "{}\n")
            self.write_fixture(fixture / ".git" / "config", "ignored\n")

            exit_code, stdout, stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")

        observations = [json.loads(line) for line in stdout.splitlines()]
        file_observations = [o for o in observations if o["kind"] == "file"]
        shell_observations = [o for o in observations if o["kind"] == "shell.command"]
        paths = [o["path"] for o in file_observations]
        metadata_by_path = {o["path"]: o["metadata"] for o in file_observations}

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(paths, ["bin/tool", "flake.nix", "generated/report.json", "src/main/python/app.py", "src/test/unit/python/app.unit.test.py"])
        self.assertEqual(len(shell_observations), 1)
        so = shell_observations[0]
        self.assertEqual(so["path"], "bin/tool")
        self.assertEqual(so["source_id"], "bin/tool#call:2:nix-build")
        self.assertEqual(so["name"], "nix build")
        self.assertEqual(so["target"], "tool:nix")
        self.assertEqual((so["start_line"], so["end_line"], so["confidence"]), (2, 2, "heuristic"))
        self.assertNotIn(".git/config", paths)
        self.assertEqual(metadata_by_path["bin/tool"]["language"], "shell")
        self.assertEqual(metadata_by_path["bin/tool"]["role"], "entrypoint")
        self.assertTrue(metadata_by_path["bin/tool"]["executable"])
        self.assertEqual(metadata_by_path["flake.nix"]["language"], "nix")
        self.assertEqual(metadata_by_path["flake.nix"]["role"], "config")
        self.assertEqual(metadata_by_path["generated/report.json"]["role"], "generated")
        self.assertEqual(metadata_by_path["src/main/python/app.py"]["role"], "source")
        self.assertEqual(metadata_by_path["src/test/unit/python/app.unit.test.py"]["role"], "test")

    def test_discover_command_emits_nix_static_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "nix-fixture"
            self.write_fixture(fixture / "bin" / "tool", "#!/usr/bin/env bash\n")
            self.write_fixture(fixture / "bin" / "to-string-tool", "#!/usr/bin/env bash\n")
            self.write_fixture(fixture / "bin" / "literal-tool", "#!/usr/bin/env bash\n")
            self.write_fixture(fixture / "modules" / "base.nix", "{ ... }: {}\n")
            self.write_fixture(fixture / "pkgs" / "default.nix", "{ stdenv }: {}\n")
            self.write_fixture(fixture / "README.md", "Fixture docs\n")
            self.write_fixture(fixture / "config" / "settings.json", "{}\n")
            self.write_fixture(
                fixture / "flake.nix",
                (
                    "{ self }:\n{\n"
                    "  imports = [ (import ./modules/base.nix) ./README.md ];\n"
                    "  apps.aarch64-darwin.tool = { program = \"${self}/bin/tool\"; };\n"
                    "  apps.aarch64-darwin.toStringTool = { program = toString ./bin/to-string-tool; };\n"
                    "  apps.aarch64-darwin.literalTool = { program = ./bin/literal-tool; };\n"
                    "  apps.aarch64-darwin.noProgram = { type = \"app\"; };\n"
                    "  packages.aarch64-darwin.default = ./pkgs/default.nix;\n"
                    "  devShells.aarch64-darwin.default = {};\n"
                    "  checks.aarch64-darwin.unit = {};\n"
                    "  root = ./.;\n"
                    "  scripts = [ ./config/settings.json ];\n"
                    "}\n"
                ),
            )
            exit_code, stdout, stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")

        observations = [json.loads(line) for line in stdout.splitlines()]
        nix_observations = [o for o in observations if o["kind"].startswith("nix.")]
        targeted_nix_observations = [o for o in nix_observations if "target" in o]
        kinds_and_targets = [(o["kind"], o["target"]) for o in targeted_nix_observations]
        app = next(o for o in nix_observations if o["kind"] == "nix.app" and o["name"] == "tool")
        apps_by_name = {o["name"]: o for o in nix_observations if o["kind"] == "nix.app"}
        path_refs = [o for o in nix_observations if o["kind"] == "nix.path_ref"]
        output_sections = [o for o in nix_observations if o["kind"] == "nix.output_section"]

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        for item in (
            ("nix.import", "file:modules/base.nix"),
            ("nix.app", "nix.app:nix-fixture:aarch64-darwin:tool"),
            ("nix.package", "nix.package:nix-fixture:aarch64-darwin:default"),
            ("nix.devShell", "nix.devShell:nix-fixture:aarch64-darwin:default"),
            ("nix.check", "nix.check:nix-fixture:aarch64-darwin:unit"),
        ):
            self.assertIn(item, kinds_and_targets)
        self.assertEqual(app["metadata"]["program_path"], "bin/tool")
        self.assertEqual(app["metadata"]["program_resolution"], "local")
        self.assertEqual(apps_by_name["toStringTool"]["metadata"]["program_path"], "bin/to-string-tool")
        self.assertEqual(apps_by_name["literalTool"]["metadata"]["program_path"], "bin/literal-tool")
        self.assertNotIn("program", apps_by_name["noProgram"]["metadata"])
        self.assertEqual([o["target"] for o in path_refs], ["file:README.md", "file:pkgs/default.nix", "file:.", "file:config/settings.json"])
        self.assertEqual({o["metadata"]["section"] for o in output_sections}, {"apps", "packages", "devShells", "checks"})
        self.assertTrue(all(o["metadata"]["shape"] == "direct_assignment" for o in output_sections))

    def test_discover_command_emits_nix_unknown_and_dynamic_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "nix-fixture"
            self.write_fixture(
                fixture / "flake.nix",
                (
                    "{ self, name, pkgs }:\n{\n"
                    "  escaped = import ../outside.nix;\n"
                    "  apps.aarch64-darwin.dynamic = { program = \"${self}/${name}\"; };\n"
                    "  apps.aarch64-darwin.external = { program = pkgs.hello + \"/bin/hello\"; };\n"
                    "  apps.aarch64-darwin.bad = { program = ../outside/tool; };\n"
                    "  apps.aarch64-darwin.selfBad = { program = \"${self}/../outside/tool\"; };\n"
                    "  scripts = [ ../outside/resource ];\n"
                    "}\n"
                ),
            )
            exit_code, stdout, stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")

        observations = [json.loads(line) for line in stdout.splitlines()]
        nix_observations = [o for o in observations if o["kind"].startswith("nix.")]
        imports = [o for o in nix_observations if o["kind"] == "nix.import"]
        apps_by_name = {o["name"]: o for o in nix_observations if o["kind"] == "nix.app"}
        path_refs = [o for o in nix_observations if o["kind"] == "nix.path_ref"]

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(imports[0]["target"], "unknown:file:repo-escaping-nix-import")
        self.assertEqual(apps_by_name["dynamic"]["metadata"]["program_resolution"], "dynamic")
        self.assertEqual(apps_by_name["dynamic"]["metadata"]["dynamic_reason"], "nix-app-program-interpolation")
        self.assertEqual(apps_by_name["external"]["metadata"]["program_resolution"], "external")
        self.assertEqual(apps_by_name["bad"]["metadata"]["program_target"], "unknown:file:repo-escaping-nix-app-program")
        self.assertEqual(apps_by_name["bad"]["metadata"]["program_resolution"], "unknown")
        self.assertEqual(apps_by_name["selfBad"]["metadata"]["program_target"], "unknown:file:repo-escaping-nix-app-program")
        self.assertEqual(apps_by_name["selfBad"]["metadata"]["program_resolution"], "unknown")
        self.assertEqual([o["target"] for o in path_refs], ["unknown:file:repo-escaping-nix-path-ref"] * 3)

    def test_discover_command_emits_markdown_documentation_observations(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "discovery" / "markdown_docs_basic"
        with tempfile.TemporaryDirectory(prefix="repomap-markdown-discover-") as tmpdir:
            fixture_copy = Path(tmpdir) / "markdown_docs_basic"
            shutil.copytree(fixture, fixture_copy)
            readme = fixture_copy / "README.md"
            readme.write_text(
                readme.read_text(encoding="utf-8")
                + "\n[repo escape](../outside.md)\n"
                + "[absolute path](/public/docs/guide.md)\n",
                encoding="utf-8",
            )
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover", str(fixture_copy), "--jsonl"
            )

        self.assertEqual(exit_code, 0, stderr)
        observations = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        kinds = {o["kind"] for o in observations}
        links = [o for o in observations if o["kind"] == "markdown.link"]
        frontmatter = next(o for o in observations if o["kind"] == "markdown.frontmatter" and o["path"] == "README.md")

        self.assertTrue({
            "markdown.document",
            "markdown.heading",
            "markdown.link",
            "markdown.frontmatter",
            "markdown.code_fence",
            "markdown.adr_metadata",
            "markdown.skill_metadata",
        }.issubset(kinds))
        self.assertIn("api_key", frontmatter["metadata"]["redacted_keys"])
        self.assertIn(
            "doc.section:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md:decision",
            {item.get("target") for item in links},
        )
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {item.get("target") for item in links},
        )
        self.assertIn(
            "unknown:file:repo-escaping-markdown-link",
            {
                item["target"]
                for item in links
                if item["metadata"]["raw_target"] == "../outside.md"
            },
        )
        self.assertIn(
            "unknown:doc.page:missing-markdown-link-target",
            {
                item["target"]
                for item in links
                if item["metadata"]["raw_target"] == "/public/docs/guide.md"
            },
        )

    def test_discover_command_emits_json_family_config_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            mcp_json = {
                "projects": {"repo-map": {"root_path": "./projects/repo-map", "pg_database": "repomap_repo_map"}},
                "mcp_servers": {
                    "repomap": {
                        "command": "repomap-kg", "args": ["python3", "-m", "repomap_kg"],
                        "program": "repomap-kg --serve", "executable": "bin/tool",
                        "env": {"REPOMAP_MCP_CONFIG": "$REPOMAP_MCP_CONFIG", "TOKEN": "cfg1-sensitive-token"},
                        "docs_url": "https://example.com/docs", "mailto": "mailto:dev@example.com",
                        "path": "../../outside.json", "absolute_path": "/tmp/external.json",
                        "template_path": "${PROJECT_ROOT}/config.json",
                    }
                },
                "items": [{"name": "alpha", "path": "./alpha.json"}],
                "array": ["one", "two"],
                "api_key": "cfg1-sensitive-api-key",
            }
            self.write_fixture(fixture / "mcp" / "config.json", json.dumps(mcp_json, sort_keys=True, indent=2) + "\n")
            self.write_fixture(
                fixture / "events.jsonl",
                f'{json.dumps({"event": "load", "command": "repomap-kg"})}\n{json.dumps(["array", "record"])}\n{{bad json\n',
            )
            self.write_fixture(
                fixture / "settings.jsonc",
                '{\n  // line comment\n  /* block comment */\n  "command": "repomap-kg",\n'
                '  "docs_url": "mailto:dev@example.com",\n  "note": "keep // inside string",\n'
                '  "block_note": "keep /* inside string */",\n  "quoted": "escaped \\\" quote",\n'
                '  "nested": {\n    "path": "./mcp/config.json",\n  },\n}\n',
            )
            self.write_fixture(fixture / "broken.jsonc", "{ /* unterminated block comment\n")
            self.write_fixture(fixture / "broken.json", "{bad json}\n")

            exit_code, stdout, stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")

        self.assertEqual(exit_code, 0, stderr)
        observations = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        kinds = {o["kind"] for o in observations}
        self.assertTrue({"config.document", "config.path", "config.reference", "config.jsonl_record", "config.parse_error"}.issubset(kinds))
        self.assertNotIn("cfg1-sensitive-token", stdout)
        self.assertNotIn("cfg1-sensitive-api-key", stdout)

        references = [o for o in observations if o["kind"] == "config.reference"]
        reference_targets = {o["target"] for o in references}
        self.assertTrue({
            "tool:repomap-kg", "tool:python3", "dynamic:tool:config-command-fragment",
            "unknown:tool:unknown-config-command", "env:REPOMAP_MCP_CONFIG", "env:TOKEN",
            "external.url:https%3A%2F%2Fexample.com%2Fdocs", "external.url:mailto%3Adev%40example.com",
            "file:mcp/config.json", "unknown:file:repo-escaping-config-reference",
            "external:file:absolute-config-reference", "dynamic:file:config-reference-expanded-from-variable",
        }.issubset(reference_targets))

        path_metadata = {
            o["metadata"]["pointer"]: o["metadata"]
            for o in observations
            if o["kind"] == "config.path" and o["path"] == "mcp/config.json"
        }
        self.assertTrue(path_metadata["/api_key"]["redacted"])
        self.assertEqual(path_metadata["/array"]["array_policy"], "summary-only")

        parse_errors = [o for o in observations if o["kind"] == "config.parse_error"]
        self.assertTrue({"malformed-json", "malformed-jsonl-line", "unsupported-jsonc-construct"}.issubset(
            {error["metadata"]["error_kind"] for error in parse_errors}
        ))
        jsonl_records = [o for o in observations if o["kind"] == "config.jsonl_record"]
        self.assertEqual([record["metadata"]["top_level_type"] for record in jsonl_records], ["object", "array"])

    def test_discover_command_emits_toml_config_observations_from_fixture(self):
        fixture = REPO_ROOT / "src" / "test" / "fixtures" / "discovery" / "config_toml_basic"
        exit_code, stdout, stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")

        self.assertEqual(exit_code, 0, stderr)
        observations = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        kinds = {o["kind"] for o in observations}
        self.assertTrue({"config.document", "config.path", "config.reference", "config.parse_error"}.issubset(kinds))
        self.assertNotIn("cfg2-sensitive-api-key", stdout)
        self.assertNotIn("cfg2-sensitive-token", stdout)

        toml_files = [o for o in observations if o["kind"] == "file" and o["metadata"]["language"] == "toml"]
        self.assertEqual([o["path"] for o in toml_files], ["bad.toml", "mcp/config.toml"])

        references = [o for o in observations if o["kind"] == "config.reference"]
        reference_targets = {o["target"] for o in references}
        self.assertTrue({
            "tool:python3", "tool:repomap-kg", "env:PYTHONPATH", "env:TOKEN",
            "file:src/main/python", "file:docs/guide.md", "file:projects/repo-map",
            "file:bin/tool", "external.url:https%3A%2F%2Fexample.com%2Fdocs",
        }.issubset(reference_targets))
        self.assertNotIn("tool:-m", reference_targets)

        path_metadata = {
            o["metadata"]["pointer"]: o["metadata"]
            for o in observations
            if o["kind"] == "config.path" and o["path"] == "mcp/config.toml"
        }
        self.assertTrue(path_metadata["/mcp_servers/repomap/api_key"]["redacted"])
        self.assertEqual(path_metadata["/tools"]["array_policy"], "stable-member-key")
        self.assertEqual(path_metadata["/anonymous"]["array_policy"], "summary-only")
        self.assertIn("/tools/repomap/command", path_metadata)
        self.assertIn("/tools/helper/command", path_metadata)
        self.assertNotIn("/tools/0/command", path_metadata)
        self.assertNotIn("/anonymous/0/command", path_metadata)

        parse_errors = [o for o in observations if o["kind"] == "config.parse_error"]
        self.assertIn("malformed-toml", {error["metadata"]["error_kind"] for error in parse_errors})

    def test_discover_command_profile_overrides_and_validation_refusal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "profile-fixture"
            self.write_fixture(
                fixture / "bin" / "custom_cmd",
                "#!/usr/bin/env bash\necho cmd\n",
            )
            (fixture / "bin" / "custom_cmd").chmod(
                (fixture / "bin" / "custom_cmd").stat().st_mode | 0o111
            )
            self.write_fixture(fixture / "docs" / "spec.txt", "specification text\n")
            self.write_fixture(fixture / "cache" / "cached.txt", "generated cache\n")
            self.write_fixture(
                fixture / "profile.toml",
                (
                    'command_dirs = ["bin"]\n'
                    'generated_dirs = ["cache"]\n'
                    '[role_overrides]\n'
                    '"docs/spec.txt" = "documentation"\n'
                    '[confidence_overrides]\n'
                    '"docs/spec.txt" = "manual"\n'
                ),
            )

            # 1. Valid profile overrides file metadata and preserves deterministic observations
            exit_code, stdout, stderr = self.run_module_entrypoint(
                "discover",
                str(fixture),
                "--profile",
                str(fixture / "profile.toml"),
                "--jsonl",
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr, "")
            observations = [
                json.loads(line) for line in stdout.splitlines() if line.strip()
            ]
            meta_by_path = {
                o["path"]: o["metadata"]
                for o in observations
                if o["kind"] == "file"
            }
            conf_by_path = {
                o["path"]: o["confidence"]
                for o in observations
                if o["kind"] == "file"
            }

            self.assertEqual(meta_by_path["bin/custom_cmd"]["role"], "entrypoint")
            self.assertTrue(meta_by_path["bin/custom_cmd"]["executable"])
            self.assertEqual(meta_by_path["docs/spec.txt"]["role"], "documentation")
            self.assertEqual(conf_by_path["docs/spec.txt"], "manual")
            self.assertEqual(meta_by_path["cache/cached.txt"]["role"], "generated")

            # 2. Non-jsonl discover summary output contract
            exit_sum, stdout_sum, stderr_sum = self.run_module_entrypoint(
                "discover",
                str(fixture),
                "--profile",
                str(fixture / "profile.toml"),
            )
            self.assertEqual(exit_sum, 0)
            self.assertEqual(stderr_sum, "")
            self.assertEqual(
                stdout_sum.strip(),
                f"discovered {len(observations)} observations",
            )

            # 3. Invalid profile refusal: non-list command_dirs rejected before discovery mutation
            self.write_fixture(
                fixture / "bad_profile.toml",
                'command_dirs = "not-a-list"\n',
            )
            before_refusal = {
                path.relative_to(fixture).as_posix(): path.read_bytes()
                for path in fixture.rglob("*") if path.is_file()
            }
            exit_bad, stdout_bad, stderr_bad = self.run_module_entrypoint(
                "discover",
                str(fixture),
                "--profile",
                str(fixture / "bad_profile.toml"),
                "--jsonl",
            )
            self.assertEqual(exit_bad, 1)
            self.assertEqual(stdout_bad, "")
            self.assertIn("command_dirs must be a list of strings", stderr_bad)
            self.assertEqual(before_refusal, {
                path.relative_to(fixture).as_posix(): path.read_bytes()
                for path in fixture.rglob("*") if path.is_file()
            })

