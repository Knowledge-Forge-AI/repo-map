"""Driver-independent CLI for CLOE configuration filename planning, apply and recovery."""
from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import sys
from typing import Any

from repomap_kg.ops.config_layout import plan_cloe_config_filenames
from repomap_kg.ops.config_loading import _read_ops_config_home_payload
from repomap_kg.ops.config_migration import (
    SUCCESS_RESULTS, apply_cloe_config_migration, finalize_cloe_config_migration, rollback_cloe_config_migration,
)
from repomap_kg.ops.config_records import OpsConfigError

_MUTATING: dict[str, Callable[..., dict[str, Any]]] = {
    "config-migration-apply": apply_cloe_config_migration,
    "config-migration-rollback": rollback_cloe_config_migration,
    "config-migration-finalize": finalize_cloe_config_migration,
}


def dispatch_config_migration(
    args: argparse.Namespace,
    print_error: Callable[..., None],
) -> int | None:
    if args.command != "ops":
        return None
    command = getattr(args, "ops_command", None)
    if command == "config-migration-plan":
        return _dispatch_plan(args, print_error)
    action = _MUTATING.get(command or "")
    if action is None:
        return None
    result = action(args.repo_map_home, confirmed=args.yes, dry_run=not args.yes)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        _render_text(result)
    if result["result"] in SUCCESS_RESULTS:
        return 0
    codes = ", ".join(dict.fromkeys(item["code"] for item in result["refusals"])) or result["result"]
    print_error(ValueError(f"configuration migration {result['operation']} {result['result']}: {codes}"), file=sys.stderr)
    return 1


def _render_text(result: dict[str, Any]) -> None:
    print(f"CLOE configuration migration {result['operation']}: {result['result']}")
    for change in result["changes"]:
        print(f"{change['source']!r} -> {change['target']!r} ({change['layer']})")
    for refusal in result["refusals"]:
        print(f"{refusal['code']}: {refusal['file']!r}")
    if result["journal_state"] is not None:
        print(f"Journal state: {result['journal_state']}.")
    if result["finalize_pending"]:
        print("Rollback remains available. Private backups of the original files are retained until "
              "ops config-migration-finalize --yes; finalize permanently removes rollback.")
    if result["operation_directory_retained"]:
        print("The operation directory was retained; inspect it before removing it.")
    if result["dry_run"]:
        print("Dry run; no files or data changed. Re-run with --yes to perform this operation.")


def _dispatch_plan(args: argparse.Namespace, print_error: Callable[..., None]) -> int:
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
        print("Read-only plan; no files or data changed. A plan is not apply authority; "
              "ops config-migration-apply revalidates the current home.")
    return 0 if plan["filename_conversion_ready"] else 1
