"""Baseline and drift CLI output, option ownership, and failure classification."""
import io
import json
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.ops.config import OpsConfigDiagnostic, OpsConfigError
from repomap_kg.ops.refresh import OpsRefreshError

CONFIG = SimpleNamespace(label="config-double")
PRIVATE_MESSAGE = (
    "cannot read /tmp/fixture-private/repomap.toml "
    "via https://example.invalid/cfg with synthetic-token"
)
SANITIZED_MESSAGE = "cannot read [redacted-path] via [redacted-url] with [redacted-value]"


def run_cli(argv):
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def patch_cli(stack, name, **kwargs):
    return stack.enter_context(patch(f"repomap_kg.cli.{name}", **kwargs))


class CliBaselineDispatchGraphBaselineContractTests(unittest.TestCase):
    def test_graph_baseline_exit_code_follows_summary_result_in_both_formats(self):
        cases: tuple[tuple[list[str], str, int], ...] = (
            (["--json"], "failure", 1),
            ([], "success", 0),
            ([], "failure", 1),
        )
        for flags, result, expected_exit in cases:
            with self.subTest(flags=flags, result=result), ExitStack() as stack:
                summary = SimpleNamespace(result=result)
                patch_cli(stack, "load_ops_config_from_args", return_value=CONFIG)
                query = patch_cli(stack, "query_graph_summary", return_value=summary)
                patch_cli(
                    stack,
                    "graph_baseline_to_jsonable",
                    return_value={"command": "graph-baseline", "result": result},
                )
                table = patch_cli(
                    stack, "format_graph_summary_table", return_value="BASELINE TABLE"
                )

                code, stdout, stderr = run_cli(
                    ["ops", "graph-baseline", "--graph", "flakes", *flags]
                )

                self.assertEqual(code, expected_exit)
                self.assertEqual(stderr, "")
                query.assert_called_once_with(CONFIG, "flakes", psql_command=None)
                if flags:
                    self.assertEqual(
                        json.loads(stdout),
                        {"command": "graph-baseline", "result": result},
                    )
                    table.assert_not_called()
                else:
                    self.assertEqual(stdout, "BASELINE TABLE\n")
                    table.assert_called_once_with(CONFIG, summary)

    def test_graph_baseline_refusals_are_sanitized_and_leave_stdout_empty(self):
        cases = (
            ("load_ops_config_from_args", OpsConfigError((OpsConfigDiagnostic("error", "fixture-refusal", "fixture", PRIVATE_MESSAGE),))),
            ("query_graph_summary", OpsConfigError((OpsConfigDiagnostic("error", "fixture-refusal", "fixture", PRIVATE_MESSAGE),))),
            ("query_graph_summary", OpsRefreshError(PRIVATE_MESSAGE)),
        )
        for failing, error in cases:
            with self.subTest(failing=failing, error=type(error).__name__), ExitStack() as stack:
                patch_cli(stack, "load_ops_config_from_args", return_value=CONFIG)
                patch_cli(stack, failing, side_effect=error)
                if failing != "query_graph_summary":
                    patch_cli(stack, "query_graph_summary")

                code, stdout, stderr = run_cli(
                    ["ops", "graph-baseline", "--graph", "flakes", "--psql-command", "/bin/psql"]
                )

                self.assertEqual(code, 1)
                self.assertEqual(stdout, "")
                self.assertEqual(stderr, f"ERROR: {SANITIZED_MESSAGE}\n")


class CliBaselineDispatchSaveAndPruneContractTests(unittest.TestCase):
    def test_baseline_save_table_and_exit_code_follow_result(self):
        for flags, result, expected_exit in (
            ([], "success", 0),
            ([], "failure", 1),
            (["--json"], "failure", 1),
        ):
            with self.subTest(flags=flags, result=result), ExitStack() as stack:
                saved = SimpleNamespace(result=result)
                patch_cli(stack, "load_ops_config_from_args", return_value=CONFIG)
                save = patch_cli(stack, "save_graph_baselines", return_value=saved)
                patch_cli(
                    stack,
                    "baseline_save_to_jsonable",
                    return_value={"command": "baseline-save", "result": result},
                )
                patch_cli(stack, "format_baseline_save_table", return_value="SAVE TABLE")

                code, stdout, stderr = run_cli(
                    ["ops", "baseline-save", "--graph", "flakes", "--kind", "stored", *flags]
                )

                self.assertEqual(code, expected_exit)
                self.assertEqual(stderr, "")
                save.assert_called_once_with(
                    CONFIG, "flakes", kind="stored", psql_command=None
                )
                if flags:
                    self.assertEqual(json.loads(stdout)["result"], result)
                else:
                    self.assertEqual(stdout, "SAVE TABLE\n")

    def test_baseline_prune_deletes_only_with_yes_and_prints_table(self):
        for flags, expected_dry_run in (([], True), (["--dry-run"], True), (["--yes"], False)):
            with self.subTest(flags=flags), ExitStack() as stack:
                pruned = SimpleNamespace(result="success")
                patch_cli(stack, "load_ops_config_from_args", return_value=CONFIG)
                prune = patch_cli(stack, "prune_graph_baselines", return_value=pruned)
                patch_cli(stack, "baseline_prune_to_jsonable")
                table = patch_cli(
                    stack, "format_baseline_prune_table", return_value="PRUNE TABLE"
                )

                code, stdout, stderr = run_cli(
                    [
                        "ops", "baseline-prune", "--graph", "flakes", "--kind", "both",
                        "--keep", "3", *flags,
                    ]
                )

                self.assertEqual((code, stdout, stderr), (0, "PRUNE TABLE\n", ""))
                prune.assert_called_once_with(
                    CONFIG, "flakes", kind="both", keep=3, dry_run=expected_dry_run
                )
                table.assert_called_once_with(CONFIG, pruned)

    def test_baseline_prune_failure_result_exits_one_after_printing_payload(self):
        with ExitStack() as stack:
            patch_cli(stack, "load_ops_config_from_args", return_value=CONFIG)
            patch_cli(
                stack, "prune_graph_baselines", return_value=SimpleNamespace(result="failure")
            )
            patch_cli(
                stack, "baseline_prune_to_jsonable", return_value={"result": "failure"}
            )

            code, stdout, stderr = run_cli(
                [
                    "ops", "baseline-prune", "--graph", "flakes", "--kind", "stored",
                    "--keep", "1", "--yes", "--json",
                ]
            )

        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout), {"result": "failure"})
        self.assertEqual(stderr, "")

    def test_save_and_prune_refusals_including_oserror_are_sanitized(self):
        commands = {
            "baseline-save": ("save_graph_baselines", []),
            "baseline-prune": ("prune_graph_baselines", ["--keep", "2"]),
        }
        for command, (failing, extra) in commands.items():
            for error in (
                OpsConfigError((OpsConfigDiagnostic("error", "fixture-refusal", "fixture", PRIVATE_MESSAGE),)),
                OpsRefreshError(PRIVATE_MESSAGE),
                OSError(PRIVATE_MESSAGE),
            ):
                with self.subTest(command=command, error=type(error).__name__), ExitStack() as stack:
                    patch_cli(stack, "load_ops_config_from_args", return_value=CONFIG)
                    patch_cli(stack, failing, side_effect=error)

                    code, stdout, stderr = run_cli(
                        ["ops", command, "--graph", "flakes", "--kind", "stored", *extra]
                    )

                    self.assertEqual(code, 1)
                    self.assertEqual(stdout, "")
                    self.assertEqual(stderr, f"ERROR: {SANITIZED_MESSAGE}\n")



class CliBaselineDispatchDriftCheckContractTests(unittest.TestCase):
    def _write(self, directory, name, text):
        path = Path(directory) / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_drift_check_exit_code_classifies_result_in_both_formats(self):
        cases = (
            ("success", 0),
            ("warning", 2),
            ("failure", 1),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline = self._write(tmpdir, "baseline.json", json.dumps({"files": 3}))
            for as_json in (False, True):
                for result, expected_exit in cases:
                    with self.subTest(result=result, as_json=as_json), ExitStack() as stack:
                        drift = SimpleNamespace(result=result)
                        patch_cli(stack, "load_ops_config_from_args", return_value=CONFIG)
                        query = patch_cli(stack, "query_drift_check", return_value=drift)
                        patch_cli(
                            stack,
                            "drift_check_to_jsonable",
                            return_value={"command": "drift-check", "result": result},
                        )
                        patch_cli(stack, "format_drift_check_table", return_value="DRIFT TABLE")

                        code, stdout, stderr = run_cli(
                            [
                                "ops", "drift-check", "--graph", "flakes",
                                "--baseline-file", baseline,
                                *(["--json"] if as_json else []),
                            ]
                        )

                        self.assertEqual(code, expected_exit)
                        self.assertEqual(stderr, "")
                        query.assert_called_once_with(
                            CONFIG,
                            "flakes",
                            baseline={"files": 3},
                            include_preflight=False,
                            preflight_baseline=None,
                            psql_command=None,
                        )
                        if as_json:
                            self.assertEqual(json.loads(stdout)["result"], result)
                        else:
                            self.assertEqual(stdout, "DRIFT TABLE\n")

    def test_drift_check_rejects_unusable_baseline_inputs_without_querying(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            array_file = self._write(tmpdir, "array.json", "[]")
            broken_file = self._write(tmpdir, "broken.json", "{")
            object_file = self._write(tmpdir, "object.json", "{}")
            cases = (
                ("array", ["--baseline-file", array_file], "baseline file must contain a JSON object"),
                ("broken", ["--baseline-file", broken_file], "baseline file is not valid JSON"),
                (
                    "orphan-preflight-file",
                    ["--baseline-file", object_file, "--preflight-baseline-file", object_file],
                    "--preflight-baseline-file requires --include-preflight",
                ),
            )
            for label, flags, expected in cases:
                with self.subTest(label=label), ExitStack() as stack:
                    patch_cli(stack, "load_ops_config_from_args", return_value=CONFIG)
                    query = patch_cli(stack, "query_drift_check")

                    code, stdout, stderr = run_cli(
                        ["ops", "drift-check", "--graph", "flakes", *flags, "--json"]
                    )

                    self.assertEqual(code, 1)
                    self.assertEqual(stdout, "")
                    self.assertIn(expected, stderr)
                    self.assertTrue(stderr.startswith("ERROR: "))
                    query.assert_not_called()

    def test_drift_check_missing_baseline_file_reports_redacted_path(self):
        with tempfile.TemporaryDirectory() as tmpdir, ExitStack() as stack:
            patch_cli(stack, "load_ops_config_from_args", return_value=CONFIG)
            query = patch_cli(stack, "query_drift_check")

            code, stdout, stderr = run_cli(
                [
                    "ops", "drift-check", "--graph", "flakes",
                    "--baseline-file", str(Path(tmpdir) / "absent-fixture.json"),
                ]
            )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("No such file or directory", stderr)
        self.assertIn("[redacted-path]", stderr)
        self.assertNotIn(tmpdir, stderr)
        query.assert_not_called()

    def test_drift_check_refusals_from_collaborators_are_sanitized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline = self._write(tmpdir, "baseline.json", "{}")
            cases = (
                ("load_ops_config_from_args", OpsConfigError((OpsConfigDiagnostic("error", "fixture-refusal", "fixture", PRIVATE_MESSAGE),))),
                ("query_drift_check", OpsRefreshError(PRIVATE_MESSAGE)),
                ("query_drift_check", ValueError(PRIVATE_MESSAGE)),
                ("query_drift_check", OSError(PRIVATE_MESSAGE)),
            )
            for failing, error in cases:
                with self.subTest(failing=failing, error=type(error).__name__), ExitStack() as stack:
                    patch_cli(stack, "load_ops_config_from_args", return_value=CONFIG)
                    patch_cli(stack, "query_drift_check")
                    patch_cli(stack, failing, side_effect=error)

                    code, stdout, stderr = run_cli(
                        ["ops", "drift-check", "--graph", "flakes", "--baseline-file", baseline]
                    )

                    self.assertEqual(code, 1)
                    self.assertEqual(stdout, "")
                    self.assertEqual(stderr, f"ERROR: {SANITIZED_MESSAGE}\n")
