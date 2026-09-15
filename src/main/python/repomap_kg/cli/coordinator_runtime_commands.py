"""Foreground coordinator and health CLI dispatch."""

from __future__ import annotations

import json
from collections.abc import Callable
from types import ModuleType
from typing import Any


def dispatch_coordinator_runtime_command(
    args: Any,
    commands: ModuleType,
    *,
    print_error: Callable[[Exception], None],
) -> int | None:
    """Dispatch foreground coordinator commands or decline unrelated input."""

    if args.command != "ops" or args.ops_command not in {
        "coordinator-serve",
        "coordinator-health",
    }:
        return None
    if args.ops_command == "coordinator-health":
        try:
            payload = commands.coordinator_health(args.repo_map_home)
        except (commands.CoordinatorClientError, commands.CoordinatorModeError) as error:
            print_error(error)
            return 1
        print(
            json.dumps(payload, sort_keys=True)
            if args.json
            else commands.format_coordinator_health_table(payload)
        )
        return 0 if payload["result"] == "ready" else 1

    if args.service_package_environment and args.service_package_psql is None:
        print_error(
            commands.CoordinatorModeError(
                "coordinator_service_package_contract_invalid"
            )
        )
        return 1
    if args.service_package_environment:
        commands.apply_service_environment(commands.os.environ)

    def report_ready(payload: dict[str, object]) -> None:
        if args.json:
            print(json.dumps(payload, sort_keys=True), flush=True)
            return
        recovery = payload.get("startup_recovery")
        if not isinstance(recovery, dict):
            raise commands.CoordinatorModeError(
                "coordinator_ready_payload_invalid"
            )
        print(
            "RepoMap local coordinator ready\n"
            f"startup_recovery_scanned={recovery['scanned']}\n"
            f"startup_recovery_resolved={recovery['resolved']}\n"
            f"startup_recovery_pending={recovery['pending']}\n"
            f"startup_recovery_route_changed={recovery['route_changed']}\n"
            f"startup_recovery_unavailable={recovery['unavailable']}",
            flush=True,
        )

    try:
        if args.service_package_psql is None:
            commands.serve_configured_coordinator(
                args.repo_map_home,
                report_ready,
                **(
                    {"startup_wait_seconds": args.startup_wait_seconds}
                    if args.startup_wait_seconds
                    else {}
                ),
            )
        else:
            commands.serve_configured_coordinator(
                args.repo_map_home,
                report_ready,
                psql_path=args.service_package_psql,
                **(
                    {"startup_wait_seconds": args.startup_wait_seconds}
                    if args.startup_wait_seconds
                    else {}
                ),
            )
    except commands.CoordinatorModeError as error:
        print_error(error)
        return 1
    return 0


__all__ = ["dispatch_coordinator_runtime_command"]
