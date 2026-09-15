import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from repomap_kg.cli import main
from repomap_kg.observations.raw import RawObservation, write_observations_jsonl


class CliRawObservationCommandUnitTests(unittest.TestCase):
    def test_observations_normalize_prints_normalized_json(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="scripts/build.sh#call:nix-build",
            path="scripts/build.sh",
            start_line=21,
            end_line=21,
            name="nix-build",
            target="tool:nix",
            confidence="heuristic",
            extractor="shell-static",
            extractor_version="0.1.0",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([observation], jsonl_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    ["observations", "normalize", str(jsonl_path), "--json"]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["summary"]["raw_observations"], 1)
        self.assertEqual(payload["edges"][0]["dst_node_key"], "tool:nix")

    def test_files_prints_json_view(self):
        observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "markdown",
                "role": "documentation",
                "content_hash": "0" * 64,
                "generated": False,
                "executable": False,
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([observation], jsonl_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["files", str(jsonl_path), "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["path"], "README.md")
        self.assertEqual(payload[0]["confidence"], "manual")

    def test_entrypoints_prints_json_view(self):
        entrypoint = RawObservation(
            kind="file",
            source_id="bin/tool",
            path="bin/tool",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "shell",
                "role": "entrypoint",
                "content_hash": "0" * 64,
                "generated": False,
                "executable": True,
            },
        )
        script = RawObservation(
            kind="file",
            source_id="scripts/helper.sh",
            path="scripts/helper.sh",
            confidence="extracted",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "shell",
                "role": "script",
                "content_hash": "0" * 64,
                "generated": False,
                "executable": True,
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([entrypoint, script], jsonl_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["entrypoints", str(jsonl_path), "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual([record["path"] for record in payload], ["bin/tool"])
        self.assertEqual(payload[0]["confidence"], "manual")

    def test_host_mutators_prints_json_view(self):
        mutation = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:2:package",
            path="scripts/maintain.sh",
            start_line=2,
            end_line=2,
            name="brew install",
            target="host:package-management",
            confidence="heuristic",
            extractor="fixture-shell",
            extractor_version="0.1.0",
            metadata={
                "argv": ["brew", "install", "postgresql"],
                "category": "package-management",
                "effective_argv": ["brew", "install", "postgresql"],
                "privileged": False,
                "reason": "brew install",
                "tool": "brew",
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([mutation], jsonl_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(["host-mutators", str(jsonl_path), "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload[0]["path"], "scripts/maintain.sh")
        self.assertEqual(payload[0]["category"], "package-management")
        self.assertEqual(payload[0]["target"], "host:package-management")

    def test_host_mutators_summary_prints_json_view(self):
        privileged_rm = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:4:rm",
            path="scripts/maintain.sh",
            start_line=4,
            end_line=4,
            name="rm",
            target="host:filesystem-mutation",
            confidence="heuristic",
            extractor="fixture-shell",
            extractor_version="0.1.0",
            metadata={
                "argv": ["sudo", "rm", "-rf", "/Library/Caches/example"],
                "category": "filesystem-mutation",
                "effective_argv": ["rm", "-rf", "/Library/Caches/example"],
                "privileged": True,
                "reason": "rm host filesystem path",
                "tool": "rm",
            },
        )
        user_rm = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:5:rm",
            path="scripts/maintain.sh",
            start_line=5,
            end_line=5,
            name="rm",
            target="host:filesystem-mutation",
            confidence="heuristic",
            extractor="fixture-shell",
            extractor_version="0.1.0",
            metadata={
                "argv": ["rm", "-rf", "~/Library/Caches/example"],
                "category": "filesystem-mutation",
                "effective_argv": ["rm", "-rf", "~/Library/Caches/example"],
                "privileged": False,
                "reason": "rm host filesystem path",
                "tool": "rm",
            },
        )
        brew = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:2:package",
            path="scripts/maintain.sh",
            start_line=2,
            end_line=2,
            name="brew install",
            target="host:package-management",
            confidence="heuristic",
            extractor="fixture-shell",
            extractor_version="0.1.0",
            metadata={
                "argv": ["brew", "install", "postgresql"],
                "category": "package-management",
                "effective_argv": ["brew", "install", "postgresql"],
                "privileged": False,
                "reason": "brew install",
                "tool": "brew",
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([privileged_rm, user_rm, brew], jsonl_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "host-mutators-summary",
                        str(jsonl_path),
                        "--category",
                        "filesystem-mutation",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload, [
            {
                "category": "filesystem-mutation",
                "count": 2,
                "privileged_count": 1,
                "tool": "rm",
            }
        ])

    def test_observation_and_readback_commands_print_text_views(self):
        file_observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "markdown",
                "role": "documentation",
                "content_hash": "0" * 64,
                "generated": False,
                "executable": False,
            },
        )
        entrypoint = RawObservation(
            kind="file",
            source_id="bin/tool",
            path="bin/tool",
            confidence="manual",
            extractor="fixture-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "shell",
                "role": "entrypoint",
                "content_hash": "0" * 64,
                "generated": False,
                "executable": True,
            },
        )
        mutation = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:2:package",
            path="scripts/maintain.sh",
            start_line=2,
            end_line=2,
            name="brew install",
            target="host:package-management",
            confidence="heuristic",
            extractor="fixture-shell",
            extractor_version="0.1.0",
            metadata={
                "argv": ["brew", "install", "postgresql"],
                "category": "package-management",
                "effective_argv": ["brew", "install", "postgresql"],
                "privileged": False,
                "reason": "brew install",
                "tool": "brew",
            },
        )
        shell_command = RawObservation(
            kind="shell.command",
            source_id="scripts/build.sh#call:nix-build",
            path="scripts/build.sh",
            start_line=21,
            end_line=21,
            name="nix-build",
            target="tool:nix",
            confidence="heuristic",
            extractor="shell-static",
            extractor_version="0.1.0",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl(
                [file_observation, entrypoint, mutation, shell_command],
                jsonl_path,
            )
            commands = (
                (["files", str(jsonl_path)], "README.md"),
                (["entrypoints", str(jsonl_path)], "bin/tool"),
                (["host-mutators", str(jsonl_path)], "brew install"),
                (["host-mutators-summary", str(jsonl_path)], "package-management"),
                (
                    ["observations", "normalize", str(jsonl_path)],
                    "normalized 4 observations",
                ),
            )
            for argv, expected in commands:
                with self.subTest(argv=argv):
                    stdout = io.StringIO()
                    with redirect_stdout(stdout):
                        exit_code = main(argv)
                    self.assertEqual(exit_code, 0)
                    self.assertIn(expected, stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
