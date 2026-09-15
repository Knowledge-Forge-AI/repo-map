"""Platform-neutral coordinator service-package CLI dispatch."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from types import ModuleType


def dispatch_coordinator_service_command(
    args: argparse.Namespace,
    commands: ModuleType,
    print_error: Callable[..., None],
) -> int | None:
    """Dispatch one neutral service action, or decline unrelated commands."""

    if not (
        getattr(args, "command", None) == "ops"
        and getattr(args, "ops_command", None) == "coordinator-service"
    ):
        return None
    try:
        result = commands.run_coordinator_service_action(
            args.coordinator_service_action,
            args.repo_map_home,
        )
    except commands.ServicePackageError as error:
        print_error(error, file=commands.sys.stderr)
        return 1
    if isinstance(result, str):
        commands.sys.stdout.write(result)
        return 0
    if args.json:
        print(commands.json.dumps(result.as_dict(), sort_keys=True))
    else:
        print(commands.format_service_action_table(result))
    return 0 if result.result == "success" else 1


__all__ = ["dispatch_coordinator_service_command"]
