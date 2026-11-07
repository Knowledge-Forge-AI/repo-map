"""Canonical graph-file command handler."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from types import ModuleType


def dispatch_ops_graph_file_command(
    args: argparse.Namespace,
    commands: ModuleType,
    print_cli_error: Callable[..., None],
) -> int | None:
    if args.command != "ops" or args.ops_command != "graph-files":
        return None

    filters = commands.GraphFileFilters(
        path=args.path,
        path_prefix=args.path_prefix,
        language=args.language,
        role=args.role,
        generated=args.generated,
        executable=args.executable,
        observation_state=args.observation_state,
        ambiguity=args.ambiguity,
    )
    try:
        config = commands.load_ops_config_from_args(args)
        page = commands.query_graph_files(
            config,
            args.graph,
            filters=filters,
            limit=args.limit,
            offset=args.offset,
            psql_command=args.psql_command,
        )
    except (commands.OpsConfigError, commands.OpsRefreshError) as error:
        print_cli_error(error, file=commands.sys.stderr)
        return 1
    if args.json:
        print(
            commands.json.dumps(
                commands.graph_file_page_to_jsonable(page),
                sort_keys=True,
            )
        )
    else:
        print(commands.format_graph_file_table(page))
    return 0


__all__ = ("dispatch_ops_graph_file_command",)
