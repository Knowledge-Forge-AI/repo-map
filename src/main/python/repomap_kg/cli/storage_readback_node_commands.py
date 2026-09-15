"""Canonical node and neighborhood storage readback handlers."""

from __future__ import annotations

import argparse
from dataclasses import replace
from collections.abc import Callable
from types import ModuleType

__all__ = ("dispatch_storage_readback_node_command",)


def dispatch_storage_readback_node_command(
    args: argparse.Namespace,
    commands: ModuleType,
    print_cli_error: Callable[..., None],
) -> int | None:
    if args.command != "storage":
        return None

    try:
        if args.storage_command == "nodes":
            limit, offset = commands.validate_public_read_window(
                args.limit,
                args.offset,
            )
            records = commands.query_canonical_node_records(
                commands.psql_args_from_args(args),
                root_path=args.root_path,
                kind=commands.canonical_node_kind_from_args(args),
                canonical_key=args.canonical_key,
                path_prefix=args.path_prefix,
                graph_key_version=args.graph_key_version,
                limit=limit + 1,
                offset=offset,
                psql_command=args.psql_command,
            )
            page = commands.public_read_page(records, limit=limit, offset=offset)
            payload = commands.public_read_page_to_jsonable(
                page,
                result_kind="canonical_nodes",
                serialize_items=commands.canonical_node_records_to_jsonable,
            )
            if args.legacy_json_array:
                payload = commands.canonical_node_records_to_jsonable(page.items)
            table = "\n".join(
                (
                    commands.format_canonical_node_table(page.items),
                    commands.format_public_read_page_footer(page),
                )
            )
        elif args.storage_command == "neighborhood":
            commands.canonical_neighborhood_filters_from_args(args)
            node_limit, node_offset = commands.validate_public_read_window(
                args.node_limit,
                args.node_offset,
            )
            edge_limit, edge_offset = commands.validate_public_read_window(
                args.edge_limit,
                args.edge_offset,
            )
            record = commands.query_canonical_neighborhood(
                commands.psql_args_from_args(args),
                root_path=args.root_path,
                node=args.node,
                direction=args.direction,
                depth=args.depth,
                graph_key_version=args.graph_key_version,
                node_limit=node_limit + 1,
                node_offset=node_offset,
                edge_limit=edge_limit + 1,
                edge_offset=edge_offset,
                psql_command=args.psql_command,
            )
            node_page = commands.public_read_page(
                record.nodes,
                limit=node_limit,
                offset=node_offset,
            )
            edge_page = commands.public_read_page(
                record.edges,
                limit=edge_limit,
                offset=edge_offset,
            )
            record = replace(record, nodes=node_page.items, edges=edge_page.items)
            result = commands.canonical_neighborhood_to_jsonable(record)
            payload = commands.public_embedded_read_result_to_jsonable(
                result,
                result_kind="canonical_neighborhood",
                collection_pages={"nodes": node_page, "edges": edge_page},
            )
            if args.legacy_json_object:
                payload = result
            table = "\n".join(
                (
                    commands.format_canonical_neighborhood_table(record),
                    commands.format_public_read_page_footer(
                        node_page,
                        collection="nodes",
                    ),
                    commands.format_public_read_page_footer(
                        edge_page,
                        collection="edges",
                    ),
                )
            )
        elif args.storage_command == "file-neighborhood":
            node_limit, node_offset = commands.validate_public_read_window(
                args.node_limit,
                args.node_offset,
            )
            edge_limit, edge_offset = commands.validate_public_read_window(
                args.edge_limit,
                args.edge_offset,
            )
            record = commands.query_canonical_neighborhood(
                commands.psql_args_from_args(args),
                root_path=args.root_path,
                node=commands.canonical_file_neighborhood_node_from_args(args),
                direction=args.direction,
                depth=args.depth,
                graph_key_version=args.graph_key_version,
                node_limit=node_limit + 1,
                node_offset=node_offset,
                edge_limit=edge_limit + 1,
                edge_offset=edge_offset,
                psql_command=args.psql_command,
            )
            node_page = commands.public_read_page(
                record.nodes,
                limit=node_limit,
                offset=node_offset,
            )
            edge_page = commands.public_read_page(
                record.edges,
                limit=edge_limit,
                offset=edge_offset,
            )
            record = replace(record, nodes=node_page.items, edges=edge_page.items)
            result = commands.canonical_neighborhood_to_jsonable(record)
            payload = commands.public_embedded_read_result_to_jsonable(
                result,
                result_kind="canonical_neighborhood",
                collection_pages={"nodes": node_page, "edges": edge_page},
            )
            if args.legacy_json_object:
                payload = result
            table = "\n".join(
                (
                    commands.format_canonical_neighborhood_table(record),
                    commands.format_public_read_page_footer(
                        node_page,
                        collection="nodes",
                    ),
                    commands.format_public_read_page_footer(
                        edge_page,
                        collection="edges",
                    ),
                )
            )
        else:
            return None
    except commands.StorageSchemaError as error:
        print_cli_error(error, file=commands.sys.stderr)
        return 1

    print(commands.json.dumps(payload, sort_keys=True) if args.json else table)
    return 0
