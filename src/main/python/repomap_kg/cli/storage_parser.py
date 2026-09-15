"""Storage command parser construction for the RepoMap CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable

from repomap_kg.cli._storage_parser_summaries import (
    add_storage_summary_commands,
)
from repomap_kg.graph.keys import GRAPH_KEY_VERSION

__all__ = ("add_storage_commands",)

StorageArgumentHelper = Callable[[argparse.ArgumentParser], None]


def add_storage_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    add_storage_root_argument: StorageArgumentHelper,
    add_storage_connection_arguments: StorageArgumentHelper,
) -> None:
    storage = subparsers.add_parser(
        "storage",
        help="work with RepoMap storage backends",
    )
    storage_subcommands = storage.add_subparsers(dest="storage_command")
    load_files = storage_subcommands.add_parser(
        "load-files",
        help="load raw file observations into Postgres storage",
    )
    load_files.add_argument("jsonl_path", help="raw observation JSONL path")
    load_files.add_argument("--repository-name", required=True)
    add_storage_root_argument(load_files)
    load_files.add_argument("--git-commit")
    add_storage_connection_arguments(load_files)
    load_files.add_argument(
        "--json",
        action="store_true",
        help="emit load summary as JSON",
    )
    storage_explain_canonical_edge = storage_subcommands.add_parser(
        "explain-canonical-edge",
        help="explain one stored canonical graph edge from Postgres storage",
    )
    add_storage_root_argument(storage_explain_canonical_edge)
    storage_explain_canonical_edge.add_argument("--source-key", required=True)
    storage_explain_canonical_edge.add_argument("--kind", required=True)
    storage_explain_canonical_edge.add_argument("--target-key", required=True)
    storage_explain_canonical_edge.add_argument(
        "--identity-metadata-json",
        default="{}",
        help="canonical edge identity metadata JSON object; default {}",
    )
    storage_explain_canonical_edge.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    storage_explain_canonical_edge.add_argument("--evidence-limit", type=int, default=50)
    storage_explain_canonical_edge.add_argument("--evidence-offset", type=int, default=0)
    storage_explain_canonical_edge.add_argument(
        "--legacy-json-object",
        action="store_true",
        help="emit the bounded pre-ARCH7 JSON object during the compatibility interval",
    )
    add_storage_connection_arguments(storage_explain_canonical_edge)
    storage_explain_canonical_edge.add_argument(
        "--json",
        action="store_true",
        help="emit canonical edge explanation as JSON",
    )
    storage_nodes = storage_subcommands.add_parser(
        "nodes",
        help="list stored graph nodes from Postgres storage",
    )
    add_storage_root_argument(storage_nodes)
    storage_nodes.add_argument("--kind", help="include only nodes with this kind")
    storage_nodes.add_argument(
        "--canonical-key",
        help="include only the canonical node with this key",
    )
    storage_nodes.add_argument(
        "--path-prefix",
        help="include only file canonical nodes under this path prefix",
    )
    storage_nodes.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    storage_nodes.add_argument("--limit", type=int, default=50)
    storage_nodes.add_argument("--offset", type=int, default=0)
    storage_nodes.add_argument(
        "--legacy-json-array",
        action="store_true",
        help="emit the bounded pre-ARCH7 JSON array during the compatibility interval",
    )
    add_storage_connection_arguments(storage_nodes)
    storage_nodes.add_argument(
        "--json",
        action="store_true",
        help="emit stored graph node records as JSON",
    )
    storage_neighborhood = storage_subcommands.add_parser(
        "neighborhood",
        help="list a depth-1 graph neighborhood from Postgres storage",
    )
    add_storage_root_argument(storage_neighborhood)
    storage_neighborhood.add_argument(
        "--node",
        required=True,
        help="center canonical node key",
    )
    storage_neighborhood.add_argument(
        "--direction",
        choices=("both", "in", "out"),
        default="both",
        help="edge direction relative to the center node",
    )
    storage_neighborhood.add_argument(
        "--depth",
        type=int,
        default=1,
        help="graph traversal depth; only 1 is currently supported",
    )
    storage_neighborhood.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    storage_neighborhood.add_argument("--node-limit", type=int, default=50)
    storage_neighborhood.add_argument("--node-offset", type=int, default=0)
    storage_neighborhood.add_argument("--edge-limit", type=int, default=50)
    storage_neighborhood.add_argument("--edge-offset", type=int, default=0)
    storage_neighborhood.add_argument(
        "--legacy-json-object",
        action="store_true",
        help="emit the bounded pre-ARCH7 JSON object during the compatibility interval",
    )
    add_storage_connection_arguments(storage_neighborhood)
    storage_neighborhood.add_argument(
        "--json",
        action="store_true",
        help="emit stored graph neighborhood as JSON",
    )
    storage_file_neighborhood = storage_subcommands.add_parser(
        "file-neighborhood",
        help="list a depth-1 graph neighborhood for a stored file path",
    )
    add_storage_root_argument(storage_file_neighborhood)
    storage_file_neighborhood.add_argument(
        "--path",
        required=True,
        help="center repo-relative file path",
    )
    storage_file_neighborhood.add_argument(
        "--direction",
        choices=("both", "in", "out"),
        default="both",
        help="edge direction relative to nodes in the file",
    )
    storage_file_neighborhood.add_argument(
        "--depth",
        type=int,
        default=1,
        help="graph traversal depth; only 1 is currently supported",
    )
    storage_file_neighborhood.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    storage_file_neighborhood.add_argument("--node-limit", type=int, default=50)
    storage_file_neighborhood.add_argument("--node-offset", type=int, default=0)
    storage_file_neighborhood.add_argument("--edge-limit", type=int, default=50)
    storage_file_neighborhood.add_argument("--edge-offset", type=int, default=0)
    storage_file_neighborhood.add_argument(
        "--legacy-json-object",
        action="store_true",
        help="emit the bounded pre-ARCH7 JSON object during the compatibility interval",
    )
    add_storage_connection_arguments(storage_file_neighborhood)
    storage_file_neighborhood.add_argument(
        "--json",
        action="store_true",
        help="emit stored file graph neighborhood as JSON",
    )
    storage_edges = storage_subcommands.add_parser(
        "edges",
        help="list stored relationship edges from Postgres storage",
    )
    add_storage_root_argument(storage_edges)
    storage_edges.add_argument("--kind", help="include only edges with this kind")
    storage_edges.add_argument(
        "--source-key",
        help="include only canonical edges from this source key",
    )
    storage_edges.add_argument(
        "--target-key",
        help="include only canonical edges to this target key",
    )
    storage_edges.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    storage_edges.add_argument("--limit", type=int, default=50)
    storage_edges.add_argument("--offset", type=int, default=0)
    storage_edges.add_argument(
        "--legacy-json-array",
        action="store_true",
        help="emit the bounded pre-ARCH7 JSON array during the compatibility interval",
    )
    add_storage_connection_arguments(storage_edges)
    storage_edges.add_argument(
        "--json",
        action="store_true",
        help="emit stored edge records as JSON",
    )
    storage_host_mutators = storage_subcommands.add_parser(
        "host-mutators",
        help="list canonical host mutation edges from Postgres storage",
    )
    add_storage_root_argument(storage_host_mutators)
    storage_host_mutators.add_argument(
        "--category",
        help="include only this host mutation category",
    )
    storage_host_mutators.add_argument(
        "--tool",
        help="include only this host mutation tool",
    )
    storage_host_mutators.add_argument(
        "--source-key",
        help="include only canonical host mutation edges from this source key",
    )
    storage_host_mutators.add_argument(
        "--target-key",
        help="include only canonical host mutation edges to this target key",
    )
    storage_host_mutators.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    add_storage_connection_arguments(storage_host_mutators)
    storage_host_mutators.add_argument(
        "--json",
        action="store_true",
        help="emit stored host-mutator records as JSON",
    )
    add_storage_summary_commands(
        storage_subcommands,
        add_storage_root_argument,
        add_storage_connection_arguments,
    )
