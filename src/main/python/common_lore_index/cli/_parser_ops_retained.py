"""Explicit inspection and settlement of one retained Server attempt."""

from __future__ import annotations

import argparse
from collections.abc import Callable


def _positive_attempt(value: str) -> int:
    try:
        attempt = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("attempt must be a positive integer") from error
    if not 1 <= attempt <= 2_147_483_647:
        raise argparse.ArgumentTypeError("attempt must be between 1 and 2147483647")
    return attempt


def add_ops_retained_attempt_commands(
    ops_subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
    add_config_arguments: Callable[[argparse.ArgumentParser], None],
) -> None:
    parser = ops_subcommands.add_parser(
        "retained-attempt", help="inspect or settle one known Server retained attempt",
    )
    actions = parser.add_subparsers(dest="retained_attempt_command", required=True)
    for action in ("inspect", "settle"):
        command = actions.add_parser(action, help=f"{action} one explicitly selected attempt")
        add_config_arguments(command)
        command.add_argument("--graph", required=True, help="configured Server graph id")
        command.add_argument("--operation-id", required=True, help="known operation identity")
        command.add_argument("--attempt", required=True, type=_positive_attempt)
        command.add_argument("--psql-command", help="explicit psql readback executable or wrapper")
        command.add_argument("--json", action="store_true", help="emit a categorical result")


__all__ = ("add_ops_retained_attempt_commands",)
