"""SQLite Local command dispatch: ``ops sqlite-*`` and the Local ``ops`` workflow.

``ops sqlite-init``, ``sqlite-backup``, ``sqlite-restore``, ``sqlite-upgrade``
and ``sqlite-cleanup`` always route here and refuse a PostgreSQL home
(``sqlite-local-home-required``) before any filesystem or database action. A
cleanup that ``refused`` or is ``incomplete`` prints its payload and exits 1.

``ops config-check``, ``graphs``, ``refresh-preflight``, ``refresh-graph`` and
``refresh-enabled`` route here only when the selected home or file declares
``[storage] backend = "sqlite"``; every other home (including an unreadable
one) falls through to the unchanged PostgreSQL dispatcher and its existing
refusal order. PostgreSQL-only options refuse after backend selection and
before any config parse, database open, source capture or worker launch; a
SQLite home's own configuration errors are reported directly instead of being
masked by the PostgreSQL loader's refusal. ``refresh-graph --mode coordinator``
is refused by design: direct serialized refresh is the Local baseline. A
refresh that only settled an already-accepted retained attempt prints one
stderr NOTE; its stdout shape is unchanged.

``repomap_kg.cli.main`` calls this before the PostgreSQL dispatcher loads, so
none of these commands imports the PostgreSQL driver.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from typing import Any

from repomap_kg.ops._refresh_preflight import (
    format_preflight_table,
    preflight_graph,
    preflight_to_jsonable,
)
from repomap_kg.ops.config_local import (
    LocalSqliteConfig,
    declared_storage_backend,
    load_graph_registry_config,
    load_graph_registry_config_home,
)
from repomap_kg.ops.config_storage import SQLITE_BACKEND
from repomap_kg.ops.local_backup import (
    backup_local_graph,
    restore_local_graph,
    upgrade_local_graph,
)
from repomap_kg.ops.local_cleanup import cleanup_local_graph
from repomap_kg.ops.local_ops_status import (
    format_local_config_status_table,
    format_local_graph_registry_table,
    local_config_status_to_jsonable,
    local_graph_registry_status_to_jsonable,
)
from repomap_kg.ops.local_readiness import probe_local_graphs
from repomap_kg.ops.local_refresh import (
    LocalRefreshError,
    LocalRefreshResult,
    initialize_local_graph,
    refresh_local_graph,
)
from repomap_kg.ops.local_refresh_enabled import (
    LocalRefreshOutcome,
    format_local_refresh_enabled_table,
    local_refresh_enabled_to_jsonable,
    refresh_enabled_local_graphs,
)

__all__ = ("dispatch_ops_sqlite_command",)

_ROUTED_COMMANDS = frozenset(
    {"config-check", "graphs", "refresh-preflight", "refresh-graph", "refresh-enabled"}
)
_PrintError = Callable[..., None]


def _local_config(args: argparse.Namespace) -> LocalSqliteConfig:
    repo_map_home = getattr(args, "repo_map_home", None)
    config_path = getattr(args, "config", None)
    if repo_map_home:
        config = load_graph_registry_config_home(repo_map_home)
    elif config_path:
        config = load_graph_registry_config(config_path)
    else:
        config = load_graph_registry_config_home()
    if not isinstance(config, LocalSqliteConfig):
        raise LocalRefreshError(
            "sqlite-local-home-required: this home selects PostgreSQL storage"
        )
    return config


def _refusal(args: argparse.Namespace) -> str | None:
    command = args.ops_command
    if command == "refresh-graph" and getattr(args, "mode", "direct") == "coordinator":
        return "sqlite-local-refresh-rejects-coordinator-mode"
    if getattr(args, "psql_command", None):
        if command in ("refresh-graph", "refresh-enabled"):
            return "sqlite-local-refresh-rejects-psql-command"
        return "sqlite-local-rejects-psql-command"
    if any(
        getattr(args, name, None) is not None
        for name in ("backend_telemetry_fd", "backend_telemetry_ack_fd", "staging_event_fd")
    ):
        return "sqlite-local-refresh-rejects-postgres-telemetry"
    return None


def dispatch_ops_sqlite_command(
    args: argparse.Namespace,
    print_cli_error: _PrintError,
) -> int | None:
    if args.command != "ops":
        return None
    if args.ops_command in _STORE_COMMANDS:
        try:
            payload = _STORE_COMMANDS[args.ops_command](_local_config(args), args)
        except (OSError, ValueError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(_store_summary(payload))
        return 1 if payload["result"] in _FAILED_STORE_RESULTS else 0
    if args.ops_command not in _ROUTED_COMMANDS:
        return None
    repo_map_home = getattr(args, "repo_map_home", None)
    config_path = getattr(args, "config", None)
    if (
        args.ops_command == "refresh-graph"
        and getattr(args, "mode", "direct") == "coordinator"
        and not (repo_map_home or config_path)
    ):
        # The PostgreSQL coordinator path refuses this before reading any home.
        return None
    backend = declared_storage_backend(repo_map_home=repo_map_home, config_path=config_path)
    if backend != SQLITE_BACKEND:
        return None
    refusal = _refusal(args)
    if refusal is not None:
        print_cli_error(LocalRefreshError(refusal), file=sys.stderr)
        return 1
    try:
        return _HANDLERS[args.ops_command](args, print_cli_error)
    except (OSError, ValueError) as error:
        print_cli_error(error, file=sys.stderr)
        return 1


def _store_summary(payload: dict[str, Any]) -> str:
    summary = f"{payload['command']} {payload['graph_id']}: {payload['result']}"
    if "accepted_generation" in payload:
        generation = payload["accepted_generation"]
        summary += f" (accepted generation {generation})" if generation else " (unpublished)"
    if payload["command"] == "sqlite-cleanup":
        attempts = (payload["graph_attempts"], payload["legacy_shared_attempts"])
        removed = sum(item["expired_terminal_removed"] for item in attempts) + (
            payload["orphans"]["stale_removed"] + payload["orphans"]["partial_removed"]
        )
        summary += (
            f" (removed {removed}, durability {payload['durability']}, "
            f"warnings {payload['warning_count']}, refusals {payload['refusal_count']})"
        )
    return summary


_STORE_COMMANDS: dict[str, Callable[[LocalSqliteConfig, argparse.Namespace], dict[str, Any]]] = {
    "sqlite-init": lambda config, args: dict(initialize_local_graph(config, args.graph)),
    "sqlite-backup": lambda config, args: backup_local_graph(config, args.graph, args.output),
    "sqlite-restore": lambda config, args: restore_local_graph(config, args.graph, args.backup),
    "sqlite-upgrade": lambda config, args: upgrade_local_graph(config, args.graph, args.backup_output),
    "sqlite-cleanup": lambda config, args: cleanup_local_graph(config, args.graph, execute=args.yes),
}
# Only sqlite-cleanup returns these; every other store command raises instead.
_FAILED_STORE_RESULTS = frozenset({"refused", "incomplete"})


def _config_check(args: argparse.Namespace, _print_error: _PrintError) -> int:
    config = _local_config(args)
    readiness = probe_local_graphs(config) if args.check_db else None
    if args.json:
        print(json.dumps(local_config_status_to_jsonable(config, readiness=readiness), sort_keys=True))
    else:
        print(format_local_config_status_table(config, readiness=readiness))
    return 0


def _graphs(args: argparse.Namespace, _print_error: _PrintError) -> int:
    config = _local_config(args)
    readiness = probe_local_graphs(config) if args.check_db else None
    if args.json:
        print(
            json.dumps(
                local_graph_registry_status_to_jsonable(config, readiness=readiness),
                sort_keys=True,
            )
        )
    else:
        print(format_local_graph_registry_table(config, readiness=readiness))
    return 0


def _refresh_preflight(args: argparse.Namespace, _print_error: _PrintError) -> int:
    config = _local_config(args)
    result = preflight_graph(config, args.graph)
    payload = preflight_to_jsonable(config, result)
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(format_preflight_table(config, result))
    return 0 if payload["result"] == "success" else 1


def _note_reconciled(results: Sequence[LocalRefreshOutcome], *, name_graph: bool) -> None:
    for result in results:
        if isinstance(result, LocalRefreshResult) and result.reconciled:
            print(
                "NOTE: sqlite-local-attempt-reconciled: accepted generation "
                f"{result.generation} was already published; no new generation was published"
                + (f" (graph {result.graph_id})" if name_graph else ""),
                file=sys.stderr,
            )


def _refresh_graph(args: argparse.Namespace, _print_error: _PrintError) -> int:
    result = refresh_local_graph(_local_config(args), args.graph)
    _note_reconciled((result,), name_graph=False)
    payload = result.to_jsonable()
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"refresh-graph {result.graph_id}: accepted generation {result.generation} "
            f"({result.publication.get('publication_bundle_id')})"
        )
    return 0


def _refresh_enabled(args: argparse.Namespace, _print_error: _PrintError) -> int:
    config = _local_config(args)
    outcomes = refresh_enabled_local_graphs(config)
    _note_reconciled(outcomes, name_graph=True)
    payload = local_refresh_enabled_to_jsonable(config, outcomes)
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(format_local_refresh_enabled_table(config, outcomes))
    return 0 if payload["result"] == "success" else 1


_HANDLERS: dict[str, Callable[[argparse.Namespace, _PrintError], int]] = {
    "config-check": _config_check,
    "graphs": _graphs,
    "refresh-preflight": _refresh_preflight,
    "refresh-graph": _refresh_graph,
    "refresh-enabled": _refresh_enabled,
}
