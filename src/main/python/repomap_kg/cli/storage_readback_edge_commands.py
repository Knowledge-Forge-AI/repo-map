"""Canonical edge and host-mutator storage readback handlers."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from types import ModuleType

from repomap_kg.ops.config import OpsConfigError, load_ops_config_home
from repomap_kg.ops.resolved_config import resolve_ops_config
from repomap_kg.runtime.postgres_route import readback_postgres_authority
from repomap_kg.storage.errors import StorageSchemaError

__all__ = ("dispatch_storage_readback_edge_command",)


def _storage_readback_connection(
    args: argparse.Namespace,
    commands: ModuleType,
) -> tuple[list[str], str | None, str, str | None]:
    home = getattr(args, "repo_map_home", None)
    graph_id = getattr(args, "graph", None)
    if not home:
        if graph_id:
            raise StorageSchemaError("--graph requires --repo-map-home")
        if not args.root_path:
            raise StorageSchemaError("one of --root-path or --graph is required")
        return commands.psql_args_from_args(args), None, args.root_path, None
    if any(getattr(args, name, None) is not None for name in (
        "pg_host", "pg_port", "pg_user", "pg_database",
    )):
        raise StorageSchemaError(
            "--repo-map-home cannot be combined with explicit PostgreSQL connection options"
        )
    try:
        config = load_ops_config_home(home)
        authority = readback_postgres_authority(config)
        if graph_id:
            graph = resolve_ops_config(config).graph(graph_id)
            root_path = (
                f"graph:{graph.source.id}" if graph.source.explicit_source_bindings
                else graph.source.root_path_expanded or graph.source.root_path
            )
            repository_identity = str(graph.repository_identity)
            database = str(graph.database)
        else:
            if not args.root_path:
                raise StorageSchemaError("one of --root-path or --graph is required")
            root_path = args.root_path
            repository_identity = None
            database = config.postgres.database
    except KeyError:
        raise StorageSchemaError("configured graph was not found") from None
    except (OpsConfigError, ValueError):
        raise StorageSchemaError(
            "setup-owned local readback authority is unavailable or unsafe"
        ) from None
    return (
        authority.postgres.psql_args_for_database(database),
        authority.password,
        root_path,
        repository_identity,
    )


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
            psql_args, password, root_path, identity = _storage_readback_connection(args, commands)
            records = commands.query_canonical_edge_records(
                psql_args,
                root_path=root_path,
                **({"repository_identity": identity} if identity is not None else {}),
                kind=args.kind,
                source_key=args.source_key,
                target_key=args.target_key,
                graph_key_version=args.graph_key_version,
                limit=limit + 1,
                offset=offset,
                psql_command=args.psql_command,
                **({"password": password} if password is not None else {}),
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
