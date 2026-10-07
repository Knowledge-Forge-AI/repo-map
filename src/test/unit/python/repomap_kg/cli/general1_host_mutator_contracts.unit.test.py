"""CLI list and refusal contracts for static host mutation observations."""
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


def mutator_records():
    package = edge(
        "file:bin/b.sh",
        "mutates_host",
        PACKAGE_TARGET,
        "h3",
        {
            "tool": "brew",
            "tools": ["brew", "apt", 7],
            "manager": "brew",
            "command": "brew install",
            "commands": ["brew install", 5, ""],
            "privileged_observed": True,
            "destructive_observed": "yes",
            "static_only": False,
        },
        first=2,
        last=5,
    )
    network = edge("file:bin/a.sh", "host_mutation_intent", NETWORK_TARGET, "h1", last=4)
    uncategorized = edge(
        "file:bin/a.sh", "mutates_host", "tool:nix", "h2", {"commands": ["nix"]},
        conflict=True, last=4,
    )
    by_kind = {"mutates_host": (package, uncategorized), "host_mutation_intent": (network,)}
    return by_kind


class CliHostMutatorListContractTests(unittest.TestCase):
    def test_json_merges_both_edge_kinds_in_stable_order_with_derived_fields(self):
        code, stdout, stderr, query = run_cli(
            [
                "storage", "host-mutators", "--root-path", "/tmp/fixture",
                "--pg-host", "db.local", "--pg-port", "5433", "--pg-user", "reader",
                "--pg-database", "graphs", "--psql-command", "/bin/psql", "--json",
            ],
            mutator_records(),
        )

        self.assertEqual((code, stderr), (0, ""))
        base = {"graph_key_version": 1, "confidence": "extracted"}
        self.assertEqual(
            json.loads(stdout),
            [
                {
                    **base, "source_key": "file:bin/a.sh", "edge_kind": "host_mutation_intent",
                    "target_key": NETWORK_TARGET, "identity_metadata_hash": "h1",
                    "conflict": False, "first_seen_run_id": None, "last_seen_run_id": 4,
                    "category": "network",
                },
                {
                    **base, "source_key": "file:bin/a.sh", "edge_kind": "mutates_host",
                    "target_key": "tool:nix", "identity_metadata_hash": "h2",
                    "conflict": True, "first_seen_run_id": None, "last_seen_run_id": 4,
                    "command_names": ["nix"],
                },
                {
                    **base, "source_key": "file:bin/b.sh", "edge_kind": "mutates_host",
                    "target_key": PACKAGE_TARGET, "identity_metadata_hash": "h3",
                    "conflict": False, "first_seen_run_id": 2, "last_seen_run_id": 5,
                    "category": "package-management", "tool_names": ["brew", "apt"],
                    "command_names": ["brew install"], "privileged_observed": True,
                    "static_only": False,
                },
            ],
        )
        psql_args = ["-h", "db.local", "-p", "5433", "-U", "reader", "-d", "graphs"]
        self.assertEqual(
            query.call_args_list,
            [
                call(
                    psql_args, root_path="/tmp/fixture", kind=kind, source_key=None,
                    target_key=None, graph_key_version=1, psql_command="/bin/psql",
                )
                for kind in EDGE_KINDS
            ],
        )

    def test_table_output_renders_aligned_rows_with_blank_and_boolean_cells(self):
        code, stdout, stderr, _query = run_cli(
            ["storage", "host-mutators", "--root-path", "/tmp/fixture"], mutator_records()
        )

        header = [
            "source_key", "edge_kind", "category", "tool_names", "command_names",
            "confidence", "conflict", "first_seen_run_id", "last_seen_run_id",
        ]
        rows = [
            ["file:bin/a.sh", "host_mutation_intent", "network", "", "", "extracted", "false", "", "4"],
            ["file:bin/a.sh", "mutates_host", "", "", "nix", "extracted", "true", "", "4"],
            [
                "file:bin/b.sh", "mutates_host", "package-management", "brew,apt",
                "brew install", "extracted", "false", "2", "5",
            ],
        ]
        self.assertEqual((code, stderr), (0, ""))
        self.assertEqual(stdout, render_table(header, rows))

    def test_tool_filter_matches_tool_manager_and_command_names_only(self):
        cases: tuple[tuple[str, list[str]], ...] = (
            ("apt", ["file:bin/b.sh"]),
            ("brew install", ["file:bin/b.sh"]),
            ("nix", ["file:bin/a.sh"]),
            ("network", []),
        )
        for tool, expected_sources in cases:
            with self.subTest(tool=tool):
                code, stdout, stderr, _query = run_cli(
                    ["storage", "host-mutators", "--root-path", "/tmp/fixture",
                     "--tool", tool, "--json"],
                    mutator_records(),
                )

                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(
                    [item["source_key"] for item in json.loads(stdout)], expected_sources
                )

    def test_unmatched_tool_filter_table_prints_header_only(self):
        code, stdout, _stderr, _query = run_cli(
            ["storage", "host-mutators", "--root-path", "/tmp/fixture", "--tool", "missing"],
            mutator_records(),
        )

        self.assertEqual(code, 0)
        self.assertEqual(
            stdout.split(),
            [
                "source_key", "edge_kind", "category", "tool_names", "command_names",
                "confidence", "conflict", "first_seen_run_id", "last_seen_run_id",
            ],
        )

    def test_category_selects_canonical_target_and_accepts_matching_target_key(self):
        for extra in ([], ["--target-key", PACKAGE_TARGET]):
            with self.subTest(extra=extra):
                code, _stdout, stderr, query = run_cli(
                    ["storage", "host-mutators", "--root-path", "/tmp/fixture",
                     "--category", "package-management", "--source-key", "file:bin/b.sh",
                     "--pg-user", "reader", "--pg-host", "", *extra, "--json"],
                    {kind: () for kind in EDGE_KINDS},
                )

                self.assertEqual((code, stderr), (0, ""))
                self.assertEqual(
                    query.call_args_list,
                    [
                        call(
                            ["-U", "reader"], root_path="/tmp/fixture", kind=kind,
                            source_key="file:bin/b.sh", target_key=PACKAGE_TARGET,
                            graph_key_version=1, psql_command="psql",
                        )
                        for kind in EDGE_KINDS
                    ],
                )

    def test_invalid_filters_refuse_with_exit_one_before_any_readback(self):
        cases = (
            (["--graph-key-version", "2"], "unsupported graph key version"),
            (
                ["--source-key", "bogus"],
                "invalid --source-key canonical key: "
                "canonical key must include a namespace separator",
            ),
            (
                ["--target-key", "nosuchspace:x"],
                "invalid --target-key canonical key: "
                "unknown canonical key namespace: nosuchspace",
            ),
            (
                ["--category", ""],
                "invalid host mutation category: canonical key segment is required",
            ),
            (
                ["--category", "network", "--target-key", PACKAGE_TARGET],
                "category and target-key refer to different host categories",
            ),
        )
        for flags, message in cases:
            with self.subTest(flags=flags):
                code, stdout, stderr, query = run_cli(
                    ["storage", "host-mutators", "--root-path", "/tmp/fixture", *flags],
                    {},
                )

                self.assertEqual(code, 1)
                self.assertEqual(stdout, "")
                self.assertEqual(stderr, f"ERROR: {message}\n")
                query.assert_not_called()

    def test_readback_failure_on_second_edge_kind_prints_sanitized_error_only(self):
        def fail_on_intent(_psql_args, **kwargs):
            if kwargs["kind"] == "host_mutation_intent":
                raise StorageSchemaError(PRIVATE_MESSAGE)
            return mutator_records()["mutates_host"]

        code, stdout, stderr, query = run_cli(
            ["storage", "host-mutators", "--root-path", "/tmp/fixture", "--json"],
            side_effect=fail_on_intent,
        )

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, f"ERROR: {SANITIZED_MESSAGE}\n")
        self.assertEqual(query.call_count, 2)
