"""CLI category aggregation and filtering contracts for host mutation readback."""
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import call, patch

from repomap_kg.cli import main
from repomap_kg.storage import CanonicalEdgeRecord, StorageSchemaError

PACKAGE_TARGET = "host.category:package-management"
NETWORK_TARGET = "host.category:network"
EDGE_KINDS = ("mutates_host", "host_mutation_intent")
PRIVATE_MESSAGE = (
    "storage failed for /tmp/fixture-private/repo "
    "via https://example.invalid/db with synthetic-token"
)
SANITIZED_MESSAGE = "storage failed for [redacted-path] via [redacted-url] with [redacted-value]"


def edge(source, kind, target, digest, metadata=None, *, conflict=False, first=None, last=1):
    return CanonicalEdgeRecord(
        source_key=source,
        edge_kind=kind,
        target_key=target,
        graph_key_version=1,
        identity_metadata={},
        identity_metadata_hash=digest,
        metadata=metadata or {},
        confidence="extracted",
        conflict=conflict,
        first_seen_run_id=first,
        last_seen_run_id=last,
    )


def run_cli(argv, by_kind=None, side_effect=None):
    """Run the CLI with only the edge readback collaborator replaced."""
    if side_effect is None:
        def side_effect(_psql_args, **kwargs):
            return by_kind[kwargs["kind"]]
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch("repomap_kg.cli.query_canonical_edge_records", side_effect=side_effect) as query:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue(), query


def render_table(header, rows):
    widths = [max(len(cell) for cell in column) for column in zip(header, *rows, strict=True)]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True))
        for row in (header, *rows)
    ) + "\n"


class CliHostMutatorSummaryContractTests(unittest.TestCase):
    @staticmethod
    def summary_records():
        def package(source, kind, digest, privileged=None):
            metadata = {} if privileged is None else {"privileged_observed": privileged}
            return edge(source, kind, PACKAGE_TARGET, digest, metadata)

        return {
            "mutates_host": (
                package("file:bin/a.sh", "mutates_host", "x1", True),
                package("file:bin/a.sh", "mutates_host", "x2", False),
                package("file:bin/b.sh", "mutates_host", "x1", True),
                edge("file:bin/a.sh", "mutates_host", "tool:nix", "x3", {"tool": "nix"}),
            ),
            "host_mutation_intent": (
                package("file:bin/a.sh", "host_mutation_intent", "x1"),
                edge(
                    "file:bin/c.sh", "host_mutation_intent", NETWORK_TARGET, "x4",
                    {"privileged_observed": "true"},
                ),
            ),
        }

    def test_json_groups_by_category_and_kind_and_skips_uncategorized_targets(self):
        code, stdout, stderr, query = run_cli(
            ["storage", "host-mutators-summary", "--root-path", "/tmp/fixture", "--json"],
            self.summary_records(),
        )

        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(
            json.loads(stdout),
            [
                {
                    "category": "network", "edge_kind": "host_mutation_intent",
                    "source_count": 1, "canonical_edge_count": 1,
                    "privileged_edge_count": 0, "intent_edge_count": 1,
                    "proven_edge_count": 0,
                },
                {
                    "category": "package-management", "edge_kind": "host_mutation_intent",
                    "source_count": 1, "canonical_edge_count": 1,
                    "privileged_edge_count": 0, "intent_edge_count": 1,
                    "proven_edge_count": 0,
                },
                {
                    "category": "package-management", "edge_kind": "mutates_host",
                    "source_count": 2, "canonical_edge_count": 3,
                    "privileged_edge_count": 2, "intent_edge_count": 0,
                    "proven_edge_count": 3,
                },
            ],
        )
        self.assertEqual(
            query.call_args_list,
            [
                call(
                    [], root_path="/tmp/fixture", kind=kind, source_key=None,
                    target_key=None, graph_key_version=1, psql_command="psql",
                )
                for kind in EDGE_KINDS
            ],
        )

    def test_table_output_and_tool_filter_apply_before_summarizing(self):
        header = [
            "category", "edge_kind", "source_count", "canonical_edge_count",
            "privileged_edge_count", "intent_edge_count", "proven_edge_count",
        ]
        code, stdout, stderr, _query = run_cli(
            ["storage", "host-mutators-summary", "--root-path", "/tmp/fixture"],
            self.summary_records(),
        )
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(
            stdout,
            render_table(
                header,
                [
                    ["network", "host_mutation_intent", "1", "1", "0", "1", "0"],
                    ["package-management", "host_mutation_intent", "1", "1", "0", "1", "0"],
                    ["package-management", "mutates_host", "2", "3", "2", "0", "3"],
                ],
            ),
        )

        records = self.summary_records()
        records["mutates_host"] = (
            edge("file:bin/a.sh", "mutates_host", PACKAGE_TARGET, "y1", {"managers": ["pip"]}),
            edge("file:bin/b.sh", "mutates_host", PACKAGE_TARGET, "y2", {"tool": "brew"}),
        )
        code, stdout, _stderr, _query = run_cli(
            ["storage", "host-mutators-summary", "--root-path", "/tmp/fixture",
             "--tool", "pip"],
            records,
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            stdout,
            render_table(header, [["package-management", "mutates_host", "1", "1", "0", "0", "1"]]),
        )

    def test_category_option_narrows_readback_target(self):
        code, stdout, stderr, query = run_cli(
            ["storage", "host-mutators-summary", "--root-path", "/tmp/fixture",
             "--category", "network", "--json"],
            {kind: () for kind in EDGE_KINDS},
        )

        self.assertEqual((code, stdout, stderr), (0, "[]\n", ""))
        self.assertEqual(
            [item.kwargs["target_key"] for item in query.call_args_list],
            [NETWORK_TARGET, NETWORK_TARGET],
        )

    def test_invalid_options_and_readback_errors_are_refused_with_sanitized_stderr(self):
        for flags, message in (
            (["--graph-key-version", "2"], "unsupported graph key version"),
            (["--category", ""], "invalid host mutation category: canonical key segment is required"),
        ):
            with self.subTest(flags=flags):
                code, stdout, stderr, query = run_cli(
                    ["storage", "host-mutators-summary", "--root-path", "/tmp/fixture", *flags],
                    {},
                )

                self.assertEqual((code, stdout), (1, ""))
                self.assertEqual(stderr, f"ERROR: {message}\n")
                query.assert_not_called()

        def fail(_psql_args, **_kwargs):
            raise StorageSchemaError(PRIVATE_MESSAGE)

        code, stdout, stderr, query = run_cli(
            ["storage", "host-mutators-summary", "--root-path", "/tmp/fixture"],
            side_effect=fail,
        )
        self.assertEqual((code, stdout), (1, ""))
        self.assertEqual(stderr, f"ERROR: {SANITIZED_MESSAGE}\n")
        self.assertEqual(query.call_count, 1)
