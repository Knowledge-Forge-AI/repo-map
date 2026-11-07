"""CLI command dispatch for PostgreSQL cloe_lexical subcommands."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import json
import sys
from types import ModuleType

from common_lore_index.cli._resource_report_session import (
    admit_report,
    close_report_session,
    finish_report,
    report_observer_kwargs,
    report_session,
)
from common_lore_index.ops.config_local import declared_storage_backend
from common_lore_index.ops.config_storage import SQLITE_BACKEND
from common_lore_index.ops.local_refresh import LocalRefreshError

_LEXICAL_OPS_COMMANDS = frozenset({"lexical-build", "lexical-query", "lexical-revoke"})


def dispatch_ops_lexical_command(
    args: argparse.Namespace,
    commands: ModuleType,
    print_cli_error: Callable[..., None],
) -> int | None:
    """Dispatch cloe ops lexical-build, lexical-query, and lexical-revoke."""
    if args.command != "ops" or args.ops_command not in _LEXICAL_OPS_COMMANDS:
        return None
    # Delivery follows the fixed stdout and exit code, outside every subject catch block.
    session = report_session(args)
    try:
        code = _dispatch_lexical(args, commands, print_cli_error)
    except BaseException:
        close_report_session(session, preserve_primary=True)
        raise
    if code is None:
        close_report_session(session)
        return None
    return finish_report(session, code)


def _dispatch_lexical(
    args: argparse.Namespace,
    commands: ModuleType,
    print_cli_error: Callable[..., None],
) -> int | None:
    repo_map_home = getattr(args, "repo_map_home", None)
    config_path = getattr(args, "config", None)
    if (
        declared_storage_backend(
            repo_map_home=repo_map_home,
            config_path=config_path,
        )
        == SQLITE_BACKEND
    ):
        print_cli_error(
            LocalRefreshError(
                "postgres-home-required: lexical commands require PostgreSQL storage"
            ),
            file=sys.stderr,
        )
        return 1

    from common_lore_index.ops.lexical_output import (
        format_lexical_build_table,
        format_lexical_query_table,
        format_lexical_revoke_table,
        lexical_build_to_jsonable,
        lexical_query_to_jsonable,
        lexical_revoke_to_jsonable,
    )
    from common_lore_index.ops.lexical_publication import resolve_ops_graph
    from common_lore_index.ops.lexical_service import (
        build_graph_lexical_generation,
        query_graph_lexical_generation,
        revoke_graph_lexical_generation,
    )
    from common_lore_index.retrieval.lexical_envelopes import LexicalQueryRequest
    from common_lore_index.retrieval.query_contracts import (
        CapabilityState,
        FallbackDisclosure,
        QueryMode,
    )
    from common_lore_index.storage.lexical_driver import LexicalStorageError

    try:
        config = commands.load_ops_config_from_args(args)
    except commands.OpsConfigError as error:
        print_cli_error(error, file=sys.stderr)
        return 1

    if args.ops_command == "lexical-build":
        if not getattr(args, "authorize_body", False):
            print_cli_error(
                ValueError("body-authorization-required: pass --authorize-body to build cloe_lexical"),
                file=sys.stderr,
            )
            return 1
        selected_ids = tuple(
            b.strip() for b in (args.binding_id or ()) if isinstance(b, str) and b.strip()
        )
        if not selected_ids:
            print_cli_error(
                ValueError("binding-selection-required: pass at least one --binding to build cloe_lexical"),
                file=sys.stderr,
            )
            return 1
        try:
            portable_store_root = getattr(args, "portable_store_root", None)
            session = admit_report(args, config, overrides=(portable_store_root,))
            outcome = build_graph_lexical_generation(
                config,
                args.graph,
                selected_binding_ids=selected_ids,
                authorize_body=True,
                portable_store_root=portable_store_root,
                **report_observer_kwargs(session),
            )
            build_json = lexical_build_to_jsonable(outcome)
        except (LexicalStorageError, ValueError, OSError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(build_json, sort_keys=True))
        else:
            print(format_lexical_build_table(outcome))
        return 0 if build_json["status"] == "ready" else 1

    if args.ops_command == "lexical-query":
        if not getattr(args, "authorize_body", False):
            print_cli_error(
                ValueError("body-authorization-required: pass --authorize-body to query cloe_lexical"),
                file=sys.stderr,
            )
            return 1
        selected_ids = tuple(
            b.strip() for b in (args.binding_id or ()) if isinstance(b, str) and b.strip()
        )
        if not selected_ids:
            print_cli_error(
                ValueError("binding-selection-required: pass at least one --binding to query cloe_lexical"),
                file=sys.stderr,
            )
            return 1
        try:
            eff_mode = (
                QueryMode.LITERAL_CAPTURED_TEXT
                if args.query_style == "literal_captured_text"
                else QueryMode.RANKED_DISCOVERY
            )
            req_mode = QueryMode(args.requested_mode) if args.requested_mode else None
            fallback = None
            if args.fallback_from_mode or args.fallback_reason:
                if not (args.fallback_from_mode and args.fallback_reason):
                    raise ValueError(
                        "--fallback-from-mode and --fallback-reason must be supplied together"
                    )
                fallback = FallbackDisclosure(
                    caller_selected=True,
                    from_mode=QueryMode(args.fallback_from_mode),
                    to_mode=eff_mode,
                    reason_code=args.fallback_reason,
                ).validate()
            prefixes = tuple(args.path_prefix or ())
            req = LexicalQueryRequest(
                query=args.query,
                query_style=args.query_style,
                requested_mode=req_mode,
                selected_binding_ids=selected_ids,
                source_path_prefix=prefixes[0] if prefixes else None,
                path_prefixes=prefixes,
                limit=args.limit,
                offset=args.offset,
                fallback=fallback,
            ).validate()
            session = admit_report(args, config)
            envelope = query_graph_lexical_generation(
                config, args.graph, req, authorize_body=True,
                **report_observer_kwargs(session),
            )
            query_json = lexical_query_to_jsonable(args.graph, args.query_style, envelope)
        except (LexicalStorageError, ValueError, OSError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(query_json, sort_keys=True))
        else:
            print(format_lexical_query_table(args.graph, args.query_style, envelope))
        return 0 if query_json["status"] == CapabilityState.AVAILABLE.value else 1

    if args.ops_command == "lexical-revoke":
        dry_run = bool(getattr(args, "dry_run", False))
        confirmed = bool(getattr(args, "yes", False))
        if not dry_run and not confirmed:
            print_cli_error(
                ValueError("revoke-confirmation-required: pass --dry-run or --yes to lexical-revoke"),
                file=sys.stderr,
            )
            return 1
        if dry_run and confirmed:
            print_cli_error(
                ValueError("revoke-conflicting-flags: pass either --dry-run or --yes, not both"),
                file=sys.stderr,
            )
            return 1
        try:
            graph = resolve_ops_graph(config, args.graph)
            db_name = graph.database or config.postgres.database
            session = admit_report(args, config)
            rev_outcome = revoke_graph_lexical_generation(
                config,
                args.graph,
                reason=args.reason,
                purge_rows=not dry_run,
                dry_run=dry_run,
                confirmed=confirmed,
                **report_observer_kwargs(session),
            )
            revoke_json = lexical_revoke_to_jsonable(rev_outcome, database=db_name, dry_run=dry_run)
        except (LexicalStorageError, ValueError, OSError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    revoke_json,
                    sort_keys=True,
                )
            )
        else:
            print(format_lexical_revoke_table(rev_outcome, database=db_name, dry_run=dry_run))
        return 0 if revoke_json["status"] in {"revoked", "dry_run"} else 1

    return None


__all__ = ["dispatch_ops_lexical_command"]
