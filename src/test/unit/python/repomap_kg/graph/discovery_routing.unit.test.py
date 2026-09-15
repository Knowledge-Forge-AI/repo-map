from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repomap_kg.graph.discovery import discover_observations

FIXTURE_ROOT = Path(__file__).parents[4] / "fixtures" / "discovery"


class DiscoveryRoutingUnitTests(unittest.TestCase):
    def test_discover_observations_includes_shell_commands_for_shell_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            script = root / "bin" / "tool"
            self.write(script, "#!/usr/bin/env bash\nnix build .#checks\n")
            script.chmod(script.stat().st_mode | 0o111)

            observations = discover_observations(root)

        self.assertEqual(
            [observation.kind for observation in observations],
            [
                "file",
                "shell.command",
            ],
        )
        command = observations[1]
        self.assertEqual(command.path, "bin/tool")
        self.assertEqual(command.name, "nix build")
        self.assertEqual(command.target, "tool:nix")
        self.assertEqual(command.start_line, 2)

    def test_discover_observations_includes_powershell_structural_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "scripts" / "maintain.ps1",
                (
                    "#requires -Version 7.2\n"
                    "using module ../modules/Example.Module.psm1\n"
                    "param([string]$ApiToken = \"FAKE_TOKEN_VALUE\")\n"
                    "function Invoke-Thing { param([string]$Path) }\n"
                    "Import-Module Microsoft.PowerShell.Management\n"
                    ". ./helpers.ps1\n"
                    "& $Command\n"
                ),
            )

            observations = discover_observations(root)

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = {observation.kind for observation in observations}
        self.assertIn("powershell.script", kinds)
        self.assertIn("powershell.function", kinds)
        self.assertIn("powershell.param", kinds)
        self.assertIn("powershell.requires", kinds)
        self.assertIn("powershell.using_module", kinds)
        self.assertIn("powershell.import_module", kinds)
        self.assertIn("powershell.dot_source", kinds)
        self.assertIn("powershell.dynamic_invocation", kinds)
        self.assertIn("powershell.secret_like", kinds)
        self.assertNotIn("FAKE_TOKEN_VALUE", payload)

    def test_discover_observations_includes_nix_facts_for_nix_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            flake = root / "flake.nix"
            self.write(
                flake,
                (
                    "{ self }: {\n"
                    "  imports = [ ./module.nix ];\n"
                    "  apps.aarch64-darwin.tool = {\n"
                    "    program = \"${self}/bin/tool\";\n"
                    "  };\n"
                    "}\n"
                ),
            )
            self.write(root / "module.nix", "{ ... }: {}\n")

            observations = discover_observations(root)

        kinds = [observation.kind for observation in observations]
        self.assertIn("nix.import", kinds)
        self.assertIn("nix.app", kinds)
        app = next(item for item in observations if item.kind == "nix.app")
        self.assertEqual(app.metadata["flake_ref"], root.name)
        self.assertEqual(app.metadata["program_path"], "bin/tool")

    def test_discover_observations_includes_markdown_documentation_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "README.md",
                (
                    "# Fixture\n"
                    "\n"
                    "See [ADR](docs/adr/0008-markdown-documentation-graph-model.md#decision).\n"
                ),
            )
            self.write(
                root / "docs" / "adr" / "0008-markdown-documentation-graph-model.md",
                "# ADR 0008: Markdown Documentation Graph Model\n\n## Decision\n",
            )

            observations = discover_observations(root)

        kinds = [observation.kind for observation in observations]
        self.assertIn("markdown.document", kinds)
        self.assertIn("markdown.heading", kinds)
        self.assertIn("markdown.link", kinds)
        self.assertIn("markdown.adr_metadata", kinds)
        link = next(item for item in observations if item.kind == "markdown.link")
        self.assertEqual(
            link.target,
            "doc.section:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md:decision",
        )
        adr = next(item for item in observations if item.kind == "markdown.adr_metadata")
        self.assertEqual(adr.target, "doc.adr:0008")

    def test_discover_observations_includes_json_family_config_facts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "mcp" / "repo-map" / "config.json",
                '{"command": "repomap-kg", "api_key": "secret-value"}\n',
            )
            self.write(
                root / "events.jsonl",
                '{"event": "start"}\n{"event": \n{"path": "./mcp/repo-map/config.json"}\n',
            )
            self.write(
                root / "settings.jsonc",
                '{ // comment\n "url": "https://example.com/docs", }\n',
            )

            observations = discover_observations(root)

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = [observation.kind for observation in observations]

        self.assertNotIn("secret-value", payload)
        self.assertIn("config.document", kinds)
        self.assertIn("config.path", kinds)
        self.assertIn("config.reference", kinds)
        self.assertIn("config.jsonl_record", kinds)
        self.assertIn("config.parse_error", kinds)
        self.assertIn(".jsonl", {item.path[-6:] for item in observations})
        self.assertIn(".jsonc", {item.path[-6:] for item in observations})

    def test_discover_observations_routes_eml_and_mbox_files(self):
        observations = discover_observations(FIXTURE_ROOT / "mail_basic")
        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = {observation.kind for observation in observations}
        languages = {
            observation.path: observation.metadata.get("language")
            for observation in observations
            if observation.kind == "file"
        }

        self.assertEqual(languages["single-message.eml"], "eml")
        self.assertEqual(languages["sample.mbox"], "mbox")
        self.assertIn("email.message", kinds)
        self.assertIn("email.mailbox", kinds)
        self.assertIn("email.part", kinds)
        self.assertIn("email.attachment_stub", kinds)
        self.assertIn("email.thread_hint", kinds)
        self.assertNotIn("alice@example.invalid", payload)
        self.assertNotIn("fake-mail-reset-code", payload)

    def test_discover_observations_includes_yaml_config_facts(self):
        observations = discover_observations(FIXTURE_ROOT / "yaml_basic")

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = {observation.kind for observation in observations}
        yaml_documents = [
            observation
            for observation in observations
            if observation.kind == "config.document"
            and observation.metadata.get("format") == "yaml"
        ]
        yaml_references = [
            observation
            for observation in observations
            if observation.kind == "config.reference"
            and observation.metadata.get("format") == "yaml"
        ]
        profiles = {
            observation.metadata.get("profile")
            for observation in yaml_documents
        }

        self.assertIn("config.document", kinds)
        self.assertIn("config.path", kinds)
        self.assertIn("config.reference", kinds)
        self.assertIn("config.parse_error", kinds)
        self.assertIn("github_actions", profiles)
        self.assertIn("kubernetes", profiles)
        self.assertIn("openapi", profiles)
        self.assertIn("docker_compose", profiles)
        self.assertIn("generic_yaml", profiles)
        self.assertIn(
            "external:github.action:actions%2Fcheckout%40v4",
            {observation.target for observation in yaml_references},
        )
        self.assertIn(
            "external:docker.image:example%2Fapp%3Alatest",
            {observation.target for observation in yaml_references},
        )
        self.assertNotIn("fake-actions-token", payload)
        self.assertNotIn("fake-kubernetes-password", payload)
        self.assertNotIn("fake-client-secret", payload)

    def test_discover_observations_includes_terraform_hcl_profile_facts(self):
        fixture_root = Path(__file__).parents[4] / "fixtures" / "terraform_hcl" / "basic"

        observations = discover_observations(fixture_root)

        payload = "\n".join(item.to_json_line() for item in observations)
        kinds = {observation.kind for observation in observations}
        languages = {
            observation.path: observation.metadata.get("language")
            for observation in observations
            if observation.kind == "file"
        }

        self.assertEqual(languages["main.tf"], "terraform")
        self.assertEqual(languages["prod.tfvars"], "terraform")
        self.assertEqual(languages["terraform.tfvars"], "terraform")
        self.assertEqual(languages["dev.auto.tfvars"], "terraform")
        self.assertIn("terraform.file", kinds)
        self.assertIn("terraform.block", kinds)
        self.assertIn("terraform.resource", kinds)
        self.assertIn("terraform.module", kinds)
        self.assertIn("terraform.variable", kinds)
        self.assertIn("terraform.output", kinds)
        self.assertIn("terraform.reference", kinds)
        self.assertIn("terraform.import", kinds)
        self.assertIn("terraform.redaction", kinds)
        self.assertIn("terraform.parse_error", kinds)
        self.assertNotIn("fake-tfhcl-provider-secret", payload)
        self.assertNotIn("fake-tfhcl-module-secret", payload)
        self.assertNotIn("fake-tfhcl-prod-tfvars-secret", payload)
        self.assertNotIn("fake-tfhcl-tfvars-secret", payload)
        self.assertNotIn("fake-tfhcl-import-secret", payload)

    def test_discover_observations_includes_python_ecosystem_profile_facts(self):
        fixture_root = (
            Path(__file__).parents[4]
            / "fixtures"
            / "python_ecosystem"
            / "dogfood"
        )

        observations = discover_observations(fixture_root)

        kinds = {observation.kind for observation in observations}
        languages = {
            observation.path: observation.metadata.get("language")
            for observation in observations
            if observation.kind == "file"
        }

        self.assertEqual(languages["requirements.txt"], "python")
        self.assertEqual(languages["requirements-dev.txt"], "python")
        self.assertEqual(languages["pyproject.toml"], "toml")
        self.assertIn("python.package_file", kinds)
        self.assertIn("python.requirement", kinds)
        self.assertIn("python.pyproject", kinds)
        self.assertIn("python.build_system", kinds)
        self.assertIn("python.tool_config", kinds)
        self.assertIn("python.test_file", kinds)
        self.assertIn("python.unittest_case", kinds)
        self.assertIn("python.pytest_test", kinds)
        self.assertEqual(
            [
                observation
                for observation in observations
                if observation.kind == "python.parse_error"
                and observation.path.startswith("requirements")
            ],
            [],
        )

    def test_discover_observations_includes_ruby_facts_for_ruby_files_and_dsls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write(
                root / "lib" / "example.rb",
                (
                    'require_relative "example/service"\n'
                    "module Example\n"
                    "  class Runner\n"
                    "    def call\n"
                    "    end\n"
                    "  end\n"
                    "end\n"
                ),
            )
            self.write(root / "lib" / "example" / "service.rb", "module Example\nend\n")
            self.write(root / "Gemfile", 'source "https://example.invalid"\ngem "rack"\n')
            self.write(root / "Rakefile", 'desc "Run tests"\ntask :test do\nend\n')
            self.write(root / "Vagrantfile", 'Vagrant.configure("2") do |config|\n  config.vm.box = "example/box"\nend\n')
            shebang = root / "bin" / "tool"
            self.write(shebang, "#!/usr/bin/env ruby\nrequire_relative '../lib/example'\n")
            shebang.chmod(shebang.stat().st_mode | 0o111)

            observations = discover_observations(root)

        kinds = {observation.kind for observation in observations}
        ruby_profiles = {
            observation.metadata.get("profile")
            for observation in observations
            if observation.kind == "ruby.file"
        }
        ruby_targets = {
            observation.target
            for observation in observations
            if observation.kind == "ruby.reference"
        }

        self.assertIn("ruby.file", kinds)
        self.assertIn("ruby.module", kinds)
        self.assertIn("ruby.class", kinds)
        self.assertIn("ruby.method", kinds)
        self.assertIn("ruby.gem_dependency", kinds)
        self.assertIn("ruby.vagrant_config", kinds)
        self.assertIn("generic_ruby", ruby_profiles)
        self.assertIn("gemfile", ruby_profiles)
        self.assertIn("rake", ruby_profiles)
        self.assertIn("vagrantfile", ruby_profiles)
        self.assertIn("file:lib/example/service.rb", ruby_targets)
        self.assertIn("external:ruby-gem:rack", ruby_targets)

    def test_discover_observations_reads_ruby_basic_fixture(self):
        observations = discover_observations(FIXTURE_ROOT / "ruby_basic")
        kinds = {observation.kind for observation in observations}
        ruby_profiles = {
            observation.metadata.get("profile")
            for observation in observations
            if observation.kind == "ruby.file"
        }
        ruby_targets = {
            observation.target
            for observation in observations
            if observation.kind == "ruby.reference"
        }

        self.assertIn("ruby.module", kinds)
        self.assertIn("ruby.class", kinds)
        self.assertIn("ruby.route", kinds)
        self.assertIn("ruby.test_method", kinds)
        self.assertIn("ruby.gem_dependency", kinds)
        self.assertIn("ruby.vagrant_config", kinds)
        self.assertIn("sinatra", ruby_profiles)
        self.assertIn("hanami", ruby_profiles)
        self.assertIn("minitest", ruby_profiles)
        self.assertIn("file:lib/example/service.rb", ruby_targets)
        self.assertIn("external:ruby-gem:rack", ruby_targets)
        self.assertTrue(
            any(
                observation.metadata.get("redacted")
                for observation in observations
                if observation.path == "redaction.rb"
            )
        )

    def write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


if __name__ == "__main__":
    unittest.main()
