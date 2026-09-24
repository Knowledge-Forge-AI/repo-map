import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from repomap_test_support.cli import (
    REPO_ROOT,
    SOURCE_ROOT,
    module_environment,
    run_module_entrypoint,
    run_repo_map_in_process,
    write_text_fixture,
)

from repomap_kg import __version__
from repomap_test_support import cli, cli_in_process


class TestSupportCliHelpersUnitTests(unittest.TestCase):
    def test_environment_leaf_matches_facade_and_preserves_source_patch(self):
        self.assertEqual(cli_in_process.module_environment(), module_environment())
        with mock.patch.object(cli, "SOURCE_ROOT", Path("fixture-source")):
            self.assertEqual(module_environment()["PYTHONPATH"], "fixture-source")
            self.assertEqual(
                module_environment(extra_env={"PYTHONPATH": "override"})["PYTHONPATH"],
                "override",
            )

    def test_entrypoint_refusal_and_exception_restore_argv(self):
        original = sys.argv[:]
        with mock.patch.object(cli.runpy, "run_module", return_value={}):
            with self.assertRaisesRegex(AssertionError, "did not exit"):
                run_module_entrypoint("--version")
        self.assertEqual(sys.argv, original)
        with mock.patch.object(cli.runpy, "run_module", side_effect=RuntimeError("probe")):
            with self.assertRaisesRegex(RuntimeError, "probe"):
                run_module_entrypoint("--version")
        self.assertEqual(sys.argv, original)

    def test_static_cli_capture_matches_the_compatibility_facade(self):
        self.assertEqual(
            cli_in_process.run_repo_map_in_process("--version"),
            run_repo_map_in_process("--version"),
        )

    def test_compatibility_facade_keeps_its_main_patch_location(self):
        received: list[list[str]] = []

        def patched_main(argv: list[str]) -> int:
            received.append(argv)
            print("captured output")
            print("captured error", file=sys.stderr)
            return 17

        with mock.patch.object(cli, "main", patched_main):
            self.assertEqual(
                run_repo_map_in_process("status", "--json"),
                (17, "captured output\n", "captured error\n"),
            )
        self.assertEqual(received, [["status", "--json"]])

    def test_module_environment_sets_source_root_and_allows_extra_values(self):
        env = module_environment(extra_env={"REPOMAP_TEST_FLAG": "yes"})

        self.assertEqual(env["PYTHONPATH"], str(SOURCE_ROOT))
        self.assertEqual(env["REPOMAP_TEST_FLAG"], "yes")
        self.assertTrue((REPO_ROOT / "pyproject.toml").is_file())

    def test_run_repo_map_in_process_captures_stdout_and_stderr(self):
        exit_code, stdout, stderr = run_repo_map_in_process("--version")

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.strip(), f"repomap-kg {__version__}")
        self.assertEqual(stderr, "")

    def test_run_module_entrypoint_captures_output_and_restores_argv(self):
        original_argv = sys.argv[:]

        exit_code, stdout, stderr = run_module_entrypoint("--version")

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.strip(), f"repomap-kg {__version__}")
        self.assertEqual(stderr, "")
        self.assertEqual(sys.argv, original_argv)

    def test_write_text_fixture_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "fixture.txt"

            returned = write_text_fixture(path, "fixture text\n")

            self.assertEqual(returned, path)
            self.assertEqual(path.read_text(encoding="utf-8"), "fixture text\n")


if __name__ == "__main__":
    unittest.main()
# v0.0.2 dynamic target re-attestation.
