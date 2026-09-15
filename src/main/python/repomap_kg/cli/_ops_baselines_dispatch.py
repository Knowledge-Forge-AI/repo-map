"""Ops baseline, drift, server memory, and policy dogfood dispatch for RepoMap CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import sys
from types import ModuleType

__all__ = ("dispatch_ops_baselines_command",)


def dispatch_ops_baselines_command(
    args: argparse.Namespace,
    commands: ModuleType,
    print_cli_error: Callable[..., None],
) -> int | None:
    if args.command != "ops":
        return None

    if args.ops_command == "graph-baseline":
        try:
            config = commands.load_ops_config_from_args(args)
            summary = commands.query_graph_summary(
                config,
                args.graph,
                psql_command=args.psql_command,
            )
        except (commands.OpsConfigError, commands.OpsRefreshError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        payload = commands.graph_baseline_to_jsonable(config, summary)
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(commands.format_graph_summary_table(config, summary))
        return 0 if summary.result == "success" else 1

    if args.ops_command == "baseline-save":
        try:
            config = commands.load_ops_config_from_args(args)
            result = commands.save_graph_baselines(
                config,
                args.graph,
                kind=args.kind,
                psql_command=args.psql_command,
            )
        except (commands.OpsConfigError, commands.OpsRefreshError, OSError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        payload = commands.baseline_save_to_jsonable(config, result)
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(commands.format_baseline_save_table(config, result))
        return 0 if result.result == "success" else 1

    if args.ops_command == "baseline-prune":
        if args.dry_run and args.yes:
            print("ERROR: --dry-run and --yes cannot be used together", file=sys.stderr)
            return 1
        try:
            config = commands.load_ops_config_from_args(args)
            result = commands.prune_graph_baselines(
                config,
                args.graph,
                kind=args.kind,
                keep=args.keep,
                dry_run=not args.yes,
            )
        except (commands.OpsConfigError, commands.OpsRefreshError, OSError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        payload = commands.baseline_prune_to_jsonable(config, result)
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(commands.format_baseline_prune_table(config, result))
        return 0 if result.result == "success" else 1

    if args.ops_command == "drift-check":
        try:
            config = commands.load_ops_config_from_args(args)
            baseline = commands._read_json_file(args.baseline_file, "baseline")
            preflight_baseline = None
            if args.include_preflight and not args.preflight_baseline_file:
                raise ValueError(
                    "--preflight-baseline-file is required when "
                    "--include-preflight is used"
                )
            if args.preflight_baseline_file and not args.include_preflight:
                raise ValueError(
                    "--preflight-baseline-file requires --include-preflight"
                )
            if args.include_preflight:
                preflight_baseline = commands._read_json_file(
                    args.preflight_baseline_file,
                    "preflight baseline",
                )
            drift_check = commands.query_drift_check(
                config,
                args.graph,
                baseline=baseline,
                include_preflight=args.include_preflight,
                preflight_baseline=preflight_baseline,
                psql_command=args.psql_command,
            )
        except (commands.OpsConfigError, commands.OpsRefreshError, ValueError, OSError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    commands.drift_check_to_jsonable(config, drift_check),
                    sort_keys=True,
                )
            )
        else:
            print(commands.format_drift_check_table(config, drift_check))
        if drift_check.result == "success":
            return 0
        if drift_check.result == "warning":
            return 2
        return 1

    if args.ops_command == "server-memory-summary":
        try:
            payload = commands.server_memory_summary_payload(
                config_path=args.config,
                config_home=args.repo_map_home,
            )
        except (commands.OpsConfigError, ValueError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(commands.format_server_memory_summary_table(payload))
        return 0

    if args.ops_command == "server-memory-search":
        try:
            payload = commands.server_memory_search_payload(
                config_path=args.config,
                config_home=args.repo_map_home,
                query=args.query,
                kind=args.kind,
                limit=args.limit,
                offset=args.offset,
            )
        except (commands.OpsConfigError, ValueError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(commands.format_server_memory_search_table(payload))
        return 0

    if args.ops_command == "policy-dogfood":
        try:
            payload = commands.policy_dogfood_payload(
                config_path=args.config,
                config_home=args.repo_map_home,
                graph_id=args.graph,
            )
        except (commands.OpsConfigError, ValueError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(commands.format_policy_dogfood_table(payload))
        return 0

    return None
