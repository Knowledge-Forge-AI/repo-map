"""Storage summary command handlers for the RepoMap CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from types import ModuleType

__all__ = ("dispatch_storage_summary_command",)


SUMMARY_COMMANDS = {
    "ruby-summary": (
        "query_ruby_summary",
        "ruby_summary_to_jsonable",
        "format_ruby_summary_table",
    ),
    "js-summary": (
        "query_js_summary",
        "js_summary_to_jsonable",
        "format_js_summary_table",
    ),
    "js-framework-summary": (
        "query_js_framework_summary",
        "js_framework_summary_to_jsonable",
        "format_js_framework_summary_table",
    ),
    "openapi-summary": (
        "query_openapi_summary",
        "openapi_summary_to_jsonable",
        "format_openapi_summary_table",
    ),
    "terraform-summary": (
        "query_terraform_summary",
        "terraform_summary_to_jsonable",
        "format_terraform_summary_table",
    ),
    "python-summary": (
        "query_python_summary",
        "python_summary_to_jsonable",
        "format_python_summary_table",
    ),
    "nix-summary": (
        "query_nix_summary",
        "nix_summary_to_jsonable",
        "format_nix_summary_table",
    ),
    "email-summary": (
        "query_email_summary",
        "email_summary_to_jsonable",
        "format_email_summary_table",
    ),
    "bulk-summary": (
        "query_bulk_summary",
        "bulk_summary_to_jsonable",
        "format_bulk_summary_table",
    ),
    "api-summary": (
        "query_api_summary",
        "api_summary_to_jsonable",
        "format_api_summary_table",
    ),
}


def dispatch_storage_summary_command(
    args: argparse.Namespace,
    commands: ModuleType,
    print_cli_error: Callable[..., None],
) -> int | None:
    if args.command != "storage":
        return None
    names = (
        (
            "query_canonical_storage_summary",
            "canonical_storage_summary_to_jsonable",
            "format_canonical_storage_summary_table",
        )
        if args.storage_command == "summary"
        else SUMMARY_COMMANDS.get(args.storage_command)
    )
    if names is None:
        return None

    query, serializer, formatter = (getattr(commands, name) for name in names)
    try:
        summary = query(
            commands.psql_args_from_args(args),
            root_path=args.root_path,
            psql_command=args.psql_command,
        )
    except commands.StorageSchemaError as error:
        print_cli_error(error, file=commands.sys.stderr)
        return 1

    output = (
        commands.json.dumps(serializer(summary), sort_keys=True)
        if args.json
        else formatter(summary)
    )
    print(output)
    return 0
