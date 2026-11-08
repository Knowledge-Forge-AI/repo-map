"""``cloe ops sealing-plan``: a read-only, metadata-only sealing plan.

It resolves the Local home or Server configuration with the backend-neutral
registry loaders (no PostgreSQL driver import), refuses unknown, disabled or
unsupported graphs and unavailable roots cheaply, then runs only the governed
metadata walk. It opens no database, graph lock or worker and writes nothing.
Stdout is canonical ``cloe-sealing-plan-v1`` JSON with ``--json``. MCP exposure:
none.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from common_lore_index.cli._sealing_budget_options import (
    PLAN_OPTIONS,
    add_sealing_budget_options,
    sealing_budget_from_args,
)

PrintError = Callable[..., None]


def add_ops_sealing_plan_command(
    ops_subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
    add_ops_config_arguments: Callable[[argparse.ArgumentParser], None],
) -> None:
    plan = ops_subcommands.add_parser(
        "sealing-plan",
        help="print a read-only metadata-only sealing plan for one configured graph",
        description=(
            "Walks source metadata only (no body reads, database, lock, worker or write) "
            "and prints labelled lower bounds for one successful seal; not a promise."
        ),
    )
    add_ops_config_arguments(plan)
    plan.add_argument("--graph", required=True, help="configured graph id to plan")
    plan.add_argument("--json", action="store_true", help="emit canonical cloe-sealing-plan-v1 JSON")
    add_sealing_budget_options(plan, options=PLAN_OPTIONS)


def _load_config(args: argparse.Namespace) -> object:
    from common_lore_index.ops.config_local import (
        load_graph_registry_config,
        load_graph_registry_config_home,
    )

    if getattr(args, "repo_map_home", None):
        return load_graph_registry_config_home(args.repo_map_home)
    if getattr(args, "config", None):
        return load_graph_registry_config(args.config)
    return load_graph_registry_config_home()


def dispatch_ops_sealing_plan_command(args: argparse.Namespace, print_cli_error: PrintError) -> int | None:
    if getattr(args, "command", None) != "ops" or getattr(args, "ops_command", None) != "sealing-plan":
        return None
    from common_lore_index.ops.sealing_plan import (
        SealingPlanRefusal,
        build_sealing_plan,
        render_plan_text,
    )

    try:
        config = _load_config(args)
        plan = build_sealing_plan(config, args.graph, sealing_budget_from_args(args))
    except (OSError, SealingPlanRefusal, ValueError) as error:
        print_cli_error(error, file=sys.stderr)
        return 1
    if args.json:
        print(plan.canonical_json().decode("utf-8"))
    else:
        print(render_plan_text(plan))
    return 0 if plan.refusal is None else 1


__all__ = ("add_ops_sealing_plan_command", "dispatch_ops_sealing_plan_command")
