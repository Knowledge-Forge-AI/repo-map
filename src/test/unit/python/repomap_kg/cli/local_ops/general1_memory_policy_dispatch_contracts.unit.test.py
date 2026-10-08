"""Read-only memory and policy CLI dispatch forwarding and sanitized refusal."""
import io
import json
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from unittest.mock import patch

from repomap_kg.cli import main
from repomap_kg.ops.config import OpsConfigDiagnostic, OpsConfigError

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


class CliBaselineDispatchServerMemoryAndPolicyContractTests(unittest.TestCase):
    def test_server_memory_summary_forwards_config_selectors_and_formats_output(self):
        for as_json in (False, True):
            with self.subTest(as_json=as_json), ExitStack() as stack:
                payload = {"entries": 4}
                summary = patch_cli(stack, "server_memory_summary_payload", return_value=payload)
                table = patch_cli(
                    stack, "format_server_memory_summary_table", return_value="MEMORY TABLE"
                )

                code, stdout, stderr = run_cli(
                    [
                        "ops", "server-memory-summary", "--config", "/etc/repomap.toml",
                        "--repo-map-home", "/etc/repomap-home",
                        *(["--json"] if as_json else []),
                    ]
                )

                self.assertEqual((code, stderr), (0, ""))
                summary.assert_called_once_with(
                    config_path="/etc/repomap.toml", config_home="/etc/repomap-home"
                )
                if as_json:
                    self.assertEqual(json.loads(stdout), payload)
                    table.assert_not_called()
                else:
                    self.assertEqual(stdout, "MEMORY TABLE\n")
                    table.assert_called_once_with(payload)

    def test_server_memory_search_forwards_query_window_and_formats_output(self):
        for as_json in (False, True):
            with self.subTest(as_json=as_json), ExitStack() as stack:
                payload: dict[str, list[object]] = {"matches": []}
                search = patch_cli(stack, "server_memory_search_payload", return_value=payload)
                table = patch_cli(
                    stack, "format_server_memory_search_table", return_value="SEARCH TABLE"
                )

                code, stdout, stderr = run_cli(
                    [
                        "ops", "server-memory-search", "--query", "nix", "--kind", "entity",
                        "--limit", "5", "--offset", "10",
                        *(["--json"] if as_json else []),
                    ]
                )

                self.assertEqual((code, stderr), (0, ""))
                search.assert_called_once_with(
                    config_path=None, config_home=None, query="nix",
                    kind="entity", limit=5, offset=10,
                )
                if as_json:
                    self.assertEqual(json.loads(stdout), payload)
                else:
                    self.assertEqual(stdout, "SEARCH TABLE\n")
                    table.assert_called_once_with(payload)

    def test_policy_dogfood_forwards_graph_and_formats_output(self):
        for as_json in (False, True):
            with self.subTest(as_json=as_json), ExitStack() as stack:
                payload = {"boundaries": ["public"]}
                dogfood = patch_cli(stack, "policy_dogfood_payload", return_value=payload)
                table = patch_cli(stack, "format_policy_dogfood_table", return_value="POLICY TABLE")

                code, stdout, stderr = run_cli(
                    [
                        "ops", "policy-dogfood", "--graph", "flakes",
                        "--repo-map-home", "/etc/repomap-home",
                        *(["--json"] if as_json else []),
                    ]
                )

                self.assertEqual((code, stderr), (0, ""))
                dogfood.assert_called_once_with(
                    config_path=None, config_home="/etc/repomap-home", graph_id="flakes"
                )
                if as_json:
                    self.assertEqual(json.loads(stdout), payload)
                else:
                    self.assertEqual(stdout, "POLICY TABLE\n")
                    table.assert_called_once_with(payload)

    def test_memory_and_policy_refusals_are_sanitized_for_config_and_value_errors(self):
        commands = (
            ("server_memory_summary_payload", ["server-memory-summary"]),
            ("server_memory_search_payload", ["server-memory-search", "--query", "nix"]),
            ("policy_dogfood_payload", ["policy-dogfood", "--graph", "flakes"]),
        )
        for failing, argv in commands:
            for error in (OpsConfigError((OpsConfigDiagnostic("error", "fixture-refusal", "fixture", PRIVATE_MESSAGE),)), ValueError(PRIVATE_MESSAGE)):
                with self.subTest(command=argv[0], error=type(error).__name__), ExitStack() as stack:
                    patch_cli(stack, failing, side_effect=error)

                    code, stdout, stderr = run_cli(["ops", *argv, "--json"])

                    self.assertEqual(code, 1)
                    self.assertEqual(stdout, "")
                    self.assertEqual(stderr, f"ERROR: {SANITIZED_MESSAGE}\n")
