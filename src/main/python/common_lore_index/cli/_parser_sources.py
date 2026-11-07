"""Source, bulk, API, GitHub, MCP, and server parser construction for the RepoMap CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable

__all__ = ("add_source_commands",)

StorageArgumentHelper = Callable[[argparse.ArgumentParser], None]


def add_source_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    add_storage_root_argument: StorageArgumentHelper,
    add_ops_config_arguments: StorageArgumentHelper,
    add_local_runtime_arguments: StorageArgumentHelper,
) -> None:
    sources = subparsers.add_parser(
        "sources",
        help="work with explicitly configured source ingestion",
    )
    source_subcommands = sources.add_subparsers(dest="source_command")
    ingest_feed = source_subcommands.add_parser(
        "ingest-feed",
        help="fetch one configured policy-approved feed source",
    )
    ingest_feed.add_argument(
        "--config",
        required=True,
        help="path to a configured feed source TOML file",
    )
    add_storage_root_argument(ingest_feed)
    ingest_feed.add_argument(
        "--artifact-dir",
        help="artifact retention directory inside --root-path",
    )
    ingest_feed.add_argument(
        "--json",
        action="store_true",
        help="emit feed ingestion summary as JSON",
    )
    import_archive = source_subcommands.add_parser(
        "import-archive",
        help="import one configured local saved-page/static artifact source",
    )
    import_archive.add_argument(
        "--config",
        required=True,
        help="path to a configured local artifact source TOML file",
    )
    add_storage_root_argument(import_archive)
    import_archive.add_argument(
        "--json",
        action="store_true",
        help="emit local artifact import summary as JSON",
    )
    import_warc = source_subcommands.add_parser(
        "import-warc",
        help="import one configured local WARC artifact source",
    )
    import_warc.add_argument(
        "--config",
        required=True,
        help="path to a configured local WARC source TOML file",
    )
    add_storage_root_argument(import_warc)
    import_warc.add_argument(
        "--json",
        action="store_true",
        help="emit local WARC import summary as JSON",
    )

    bulk = subparsers.add_parser(
        "bulk",
        help="plan and import explicitly configured local corpora",
    )
    bulk_subcommands = bulk.add_subparsers(dest="bulk_command")
    bulk_plan = bulk_subcommands.add_parser(
        "plan",
        help="plan one explicitly configured local bulk corpus import",
    )
    bulk_plan.add_argument(
        "--config",
        required=True,
        help="path to a local bulk corpus TOML config",
    )
    bulk_plan.add_argument(
        "--json",
        action="store_true",
        help="emit bulk plan manifest as JSON",
    )
    bulk_import = bulk_subcommands.add_parser(
        "import",
        help="import one explicitly configured local bulk corpus",
    )
    bulk_import.add_argument(
        "--config",
        required=True,
        help="path to a local bulk corpus TOML config",
    )
    add_storage_root_argument(bulk_import)
    bulk_import.add_argument(
        "--json",
        action="store_true",
        help="emit bulk import summary as JSON",
    )

    api = subparsers.add_parser(
        "api",
        help="plan and acquire explicitly configured documented API sources",
    )
    api_subcommands = api.add_subparsers(dest="api_command")
    api_plan = api_subcommands.add_parser(
        "plan",
        help="plan one explicitly configured documented API acquisition",
    )
    api_plan.add_argument(
        "--config",
        required=True,
        help="path to a documented API source TOML config",
    )
    api_plan.add_argument(
        "--json",
        action="store_true",
        help="emit API request plan as JSON",
    )
    api_acquire = api_subcommands.add_parser(
        "acquire",
        help="acquire one explicitly configured documented API fixture source",
    )
    api_acquire.add_argument(
        "--config",
        required=True,
        help="path to a documented API source TOML config",
    )
    add_storage_root_argument(api_acquire)
    api_acquire.add_argument(
        "--json",
        action="store_true",
        help="emit API acquisition summary as JSON",
    )

    github = subparsers.add_parser(
        "github",
        help="plan and acquire explicitly configured GitHub REST fixture sources",
    )
    github_subcommands = github.add_subparsers(dest="github_command")
    github_plan = github_subcommands.add_parser(
        "plan",
        help="plan one explicitly configured GitHub REST fixture acquisition",
    )
    github_plan.add_argument(
        "--config",
        required=True,
        help="path to a GitHub REST source TOML config",
    )
    github_plan.add_argument(
        "--json",
        action="store_true",
        help="emit GitHub API request plan as JSON",
    )
    github_acquire = github_subcommands.add_parser(
        "acquire",
        help="acquire one explicitly configured GitHub REST fixture source",
    )
    github_acquire.add_argument(
        "--config",
        required=True,
        help="path to a GitHub REST source TOML config",
    )
    add_storage_root_argument(github_acquire)
    github_acquire.add_argument(
        "--json",
        action="store_true",
        help="emit GitHub API acquisition summary as JSON",
    )

    mcp = subparsers.add_parser(
        "mcp",
        help="serve local read-only MCP tools",
    )
    mcp_subcommands = mcp.add_subparsers(dest="mcp_command")
    mcp_serve = mcp_subcommands.add_parser(
        "serve",
        help="serve read-only MCP over stdio",
    )
    add_ops_config_arguments(mcp_serve)

    server = subparsers.add_parser(
        "server",
        help="serve the long-running local RepoMap runtime API",
    )
    server_subcommands = server.add_subparsers(dest="server_command")
    server_serve = server_subcommands.add_parser(
        "serve",
        help="serve local read-only health/status endpoints",
    )
    add_local_runtime_arguments(server_serve)
    server_serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="server bind host; defaults to localhost",
    )
    server_serve.add_argument(
        "--port",
        type=int,
        default=55880,
        help="server port; defaults to 55880",
    )
    server_serve.add_argument(
        "--container-internal-bind",
        action="store_true",
        help="allow 0.0.0.0 only for generated container-internal serving",
    )
