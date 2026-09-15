import json
import tempfile
from pathlib import Path

from repomap_kg.extractors.config.nix import resolve_repo_path
from repomap_kg.observations import RawObservation, write_observations_jsonl
from repomap_test_support.cli_integration import CliIntegrationTestCase


class CliDiscoverShellProfilesIntegrationTests(CliIntegrationTestCase):
    def test_nix_repo_path_resolution_contract(self):
        self.assertEqual(resolve_repo_path("flake.nix", "${self}/bin/tool"), "bin/tool")
        self.assertEqual(resolve_repo_path("modules/base.nix", "../lib/shared.nix"), "lib/shared.nix")
        self.assertIsNone(resolve_repo_path("flake.nix", "pkgs.hello"))

    def test_discover_command_emits_shell_source_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            self.write_fixture(fixture / "bin" / "tool", "#!/usr/bin/env bash\nsource ../lib/common.sh\n")
            self.write_fixture(fixture / "lib" / "common.sh", "echo common\n")
            exit_code, stdout, stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")

        observations = [json.loads(line) for line in stdout.splitlines()]
        sources = [o for o in observations if o["kind"] == "shell.source"]
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(len(sources), 1)
        s0 = sources[0]
        self.assertEqual(s0["path"], "bin/tool")
        self.assertEqual(s0["source_id"], "bin/tool#source:2:lib-common-sh")
        self.assertEqual(s0["name"], "../lib/common.sh")
        self.assertEqual(s0["target"], "file:lib/common.sh")
        self.assertEqual(s0["start_line"], 2)
        self.assertEqual(s0["metadata"]["resolved_path"], "lib/common.sh")

    def test_discover_command_skips_dynamic_shell_source_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            self.write_fixture(fixture / "bin" / "tool", '#!/bin/sh\nFOO=bar\nsource "$DYNAMIC"\nif true; then\n  echo ok\nfi\n')
            exit_code, stdout, stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")

        observations = [json.loads(line) for line in stdout.splitlines()]
        sources = [o for o in observations if o["kind"] == "shell.source"]
        commands = [o for o in observations if o["kind"] == "shell.command"]
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(sources, [])
        self.assertEqual([command["name"] for command in commands], ["echo ok"])

    def test_discover_command_emits_shell_env_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            self.write_fixture(fixture / "bin" / "tool", '#!/bin/sh\nPATH="$PWD/bin:$PATH"\nFOO=bar nix build .#checks\necho "$PATH"\n')
            exit_code, stdout, stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")

        observations = [json.loads(line) for line in stdout.splitlines()]
        env = [o for o in observations if o["kind"] == "shell.env"]
        commands = [o for o in observations if o["kind"] == "shell.command"]
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            [(o["metadata"]["operation"], o["name"]) for o in env],
            [("write", "PATH"), ("read", "PWD"), ("read", "PATH"), ("write", "FOO"), ("read", "PATH")],
        )
        self.assertEqual(env[0]["source_id"], "bin/tool#env-write:2:path")
        self.assertEqual(env[0]["target"], "env:PATH")
        self.assertEqual(env[0]["metadata"]["scope"], "shell")
        self.assertEqual(env[3]["metadata"]["scope"], "command")
        self.assertEqual([command["name"] for command in commands], ["nix build", "echo $PATH"])

    def test_discover_command_handles_ambiguous_shell_env_and_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            script = '#!/bin/sh\nsource\nsource ../../outside.sh\nsource "$DYNAMIC"\necho "$PATH:${PATH:-/bin}:$PATH"\nnix --version\necho "unterminated\n'
            self.write_fixture(fixture / "bin" / "tool", script)
            exit_code, stdout, stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")

        observations = [json.loads(line) for line in stdout.splitlines()]
        sources = [o for o in observations if o["kind"] == "shell.source"]
        env = [o for o in observations if o["kind"] == "shell.env"]
        commands = [o for o in observations if o["kind"] == "shell.command"]
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(sources, [])
        self.assertEqual([(o["metadata"]["operation"], o["name"]) for o in env], [("read", "DYNAMIC"), ("read", "PATH")])
        self.assertEqual([command["name"] for command in commands], ["echo $PATH:${PATH:-/bin}:$PATH", "nix"])

    def test_discover_command_emits_shell_host_mutation_observations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            maintain = (
                '#!/bin/sh\nbrew install postgresql\nnix profile install nixpkgs#ripgrep\n'
                'sudo launchctl bootout system/com.example.agent\ndarwin-rebuild switch --flake ~/.flakes/nix-darwin\n'
                'sudo rm -rf /Library/Caches/example\nmv build/tool /usr/local/bin/tool\n'
                'cp scripts/tool ~/.local/bin/tool\nrm build/output\ncp /etc/hosts ./hosts.copy\nnix build .#checks\n'
            )
            self.write_fixture(fixture / "scripts" / "maintain.sh", maintain)
            exit_code, stdout, stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")

        observations = [json.loads(line) for line in stdout.splitlines()]
        mutations = [o for o in observations if o["kind"] == "shell.host_mutation"]
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            [(o["name"], o["target"], o["metadata"]["privileged"]) for o in mutations],
            [
                ("brew install", "host:package-management", False),
                ("nix profile install", "host:package-management", False),
                ("launchctl bootout", "host:service-management", True),
                ("darwin-rebuild switch", "host:system-activation", False),
                ("rm", "host:filesystem-mutation", True),
                ("mv", "host:filesystem-mutation", False),
                ("cp", "host:filesystem-mutation", False),
            ],
        )
        self.assertEqual(mutations[2]["metadata"]["effective_argv"], ["launchctl", "bootout", "system/com.example.agent"])
        self.assertEqual(mutations[4]["metadata"]["effective_argv"], ["rm", "-rf", "/Library/Caches/example"])

    def test_discover_command_applies_project_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            profile_path = Path(tmpdir) / "repomap-profile.toml"
            self.write_fixture(fixture / "ops" / "ship", "#!/usr/bin/env bash\n")
            self.write_fixture(fixture / "scripts" / "repair.sh", "#!/usr/bin/env bash\n")
            self.write_fixture(fixture / "out" / "manifest.json", "{}\n")
            self.write_fixture(fixture / "README.md", "# Fixture\n")
            profile_path.write_text('command_dirs = ["ops"]\nscript_dirs = ["scripts"]\ngenerated_dirs = ["out"]\n\n[role_overrides]\n"README.md" = "config"\n\n[confidence_overrides]\n"README.md" = "manual"\n')
            exit_code, stdout, stderr = self.run_module_entrypoint("discover", str(fixture), "--profile", str(profile_path), "--jsonl")

        observations = [json.loads(line) for line in stdout.splitlines()]
        file_observations = [o for o in observations if o["kind"] == "file"]
        by_path = {o["path"]: o for o in file_observations}
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(by_path["ops/ship"]["metadata"]["role"], "entrypoint")
        self.assertEqual(by_path["scripts/repair.sh"]["metadata"]["role"], "script")
        self.assertEqual(by_path["out/manifest.json"]["metadata"]["role"], "generated")
        self.assertTrue(by_path["out/manifest.json"]["metadata"]["generated"])
        self.assertEqual(by_path["README.md"]["metadata"]["role"], "config")
        self.assertEqual(by_path["README.md"]["confidence"], "manual")

    def test_files_command_prints_filtered_table_from_discovery_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            self.write_fixture(fixture / "README.md", "# Fixture\n")
            self.write_fixture(fixture / "src" / "main" / "python" / "app.py", "print('ok')\n")
            self.write_fixture(fixture / "generated" / "report.json", "{}\n")

            d_exit, d_stdout, d_stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")
            raw_jsonl.write_text(d_stdout)
            exit_code, stdout, stderr = self.run_module_entrypoint("files", str(raw_jsonl), "--role", "source", "--language", "python")

        self.assertEqual(d_exit, 0, d_stderr)
        self.assertEqual(exit_code, 0)
        self.assertIn("path", stdout)
        self.assertIn("src/main/python/app.py", stdout)
        self.assertNotIn("README.md", stdout)
        self.assertNotIn("generated/report.json", stdout)
        self.assertEqual(stderr, "")

    def test_files_command_accepts_stdin_jsonl_as_json(self):
        obs = RawObservation(
            kind="file", source_id="README.md", path="README.md", confidence="manual",
            extractor="fixture-discovery", extractor_version="0.1.0",
            metadata={"language": "markdown", "role": "documentation", "content_hash": "0" * 64, "generated": False, "executable": False},
        )
        result = self.run_cli("files", "-", "--json", input_text=obs.to_json_line())
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload[0]["path"], "README.md")
        self.assertEqual(payload[0]["confidence"], "manual")
        self.assertEqual(result.stderr, "")

    def test_entrypoints_command_prints_profile_command_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            profile_path = Path(tmpdir) / "repomap-profile.toml"
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            self.write_fixture(fixture / "ops" / "ship", "#!/usr/bin/env bash\n")
            self.write_fixture(fixture / "scripts" / "repair.sh", "#!/usr/bin/env bash\n")
            profile_path.write_text('command_dirs = ["ops"]\nscript_dirs = ["scripts"]\n')
            d_exit, d_stdout, d_stderr = self.run_module_entrypoint("discover", str(fixture), "--profile", str(profile_path), "--jsonl")
            raw_jsonl.write_text(d_stdout)
            exit_code, stdout, stderr = self.run_module_entrypoint("entrypoints", str(raw_jsonl))

        self.assertEqual(d_exit, 0, d_stderr)
        self.assertEqual(exit_code, 0)
        self.assertIn("ops/ship", stdout)
        self.assertIn("entrypoint", stdout)
        self.assertNotIn("scripts/repair.sh", stdout)
        self.assertEqual(stderr, "")

    def test_entrypoints_command_accepts_stdin_jsonl_as_json(self):
        obs = RawObservation(
            kind="file", source_id="bin/tool", path="bin/tool", confidence="manual",
            extractor="fixture-discovery", extractor_version="0.1.0",
            metadata={"language": "shell", "role": "entrypoint", "content_hash": "0" * 64, "generated": False, "executable": True},
        )
        result = self.run_cli("entrypoints", "-", "--json", input_text=obs.to_json_line())
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload[0]["path"], "bin/tool")
        self.assertEqual(payload[0]["confidence"], "manual")
        self.assertEqual(result.stderr, "")

    def test_host_mutators_command_prints_discovered_mutations_as_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            script = '#!/bin/sh\nbrew install postgresql\nsudo launchctl bootout system/com.example.agent\nnix build .#checks\n'
            self.write_fixture(fixture / "scripts" / "maintain.sh", script)
            d_exit, d_stdout, d_stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")
            raw_jsonl.write_text(d_stdout)
            exit_code, stdout, stderr = self.run_module_entrypoint("host-mutators", str(raw_jsonl), "--category", "service-management", "--tool", "launchctl", "--json")

        payload = json.loads(stdout)
        self.assertEqual(d_exit, 0, d_stderr)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual([(r["name"], r["target"]) for r in payload], [("launchctl bootout", "host:service-management")])
        self.assertEqual(payload[0]["effective_argv"], ["launchctl", "bootout", "system/com.example.agent"])

    def test_host_mutators_summary_command_prints_discovered_counts_as_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture = Path(tmpdir) / "fixture-repo"
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            script = '#!/bin/sh\nbrew install postgresql\nsudo launchctl bootout system/com.example.agent\nnix build .#checks\n'
            self.write_fixture(fixture / "scripts" / "maintain.sh", script)
            d_exit, d_stdout, d_stderr = self.run_module_entrypoint("discover", str(fixture), "--jsonl")
            raw_jsonl.write_text(d_stdout)
            exit_code, stdout, stderr = self.run_module_entrypoint("host-mutators-summary", str(raw_jsonl), "--json")

        payload = json.loads(stdout)
        self.assertEqual(d_exit, 0, d_stderr)
        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(payload, [
            {"category": "package-management", "count": 1, "privileged_count": 0, "tool": "brew"},
            {"category": "service-management", "count": 1, "privileged_count": 1, "tool": "launchctl"},
        ])

    def test_host_mutators_summary_command_prints_raw_jsonl_as_table(self):
        obs1 = RawObservation(
            kind="shell.host_mutation", source_id="scripts/maintain.sh#host-mutation:2:package",
            path="scripts/maintain.sh", start_line=2, end_line=2, name="brew install",
            target="host:package-management", confidence="heuristic", extractor="fixture-shell",
            extractor_version="0.1.0",
            metadata={"argv": ["brew", "install", "postgresql"], "category": "package-management", "effective_argv": ["brew", "install", "postgresql"], "privileged": False, "reason": "brew install", "tool": "brew"},
        )
        obs2 = RawObservation(
            kind="shell.host_mutation", source_id="scripts/maintain.sh#host-mutation:3:service",
            path="scripts/maintain.sh", start_line=3, end_line=3, name="launchctl bootout",
            target="host:service-management", confidence="heuristic", extractor="fixture-shell",
            extractor_version="0.1.0",
            metadata={"argv": ["sudo", "launchctl", "bootout", "system/example"], "category": "service-management", "effective_argv": ["launchctl", "bootout", "system/example"], "privileged": True, "reason": "launchctl bootout", "tool": "launchctl"},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([obs1, obs2], raw_jsonl)
            exit_code, stdout, stderr = self.run_module_entrypoint("host-mutators-summary", str(raw_jsonl))

        self.assertEqual(exit_code, 0)
        for expected in ("category", "privileged_count", "package-management", "service-management", "launchctl"):
            self.assertIn(expected, stdout)
        self.assertEqual(stderr, "")

    def test_host_mutators_command_prints_raw_jsonl_as_table(self):
        obs = RawObservation(
            kind="shell.host_mutation", source_id="scripts/maintain.sh#host-mutation:2:package",
            path="scripts/maintain.sh", start_line=2, end_line=2, name="brew install",
            target="host:package-management", confidence="heuristic", extractor="fixture-shell",
            extractor_version="0.1.0",
            metadata={"argv": ["brew", "install", "postgresql"], "category": "package-management", "effective_argv": ["brew", "install", "postgresql"], "privileged": False, "reason": "brew install", "tool": "brew"},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([obs], raw_jsonl)
            exit_code, stdout, stderr = self.run_module_entrypoint("host-mutators", str(raw_jsonl))

        self.assertEqual(exit_code, 0)
        for expected in ("path", "category", "package-management", "brew install"):
            self.assertIn(expected, stdout)
        self.assertEqual(stderr, "")
