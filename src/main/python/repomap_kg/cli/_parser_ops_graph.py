"""Ops graph, refresh, baseline, and inspect parser construction for RepoMap CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable

__all__ = (
    "_graph_file_limit",
    "_non_negative_offset",
    "add_ops_graph_commands",
)

StorageArgumentHelper = Callable[[argparse.ArgumentParser], None]


def _graph_file_limit(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 200:
        raise argparse.ArgumentTypeError("limit must be between 1 and 200")
    return parsed


def _non_negative_offset(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("offset must be a non-negative integer")
    return parsed


def add_ops_graph_commands(
    ops_subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
    add_ops_config_arguments: StorageArgumentHelper,
) -> None:
    config_check = ops_subcommands.add_parser(
        "config-check",
        help="validate a unified local operations TOML config",
    )
    add_ops_config_arguments(config_check)
    config_check.add_argument(
        "--check-db",
        action="store_true",
        help="run a read-only Postgres schema readiness probe",
    )
    config_check.add_argument(
        "--psql-command",
        help=(
            "supplying this option forces an explicit psql executable or wrapper; "
            "omission uses the configured readback selector and defaults to Psycopg"
        ),
    )
    config_check.add_argument("--json", action="store_true", help="emit operations config status as JSON")
    ops_graphs = ops_subcommands.add_parser(
        "graphs",
        help="list configured unified TOML graph registry entries",
    )
    add_ops_config_arguments(ops_graphs)
    ops_graphs.add_argument(
        "--check-db",
        action="store_true",
        help="run read-only storage namespace readiness checks",
    )
    ops_graphs.add_argument(
        "--psql-command",
        help=(
            "supplying this option forces an explicit psql executable or wrapper "
            "for both readiness and graph-storage checks; omission uses the "
            "configured readback selector and defaults to Psycopg"
        ),
    )
    ops_graphs.add_argument("--json", action="store_true", help="emit configured graph registry status as JSON")
    refresh_graph_command = ops_subcommands.add_parser(
        "refresh-graph",
        help="refresh one enabled configured graph from its local root",
    )
    add_ops_config_arguments(refresh_graph_command)
    refresh_graph_command.add_argument("--graph", required=True, help="configured graph id to refresh")
    refresh_graph_command.add_argument(
        "--mode",
        choices=("direct", "coordinator"),
        default="direct",
        help=(
            "execution boundary; direct remains the default; coordinator "
            "requires an existing service and never falls back"
        ),
    )
    refresh_graph_command.add_argument("--backend-telemetry-fd", type=int, help=argparse.SUPPRESS)
    refresh_graph_command.add_argument("--backend-telemetry-ack-fd", type=int, help=argparse.SUPPRESS)
    refresh_graph_command.add_argument("--staging-event-fd", type=int, help=argparse.SUPPRESS)
    refresh_graph_command.add_argument(
        "--idempotency-key",
        help="durable public-safe request identity required in coordinator mode",
    )
    refresh_graph_command.add_argument(
        "--coordinator-wait-seconds",
        type=int,
        default=3600,
        help="bounded terminal wait in coordinator mode (default: 3600)",
    )
    refresh_graph_command.add_argument("--psql-command", help="psql executable to use for loading storage")
    refresh_graph_command.add_argument("--json", action="store_true", help="emit graph refresh result as JSON")
    refresh_preflight = ops_subcommands.add_parser(
        "refresh-preflight",
        help="inspect one configured graph refresh without loading storage",
    )
    add_ops_config_arguments(refresh_preflight)
    refresh_preflight.add_argument("--graph", required=True, help="configured graph id to preflight")
    refresh_preflight.add_argument("--json", action="store_true", help="emit graph refresh preflight as JSON")
    refresh_enabled = ops_subcommands.add_parser(
        "refresh-enabled",
        help="refresh all enabled configured graphs in config order",
    )
    add_ops_config_arguments(refresh_enabled)
    refresh_enabled.add_argument("--psql-command", help="psql executable to use for loading storage")
    refresh_enabled.add_argument("--json", action="store_true", help="emit enabled graph refresh result as JSON")
    refresh_status = ops_subcommands.add_parser(
        "refresh-status",
        help="read stored refresh status for configured graphs",
    )
    add_ops_config_arguments(refresh_status)
    refresh_status.add_argument(
        "--graph",
        action="append",
        help="configured graph id to report; repeat for multiple graphs",
    )
    refresh_status.add_argument("--psql-command", help="psql executable to use for read-only storage status")
    refresh_status.add_argument("--json", action="store_true", help="emit graph refresh status as JSON")
    graph_summary = ops_subcommands.add_parser(
        "graph-summary",
        help="read bounded stored graph counts for one configured graph",
    )
    add_ops_config_arguments(graph_summary)
    graph_summary.add_argument("--graph", required=True, help="configured graph id to summarize")
    graph_summary.add_argument("--psql-command", help="psql executable to use for read-only storage summary")
    graph_summary.add_argument("--json", action="store_true", help="emit graph summary as JSON")
    graph_files = ops_subcommands.add_parser(
        "graph-files",
        help="list bounded canonical file nodes for one configured graph",
    )
    add_ops_config_arguments(graph_files)
    graph_files.add_argument("--graph", required=True, help="configured graph id to query")
    graph_file_path = graph_files.add_mutually_exclusive_group()
    graph_file_path.add_argument("--path", help="include only this canonical path")
    graph_file_path.add_argument("--path-prefix", help="include only canonical files under this path prefix")
    graph_files.add_argument("--language", help="include this canonical language")
    graph_files.add_argument("--role", help="include this canonical file role")
    graph_files.add_argument(
        "--generated",
        choices=("include", "exclude", "only"),
        default="include",
        help="filter canonical generated states",
    )
    graph_files.add_argument(
        "--executable",
        choices=("include", "exclude", "only"),
        default="include",
        help="filter canonical executable states",
    )
    graph_files.add_argument(
        "--observation-state",
        choices=("any", "observed", "referenced"),
        default="any",
        help="filter files with or without direct file observations",
    )
    graph_files.add_argument(
        "--ambiguity",
        choices=("include", "exclude", "only"),
        default="include",
        help="filter canonical ambiguity or conflicts",
    )
    graph_files.add_argument("--limit", type=_graph_file_limit, default=50)
    graph_files.add_argument("--offset", type=_non_negative_offset, default=0)
    graph_files.add_argument(
        "--psql-command",
        help="psql executable to use for read-only canonical file readback",
    )
    graph_files.add_argument("--json", action="store_true", help="emit canonical graph files as JSON")
    graph_baseline = ops_subcommands.add_parser(
        "graph-baseline",
        help="capture bounded stored graph baseline for one configured graph",
    )
    add_ops_config_arguments(graph_baseline)
    graph_baseline.add_argument("--graph", required=True, help="configured graph id to baseline")
    graph_baseline.add_argument(
        "--psql-command",
        help="psql executable to use for read-only storage baseline",
    )
    graph_baseline.add_argument("--json", action="store_true", help="emit graph baseline as JSON")
    baseline_save = ops_subcommands.add_parser(
        "baseline-save",
        help="save accepted graph baselines under REPOMAP_HOME/status/baselines",
    )
    add_ops_config_arguments(baseline_save)
    baseline_save.add_argument("--graph", required=True, help="configured graph id to save a baseline for")
    baseline_save.add_argument(
        "--kind",
        required=True,
        choices=("stored", "preflight", "both"),
        help="baseline kind to save",
    )
    baseline_save.add_argument(
        "--psql-command",
        help="psql executable to use for stored graph baseline readback",
    )
    baseline_save.add_argument("--json", action="store_true", help="emit baseline-save metadata as JSON")
    baseline_prune = ops_subcommands.add_parser(
        "baseline-prune",
        help="prune old accepted graph baselines under REPOMAP_HOME/status/baselines",
    )
    add_ops_config_arguments(baseline_prune)
    baseline_prune.add_argument("--graph", required=True, help="configured graph id to prune baselines for")
    baseline_prune.add_argument(
        "--kind",
        required=True,
        choices=("stored", "preflight", "both"),
        help="baseline kind to prune",
    )
    baseline_prune.add_argument(
        "--keep",
        required=True,
        type=int,
        help="number of newest timestamped baseline files to keep per kind",
    )
    baseline_prune.add_argument("--dry-run", action="store_true", help="show prune candidates without deleting files")
    baseline_prune.add_argument("--yes", action="store_true", help="confirm actual deletion of old timestamped baseline files")
    baseline_prune.add_argument("--json", action="store_true", help="emit baseline-prune metadata as JSON")
    drift_check = ops_subcommands.add_parser(
        "drift-check",
        help="compare bounded stored graph counts to an explicit baseline",
    )
    add_ops_config_arguments(drift_check)
    drift_check.add_argument("--graph", required=True, help="configured graph id to compare")
    drift_check.add_argument("--baseline-file", required=True, help="JSON baseline file produced by ops graph-baseline")
    drift_check.add_argument(
        "--include-preflight",
        action="store_true",
        help="also compare current refresh-preflight output to a baseline",
    )
    drift_check.add_argument("--preflight-baseline-file", help="JSON baseline file produced by ops refresh-preflight")
    drift_check.add_argument(
        "--psql-command",
        help="psql executable to use for read-only drift-check storage readback",
    )
    drift_check.add_argument("--json", action="store_true", help="emit drift check as JSON")
    server_memory_summary = ops_subcommands.add_parser(
        "server-memory-summary",
        help="summarize configured server-memory JSONL in read-only mode",
    )
    add_ops_config_arguments(server_memory_summary)
    server_memory_summary.add_argument("--json", action="store_true", help="emit server-memory summary as JSON")
    server_memory_search = ops_subcommands.add_parser(
        "server-memory-search",
        help="search configured server-memory JSONL in read-only mode",
    )
    add_ops_config_arguments(server_memory_search)
    server_memory_search.add_argument("--query", required=True)
    server_memory_search.add_argument("--kind")
    server_memory_search.add_argument("--limit", type=int, default=20)
    server_memory_search.add_argument("--offset", type=int, default=0)
    server_memory_search.add_argument("--json", action="store_true", help="emit server-memory search results as JSON")
    policy_dogfood = ops_subcommands.add_parser(
        "policy-dogfood",
        help="build a public-safe operational policy boundary dogfooding report",
    )
    add_ops_config_arguments(policy_dogfood)
    policy_dogfood.add_argument(
        "--graph",
        required=True,
        help="configured graph id to use for policy dogfooding context",
    )
    policy_dogfood.add_argument("--json", action="store_true", help="emit policy dogfooding report as JSON")
