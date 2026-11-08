"""Opt-in ``--sealing-max-*`` options and their pre-configuration refusals.

The options attach only to single-graph ``ops refresh-graph`` (Local and Server
direct) and to the read-only ``ops sealing-plan``. Values are unsigned ASCII
digits of at most 19 characters within the ``SealingBudget`` ranges; anything
else is the usage error ``invalid sealing budget: <option>``. Conflicts are
refused by :func:`refuse_sealing_conflicts` before any configuration work:

* ``resource-report-schema-requires-report``: an explicit schema without a report;
* ``sealing-budget-unsupported-mode``: a budget with the coordinator mode;
* ``sealing-budget-requires-report-schema-2``: a budget plus a report without
  explicitly selected schema 2 (v1 cannot describe an active sealing limit).

Without any option nothing is forwarded and output stays byte-identical.
"""

from __future__ import annotations

import argparse
from typing import Any, Callable

from common_lore_index.artifacts.sealing_governance import (
    MAX_COUNTER,
    MAX_ELAPSED_MS,
    SealingBudget,
    governance_kwargs,
)

SEALING_BUDGET_OPTIONS = (
    ("--sealing-max-read-bytes", "max_read_bytes", "bytes returned by the owned sealing readers"),
    ("--sealing-max-write-bytes", "max_write_bytes", "bytes admitted to the owned store writer"),
    ("--sealing-max-opens", "max_opens", "descriptor, listing and temporary-file opens"),
    ("--sealing-max-entries", "max_directory_entries", "directory entries visited across all walks"),
    ("--sealing-max-elapsed-ms", "max_elapsed_ms", "cooperative elapsed milliseconds"),
)
PLAN_OPTIONS = frozenset({"--sealing-max-entries", "--sealing-max-opens", "--sealing-max-elapsed-ms"})


def _budget_value(option: str, maximum: int) -> Callable[[str], int]:
    def parse(text: str) -> int:
        if not (0 < len(text) <= 19 and text.isascii() and text.isdigit()):
            raise argparse.ArgumentTypeError(f"invalid sealing budget: {option}")
        value = int(text)
        if value > maximum:
            raise argparse.ArgumentTypeError(f"invalid sealing budget: {option}")
        return value

    return parse


def add_sealing_budget_options(
    command: argparse.ArgumentParser, *, options: frozenset[str] | None = None
) -> None:
    """Attach the selected ``--sealing-max-*`` options (all of them by default)."""

    for option, field, meaning in SEALING_BUDGET_OPTIONS:
        if options is not None and option not in options:
            continue
        maximum = MAX_ELAPSED_MS if field == "max_elapsed_ms" else MAX_COUNTER
        command.add_argument(
            option, dest=f"sealing_{field}", type=_budget_value(option, maximum), default=None,
            metavar="N", help=f"opt-in governed sealing ceiling: {meaning}",
        )


def sealing_budget_from_args(args: argparse.Namespace) -> SealingBudget | None:
    values = {field: getattr(args, f"sealing_{field}", None) for _, field, _ in SEALING_BUDGET_OPTIONS}
    budget = SealingBudget(**values)
    return None if budget.empty else budget


def sealing_budget_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    """Forward ``sealing_budget`` only when an option was supplied."""

    return governance_kwargs(sealing_budget_from_args(args))


def refuse_sealing_conflicts(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Exit with a bounded usage error before configuration work; no-op otherwise."""

    if getattr(args, "resource_report_schema", None) is not None and getattr(
        args, "resource_report", None
    ) is None:
        parser.error("resource-report-schema-requires-report")
    if getattr(args, "command", None) != "ops" or getattr(args, "ops_command", None) != "refresh-graph":
        return
    if sealing_budget_from_args(args) is None:
        return
    if getattr(args, "mode", "direct") != "direct":
        parser.error("sealing-budget-unsupported-mode")
    if getattr(args, "resource_report", None) is not None and args.resource_report_schema != 2:
        parser.error("sealing-budget-requires-report-schema-2")


__all__ = (
    "PLAN_OPTIONS",
    "SEALING_BUDGET_OPTIONS",
    "add_sealing_budget_options",
    "refuse_sealing_conflicts",
    "sealing_budget_from_args",
    "sealing_budget_kwargs",
)
