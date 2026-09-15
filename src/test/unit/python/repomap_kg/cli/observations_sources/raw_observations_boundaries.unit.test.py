import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from repomap_kg.cli import main
from repomap_kg.observations.raw import RawObservation, write_observations_jsonl


class CliRawObservationCommandBoundariesUnitTests(unittest.TestCase):
    def test_observations_normalize_reports_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "bad-observations.jsonl"
            jsonl_path.write_text("{bad json}\n")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(
                    ["observations", "normalize", str(jsonl_path), "--json"]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid JSON", stderr.getvalue())

    def test_files_reports_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "bad-observations.jsonl"
            jsonl_path.write_text("{bad json}\n")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(["files", str(jsonl_path), "--json"])

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid JSON", stderr.getvalue())

    def test_entrypoints_reports_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "bad-observations.jsonl"
            jsonl_path.write_text("{bad json}\n")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(["entrypoints", str(jsonl_path), "--json"])

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid JSON", stderr.getvalue())

    def test_host_mutators_reports_validation_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "bad-observations.jsonl"
            jsonl_path.write_text("{bad json}\n")
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                exit_code = main(["host-mutators", str(jsonl_path), "--json"])

        self.assertEqual(exit_code, 1)
        self.assertIn("invalid JSON", stderr.getvalue())

    def test_host_mutators_filters_json_view(self):
        package = RawObservation(
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
        service = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:3:service",
            path="scripts/maintain.sh",
            start_line=3,
            end_line=3,
            name="launchctl bootout",
            target="host:service-management",
            confidence="heuristic",
            extractor="fixture-shell",
            extractor_version="0.1.0",
            metadata={
                "argv": ["sudo", "launchctl", "bootout", "system/example"],
                "category": "service-management",
                "effective_argv": ["launchctl", "bootout", "system/example"],
                "privileged": True,
                "reason": "launchctl bootout",
                "tool": "launchctl",
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl([package, service], jsonl_path)
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = main(
                    [
                        "host-mutators",
                        str(jsonl_path),
                        "--category",
                        "service-management",
                        "--tool",
                        "launchctl",
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual([record["name"] for record in payload], [
            "launchctl bootout",
        ])


if __name__ == "__main__":
    unittest.main()
