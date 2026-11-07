"""Ops control, coordinator, and job command dispatch for the RepoMap CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import sys
from types import ModuleType

__all__ = ("dispatch_ops_control_command",)


def dispatch_ops_control_command(
    args: argparse.Namespace,
    commands: ModuleType,
    print_cli_error: Callable[..., None],
) -> int | None:
    if args.command != "ops":
        return None

    if args.ops_command in {
        "coordinator-control-status",
        "coordinator-control-init",
        "coordinator-control-upgrade",
    }:
        try:
            if args.ops_command == "coordinator-control-status":
                payload = commands.coordinator_control_status(args.repo_map_home)
            elif args.ops_command == "coordinator-control-init":
                payload = commands.initialize_coordinator_control(args.repo_map_home)
            else:
                payload = commands.upgrade_coordinator_control(
                    args.repo_map_home,
                    backup_first=args.backup_first,
                    confirmed=args.yes,
                    dry_run=args.dry_run,
                    reason=args.reason,
                )
        except commands.CoordinatorControlError as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(commands.format_coordinator_control_table(payload))
        return 0 if payload["result"] in {"ready", "planned"} else 1

    if args.ops_command in {
        "coordinator-job-status",
        "coordinator-job-wait",
        "coordinator-job-cancel",
    }:
        try:
            if args.ops_command == "coordinator-job-status":
                payload = commands.coordinator_job_status(args.repo_map_home, args.job_id)
            elif args.ops_command == "coordinator-job-wait":
                payload = commands.wait_for_coordinator_job(
                    args.repo_map_home,
                    args.job_id,
                    wait_timeout_seconds=args.wait_timeout_seconds,
                )
            else:
                payload = commands.cancel_coordinator_job(args.repo_map_home, args.job_id)
        except (commands.CoordinatorClientError, commands.CoordinatorModeError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(commands.format_coordinator_job_table(payload))
        return 0 if payload["result"] != "failure" else 1

    if args.ops_command == "coordinator-jobs":
        try:
            payload = commands.list_coordinator_jobs(
                args.repo_map_home,
                limit=args.limit,
                graph_id=args.graph_id,
                cursor=args.cursor,
            )
        except (commands.CoordinatorClientError, commands.CoordinatorModeError, ValueError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(commands.format_coordinator_jobs_table(payload))
        return 0

    return None
