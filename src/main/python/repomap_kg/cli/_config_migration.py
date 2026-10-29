"""Driver-independent CLI for inert CLOE configuration filename planning."""
from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import sys

from repomap_kg.ops.config_layout import plan_cloe_config_filenames
from repomap_kg.ops.config_loading import _read_ops_config_home_payload
from repomap_kg.ops.config_records import OpsConfigError


def dispatch_config_migration_plan(
    args: argparse.Namespace,
    print_error: Callable[..., None],
) -> int | None:
    if args.command != "ops" or getattr(args, "ops_command", None) != "config-migration-plan":
        return None
    try:
        selected = args.repo_map_home or args.config
        home, _, files, _ = _read_ops_config_home_payload(selected)
        occupied = {entry.name for entry in home.iterdir()}
        plan = plan_cloe_config_filenames(files, occupied_names=occupied)
    except OpsConfigError as error:
        codes = ", ".join(sorted({item.code for item in error.diagnostics}))
        print_error(ValueError("configuration filename plan refused: " + codes), file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print_error(ValueError("configuration filename plan refused: plan-input-unavailable"), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(plan, sort_keys=True))
    else:
        print("CLOE configuration filename conversion: " + (
            "ready" if plan["filename_conversion_ready"] else "refused"
        ))
        for change in plan["changes"]:
            print(f"{change['source']!r} -> {change['target']!r} ({change['layer']})")
        for refusal in plan["refusals"]:
            print(f"{refusal['code']}: {refusal['file']!r}")
        print("Read-only plan; apply is unavailable; no files or data changed.")
    return 0 if plan["filename_conversion_ready"] else 1
