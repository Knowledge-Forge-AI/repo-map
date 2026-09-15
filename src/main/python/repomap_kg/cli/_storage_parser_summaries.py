"""Storage summary command parser construction for the RepoMap CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable

from repomap_kg.graph.keys import GRAPH_KEY_VERSION

__all__ = ("add_storage_summary_commands",)

StorageArgumentHelper = Callable[[argparse.ArgumentParser], None]


def add_storage_summary_commands(
    storage_subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
    add_storage_root_argument: StorageArgumentHelper,
    add_storage_connection_arguments: StorageArgumentHelper,
) -> None:
    storage_host_mutators_summary = storage_subcommands.add_parser(
        "host-mutators-summary",
        help="summarize canonical host mutation edges from Postgres storage",
    )
    add_storage_root_argument(storage_host_mutators_summary)
    storage_host_mutators_summary.add_argument(
        "--category",
        help="include only this host mutation category",
    )
    storage_host_mutators_summary.add_argument(
        "--tool",
        help="include only this host mutation tool",
    )
    storage_host_mutators_summary.add_argument(
        "--graph-key-version",
        type=int,
        default=GRAPH_KEY_VERSION,
        help="canonical graph key version; only 1 is currently supported",
    )
    add_storage_connection_arguments(storage_host_mutators_summary)
    storage_host_mutators_summary.add_argument(
        "--json",
        action="store_true",
        help="emit stored host-mutator summary records as JSON",
    )
    storage_summary = storage_subcommands.add_parser(
        "summary",
        help="summarize stored repository graph counts from Postgres storage",
    )
    add_storage_root_argument(storage_summary)
    add_storage_connection_arguments(storage_summary)
    storage_summary.add_argument(
        "--json",
        action="store_true",
        help="emit stored repository graph summary as JSON",
    )
    storage_ruby_summary = storage_subcommands.add_parser(
        "ruby-summary",
        help="summarize stored static Ruby graph facts from Postgres storage",
    )
    add_storage_root_argument(storage_ruby_summary)
    add_storage_connection_arguments(storage_ruby_summary)
    storage_ruby_summary.add_argument(
        "--json",
        action="store_true",
        help="emit stored Ruby summary as JSON",
    )
    storage_js_summary = storage_subcommands.add_parser(
        "js-summary",
        help="summarize stored static JavaScript graph facts from Postgres storage",
    )
    add_storage_root_argument(storage_js_summary)
    add_storage_connection_arguments(storage_js_summary)
    storage_js_summary.add_argument(
        "--json",
        action="store_true",
        help="emit stored JavaScript summary as JSON",
    )
    storage_js_framework_summary = storage_subcommands.add_parser(
        "js-framework-summary",
        help="summarize stored static JS/TS framework evidence from Postgres storage",
    )
    add_storage_root_argument(storage_js_framework_summary)
    add_storage_connection_arguments(storage_js_framework_summary)
    storage_js_framework_summary.add_argument(
        "--json",
        action="store_true",
        help="emit stored JavaScript framework summary as JSON",
    )
    storage_openapi_summary = storage_subcommands.add_parser(
        "openapi-summary",
        help="summarize stored static OpenAPI/Swagger evidence from Postgres storage",
    )
    add_storage_root_argument(storage_openapi_summary)
    add_storage_connection_arguments(storage_openapi_summary)
    storage_openapi_summary.add_argument(
        "--json",
        action="store_true",
        help="emit stored OpenAPI/Swagger summary as JSON",
    )
    storage_terraform_summary = storage_subcommands.add_parser(
        "terraform-summary",
        help="summarize stored static Terraform HCL evidence from Postgres storage",
    )
    add_storage_root_argument(storage_terraform_summary)
    add_storage_connection_arguments(storage_terraform_summary)
    storage_terraform_summary.add_argument(
        "--json",
        action="store_true",
        help="emit stored Terraform HCL summary as JSON",
    )
    storage_python_summary = storage_subcommands.add_parser(
        "python-summary",
        help="summarize stored static Python evidence from Postgres storage",
    )
    add_storage_root_argument(storage_python_summary)
    add_storage_connection_arguments(storage_python_summary)
    storage_python_summary.add_argument(
        "--json",
        action="store_true",
        help="emit stored Python ecosystem/framework summary as JSON",
    )
    storage_nix_summary = storage_subcommands.add_parser(
        "nix-summary",
        help="summarize stored static Nix/flakes evidence from Postgres storage",
    )
    add_storage_root_argument(storage_nix_summary)
    add_storage_connection_arguments(storage_nix_summary)
    storage_nix_summary.add_argument(
        "--json",
        action="store_true",
        help="emit stored Nix/flakes summary as JSON",
    )
    storage_email_summary = storage_subcommands.add_parser(
        "email-summary",
        help="summarize stored local email graph facts from Postgres storage",
    )
    add_storage_root_argument(storage_email_summary)
    add_storage_connection_arguments(storage_email_summary)
    storage_email_summary.add_argument(
        "--json",
        action="store_true",
        help="emit stored email summary as JSON",
    )
    storage_bulk_summary = storage_subcommands.add_parser(
        "bulk-summary",
        help="summarize stored bulk local import runs from Postgres storage",
    )
    add_storage_root_argument(storage_bulk_summary)
    add_storage_connection_arguments(storage_bulk_summary)
    storage_bulk_summary.add_argument(
        "--json",
        action="store_true",
        help="emit stored bulk summary as JSON",
    )
    storage_api_summary = storage_subcommands.add_parser(
        "api-summary",
        help="summarize stored API acquisition runs from Postgres storage",
    )
    add_storage_root_argument(storage_api_summary)
    add_storage_connection_arguments(storage_api_summary)
    storage_api_summary.add_argument(
        "--json",
        action="store_true",
        help="emit stored API summary as JSON",
    )
