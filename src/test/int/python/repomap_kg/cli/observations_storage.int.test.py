import json
import tempfile
from pathlib import Path

from repomap_test_support.cli_integration import (
    CliIntegrationTestCase,
)

from repomap_kg.observations import RawObservation, write_observations_jsonl


class CliObservationsStorageIntegrationTests(CliIntegrationTestCase):
    def test_observation_normalization_command_accepts_fixture_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fixture_root = Path(tmpdir) / "fixture-repo"
            fixture_script = fixture_root / "scripts" / "build.sh"
            fixture_script.parent.mkdir(parents=True)
            fixture_script.write_text("#!/usr/bin/env bash\nnix build .#checks\n")
            raw_jsonl = fixture_root / "raw-observations.jsonl"
            write_observations_jsonl(
                [
                    RawObservation(
                        kind="shell.command",
                        source_id="scripts/build.sh#call:nix-build",
                        path="scripts/build.sh",
                        start_line=2,
                        end_line=2,
                        name="nix build",
                        target="tool:nix",
                        confidence="heuristic",
                        extractor="fixture-shell",
                        extractor_version="0.1.0",
                        metadata={"fixture": True},
                    )
                ],
                raw_jsonl,
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "observations", "normalize", str(raw_jsonl), "--json"
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout)
        self.assertEqual(payload["summary"]["raw_observations"], 1)
        self.assertEqual(payload["summary"]["nodes"], 1)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["summary"]["evidence"], 1)
        self.assertEqual(payload["nodes"][0]["path"], "scripts/build.sh")
        self.assertEqual(payload["edges"][0]["dst_node_key"], "tool:nix")
        self.assertEqual(stderr, "")

    def test_observation_normalization_command_prints_text_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_jsonl = Path(tmpdir) / "raw-observations.jsonl"
            write_observations_jsonl(
                [
                    RawObservation(
                        kind="file",
                        source_id="README.md",
                        path="README.md",
                        confidence="extracted",
                        extractor="fixture-discovery",
                        extractor_version="0.1.0",
                    )
                ],
                raw_jsonl,
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "observations", "normalize", str(raw_jsonl)
            )

        self.assertEqual(exit_code, 0)
        self.assertIn(
            "normalized 1 observations into 1 nodes, 0 edges, and 1 evidence records",
            stdout,
        )
        self.assertEqual(stderr, "")

    def test_observation_normalization_command_reports_bad_jsonl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_jsonl = Path(tmpdir) / "bad-observations.jsonl"
            bad_jsonl.write_text("{bad json}\n")

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "observations", "normalize", str(bad_jsonl), "--json"
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("invalid JSON", stderr)

    def test_observation_normalization_command_reports_schema_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_jsonl = Path(tmpdir) / "bad-observations.jsonl"
            bad_jsonl.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "file",
                        "source_id": "README.md",
                        "path": "README.md",
                        "confidence": "certain",
                        "extractor": "fixture-discovery",
                        "extractor_version": "0.1.0",
                        "metadata": {},
                    },
                    sort_keys=True,
                )
                + "\n"
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "observations", "normalize", str(bad_jsonl), "--json"
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("confidence must be one of", stderr)

    def test_observation_normalization_command_reports_bad_line_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_jsonl = Path(tmpdir) / "bad-observations.jsonl"
            bad_jsonl.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "shell.command",
                        "source_id": "scripts/build.sh#call:nix-build",
                        "path": "scripts/build.sh",
                        "start_line": "2",
                        "end_line": 2,
                        "name": "nix build",
                        "target": "tool:nix",
                        "confidence": "heuristic",
                        "extractor": "fixture-shell",
                        "extractor_version": "0.1.0",
                        "metadata": {},
                    },
                    sort_keys=True,
                )
                + "\n"
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "observations", "normalize", str(bad_jsonl), "--json"
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("start_line must be an integer", stderr)

    def test_storage_load_files_command_reports_schema_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_jsonl = Path(tmpdir) / "bad-observations.jsonl"
            bad_jsonl.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "file",
                        "source_id": "README.md",
                        "path": "README.md",
                        "confidence": "certain",
                        "extractor": "fixture-discovery",
                        "extractor_version": "0.1.0",
                        "metadata": {},
                    },
                    sort_keys=True,
                )
                + "\n"
            )

            exit_code, stdout, stderr = self.run_module_entrypoint(
                "storage",
                "load-files",
                str(bad_jsonl),
                "--repository-name",
                "fixture",
                "--root-path",
                "/tmp/fixture",
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("confidence must be one of", stderr)
