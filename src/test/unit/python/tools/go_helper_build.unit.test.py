from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import build_go_helper as build_go_helper

REPO_ROOT = Path(__file__).resolve().parents[5]


def load_tool_module(name: str, relative_path: str):
    return build_go_helper


class GoHelperBuildUnitTests(unittest.TestCase):
    def test_platform_tag_normalizes_go_architecture_names(self):
        self.assertEqual(
            build_go_helper.platform_tag(system="darwin", machine="x86_64"),
            "darwin-amd64",
        )
        self.assertEqual(
            build_go_helper.platform_tag(system="linux", machine="aarch64"),
            "linux-arm64",
        )

    def test_build_publishes_executable_atomically_beside_package(self):
        commands = []

        def fake_run(command, **kwargs):
            commands.append((tuple(command), kwargs))
            output = Path(command[command.index("-o") + 1])
            output.write_bytes(b"helper")
            return subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            with patch.object(build_go_helper.subprocess, "run", side_effect=fake_run):
                helper = build_go_helper.build_go_helper(
                    repo_root=REPO_ROOT,
                    package_root=output_root,
                    target_platform="test-platform",
                )

            self.assertEqual(
                helper,
                output_root / "_bin" / "test-platform" / build_go_helper.HELPER_NAME,
            )
            self.assertEqual(helper.read_bytes(), b"helper")
            self.assertTrue(os.access(helper, os.X_OK))
            self.assertEqual(len(commands), 1)
            command, kwargs = commands[0]
            self.assertEqual(command[:3], ("go", "build", "-trimpath"))
            self.assertEqual(command[-1], "./cmd/repomap-go-extract")
            self.assertEqual(kwargs["cwd"], REPO_ROOT / "src" / "main" / "go")
            self.assertTrue(kwargs["check"])


class GoValidationFailureEvidenceUnitTests(unittest.TestCase):
    """Each validation step must name itself when it is the one that failed."""

    def fake_run_factory(self, *, total_percent="93.3%", failures=None):
        failures = failures or {}

        def fake_run(command, **kwargs):
            command = tuple(command)
            failure = failures.get(command[:2])
            if isinstance(failure, BaseException):
                raise failure
            if failure is not None:
                raise subprocess.CalledProcessError(failure, command)
            if command[:3] == ("go", "tool", "cover"):
                return subprocess.CompletedProcess(
                    command, 0, stdout=f"total:\t(statements)\t{total_percent}\n"
                )
            return subprocess.CompletedProcess(command, 0)

        return fake_run

    def validate(self, fake_run):
        with patch.object(build_go_helper.subprocess, "run", side_effect=fake_run):
            build_go_helper.validate_go_sources(repo_root=REPO_ROOT)

    def test_validation_passes_when_every_step_succeeds(self):
        self.validate(self.fake_run_factory())

    def test_missing_executable_names_the_absent_command(self):
        fake_run = self.fake_run_factory(
            failures={("golangci-lint", "run"): FileNotFoundError("golangci-lint")}
        )
        with self.assertRaises(RuntimeError) as caught:
            self.validate(fake_run)
        message = str(caught.exception)
        self.assertIn("golangci-lint run", message)
        self.assertIn("was not found", message)
        self.assertIsInstance(caught.exception.__cause__, FileNotFoundError)

    def test_nonzero_go_vet_is_distinguishable(self):
        with self.assertRaises(RuntimeError) as caught:
            self.validate(self.fake_run_factory(failures={("go", "vet"): 3}))
        message = str(caught.exception)
        self.assertIn("go vet", message)
        self.assertIn("exit status 3", message)
        self.assertNotIn("golangci-lint", message)

    def test_nonzero_golangci_lint_is_distinguishable(self):
        with self.assertRaises(RuntimeError) as caught:
            self.validate(self.fake_run_factory(failures={("golangci-lint", "run"): 1}))
        message = str(caught.exception)
        self.assertIn("golangci-lint run", message)
        self.assertIn("exit status 1", message)
        self.assertNotIn("go vet", message)

    def test_nonzero_race_test_is_distinguishable(self):
        fake_run = self.fake_run_factory(failures={("go", "test"): 2})
        with self.assertRaises(RuntimeError) as caught:
            self.validate(fake_run)
        # The coverage run is the first `go test`, so it is the reported step.
        self.assertIn("go test coverage", str(caught.exception))

        def race_only(command, **kwargs):
            command = tuple(command)
            if command == ("go", "test", "-race", "./..."):
                raise subprocess.CalledProcessError(2, command)
            return self.fake_run_factory()(command, **kwargs)

        with self.assertRaises(RuntimeError) as caught:
            self.validate(race_only)
        message = str(caught.exception)
        self.assertIn("go race test", message)
        self.assertIn("exit status 2", message)

    def test_coverage_below_threshold_is_distinguishable(self):
        with self.assertRaises(RuntimeError) as caught:
            self.validate(self.fake_run_factory(total_percent="84.9%"))
        message = str(caught.exception)
        self.assertIn("coverage 84.9%", message)
        self.assertIn("below 85.0%", message)

    def test_failure_evidence_stays_bounded_to_command_and_status(self):
        secret_env = "REPOMAP_FAKE_SECRET_VALUE"
        with patch.dict(os.environ, {"REPOMAP_FAKE_SECRET": secret_env}):
            with self.assertRaises(RuntimeError) as caught:
                self.validate(self.fake_run_factory(failures={("go", "vet"): 3}))
        self.assertNotIn(secret_env, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
