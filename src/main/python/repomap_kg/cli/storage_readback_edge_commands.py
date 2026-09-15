"""Canonical edge and host-mutator storage readback handlers."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from types import ModuleType

__all__ = ("dispatch_storage_readback_edge_command",)


def dispatch_storage_readback_edge_command(
    args: argparse.Namespace,
    commands: ModuleType,
    print_cli_error: Callable[..., None],
) -> int | None:
    if args.command != "storage":
        return None

    try:
        if args.storage_command == "edges":
            commands.canonical_edge_filters_from_args(args)
            limit, offset = commands.validate_public_read_window(
                args.limit,
                args.offset,
            )
            records = commands.query_canonical_edge_records(
                commands.psql_args_from_args(args),
                root_path=args.root_path,
                kind=args.kind,
                source_key=args.source_key,
                target_key=args.target_key,
                graph_key_version=args.graph_key_version,
                limit=limit + 1,
                offset=offset,
                psql_command=args.psql_command,
            )
            page = commands.public_read_page(records, limit=limit, offset=offset)
            payload = commands.public_read_page_to_jsonable(
                page,
                result_kind="canonical_edges",
                serialize_items=commands.canonical_edge_records_to_jsonable,
            )
            if args.legacy_json_array:
                payload = commands.canonical_edge_records_to_jsonable(page.items)
            table = "\n".join(
                (
                    commands.format_canonical_edge_table(page.items),
                    commands.format_public_read_page_footer(page),
                )
            )
        elif args.storage_command in {"host-mutators", "host-mutators-summary"}:
            target_key = (
                commands.canonical_host_mutator_filters_from_args(args)
                if args.storage_command == "host-mutators"
                else commands.canonical_host_mutator_summary_target_from_args(args)
            )
            records = commands.query_canonical_host_mutator_edge_records(
                args,
                target_key,
            )
            records = commands.filter_canonical_host_mutator_records(
                records,
                tool=args.tool,
            )
            if args.storage_command == "host-mutators":
                payload = commands.canonical_host_mutator_records_to_jsonable(records)
                table = commands.format_canonical_host_mutator_table(records)
            else:
                summaries = commands.summarize_canonical_host_mutator_records(records)
                payload = commands.canonical_host_mutator_summaries_to_jsonable(
                    summaries
                )
                table = commands.format_canonical_host_mutator_summary_table(summaries)
        else:
            return None
    except commands.StorageSchemaError as error:
        print_cli_error(error, file=commands.sys.stderr)
        return 1

    print(commands.json.dumps(payload, sort_keys=True) if args.json else table)
    return 0
