"""Categorical CLI output for explicit Server retained-attempt recovery."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
from types import ModuleType
from typing import Literal

from common_lore_index.ops.config_local import (
    LocalSqliteConfig, load_graph_registry_config, load_graph_registry_config_home,
)

_Operation = Literal["inspect", "settle"]


def _operation(args: argparse.Namespace) -> _Operation:
    return "settle" if getattr(args, "retained_attempt_command", None) == "settle" else "inspect"


def _emit(payload: Mapping[str, str], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"retained-attempt {payload['operation']}: {payload['result']} ({payload['reason']})")


def refuse_retained_attempt(args: argparse.Namespace, reason: str) -> int:
    """Emit a closed refusal before any recovery or PostgreSQL import."""
    _emit({
        "operation": _operation(args), "result": "refused", "reason": reason,
        "retention_state": "unavailable", "artifact_proof": "not-checked",
        "publication_proof": "not-checked", "metadata_write_state": "not-attempted",
    }, as_json=bool(getattr(args, "json", False)))
    return 1


def dispatch_ops_retained_attempt_command(
    args: argparse.Namespace,
    _commands: ModuleType,
    _print_cli_error: Callable[..., None],
) -> int | None:
    if getattr(args, "command", None) != "ops" or getattr(args, "ops_command", None) != "retained-attempt":
        return None
    try:
        if getattr(args, "repo_map_home", None):
            config = load_graph_registry_config_home(args.repo_map_home)
        elif getattr(args, "config", None):
            config = load_graph_registry_config(args.config)
        else:
            config = load_graph_registry_config_home()
    except Exception:
        return refuse_retained_attempt(args, "invalid-config")
    if isinstance(config, LocalSqliteConfig):
        return refuse_retained_attempt(args, "sqlite-backend")
    try:
        # Local homes and invalid configuration never load this Server closure.
        from common_lore_index.ops.retained_attempt_recovery import recover_server_retained_attempt

        recovery = recover_server_retained_attempt(
            config, args.graph, args.operation_id, args.attempt,
            settle=_operation(args) == "settle",
            psql_command=getattr(args, "psql_command", None),
        )
    except Exception:
        return refuse_retained_attempt(args, "recovery-unavailable")
    _emit(recovery.to_jsonable(), as_json=bool(getattr(args, "json", False)))
    return recovery.exit_code


__all__ = ("dispatch_ops_retained_attempt_command", "refuse_retained_attempt")
