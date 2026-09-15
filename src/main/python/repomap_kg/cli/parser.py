"""Argument parser construction for the RepoMap CLI."""

from __future__ import annotations

import argparse

from repomap_kg.cli._local_parser import add_local_commands
from repomap_kg.cli._parser_ops_control import add_ops_control_commands
from repomap_kg.cli._parser_ops_graph import (
    _graph_file_limit,
    _non_negative_offset,
    add_ops_graph_commands,
)
from repomap_kg.cli._parser_sources import add_source_commands
from repomap_kg.cli.storage_parser import add_storage_commands

_graph_file_limit = _graph_file_limit
_non_negative_offset = _non_negative_offset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="repomap-kg",
        description="RepoMap deterministic knowledge graph CLI.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="print the repomap-kg version and exit",
    )
    subparsers = parser.add_subparsers(dest="command")

    discover = subparsers.add_parser(
        "discover",
        help="discover repository files as raw observations",
    )
    discover.add_argument("root", help="repository root to discover")
    discover.add_argument(
        "--profile",
        help="path to an optional RepoMap project profile",
    )
    discover.add_argument(
        "--jsonl",
        action="store_true",
        help="emit raw file observations as JSONL",
    )

    entrypoints = subparsers.add_parser(
        "entrypoints",
        help="list entrypoint files from raw observation JSONL",
    )
    entrypoints.add_argument(
        "jsonl_path",
        help="raw observation JSONL path, or - for stdin",
    )
    entrypoints.add_argument(
        "--json",
        action="store_true",
        help="emit entrypoint records as JSON",
    )

    host_mutators = subparsers.add_parser(
        "host-mutators",
        help="list host-mutating commands from raw observation JSONL",
    )
    host_mutators.add_argument(
        "jsonl_path",
        help="raw observation JSONL path, or - for stdin",
    )
    host_mutators.add_argument(
        "--json",
        action="store_true",
        help="emit host-mutator records as JSON",
    )
    host_mutators.add_argument("--category", help="include only this category")
    host_mutators.add_argument("--tool", help="include only this tool")

    host_mutators_summary = subparsers.add_parser(
        "host-mutators-summary",
        help="summarize host-mutating commands from raw observation JSONL",
    )
    host_mutators_summary.add_argument(
        "jsonl_path",
        help="raw observation JSONL path, or - for stdin",
    )
    host_mutators_summary.add_argument(
        "--json",
        action="store_true",
        help="emit host-mutator summary records as JSON",
    )
    host_mutators_summary.add_argument(
        "--category",
        help="include only this category",
    )
    host_mutators_summary.add_argument("--tool", help="include only this tool")

    files = subparsers.add_parser(
        "files",
        help="list discovered files from raw observation JSONL",
    )
    files.add_argument("jsonl_path", help="raw observation JSONL path, or - for stdin")
    files.add_argument("--role", help="include only files with this role")
    files.add_argument("--language", help="include only files with this language")
    files.add_argument(
        "--generated",
        choices=("include", "exclude", "only"),
        default="include",
        help="control generated-file rows",
    )
    files.add_argument(
        "--json",
        action="store_true",
        help="emit file records as JSON",
    )

    identity = subparsers.add_parser(
        "identity",
        help="print stable project identity metadata",
        description="Print stable RepoMap project identity metadata.",
    )
    identity.add_argument(
        "--json",
        action="store_true",
        help="emit identity metadata as JSON",
    )
    observations = subparsers.add_parser(
        "observations",
        help="work with raw observation JSONL",
    )
    observation_subcommands = observations.add_subparsers(dest="observation_command")
    normalize = observation_subcommands.add_parser(
        "normalize",
        help="normalize raw observation JSONL",
    )
    normalize.add_argument("jsonl_path", help="path to raw observation JSONL")
    normalize.add_argument(
        "--json",
        action="store_true",
        help="emit normalized records as JSON",
    )

    add_source_commands(
        subparsers,
        add_storage_root_argument,
        add_ops_config_arguments,
        add_local_runtime_arguments,
    )

    ops = subparsers.add_parser(
        "ops",
        help="validate local operations configuration",
    )
    ops_subcommands = ops.add_subparsers(dest="ops_command")
    add_ops_control_commands(ops_subcommands)
    add_ops_graph_commands(ops_subcommands, add_ops_config_arguments)

    add_local_commands(subparsers, add_local_runtime_arguments)

    add_storage_commands(
        subparsers,
        add_storage_root_argument,
        add_storage_connection_arguments,
    )

    return parser


def add_storage_root_argument(command: argparse.ArgumentParser) -> None:
    command.add_argument("--root-path", required=True)


def add_storage_connection_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--pg-host")
    command.add_argument("--pg-port")
    command.add_argument("--pg-user")
    command.add_argument("--pg-database")
    command.add_argument("--psql-command", default="psql")


def add_ops_config_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--repo-map-home",
        help="path to REPOMAP_HOME containing *.rp.toml and *.rpl.toml files",
    )
    command.add_argument(
        "--config",
        help="deprecated single-file TOML ops config shim",
    )


def add_local_runtime_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--repo-map-home",
        help="path to REPOMAP_HOME for local runtime files",
    )
