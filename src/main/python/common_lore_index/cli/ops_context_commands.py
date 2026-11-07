"""CLI command dispatch for cloe ops context-pack and cloe ops context-select (W4 §2.1-2.2)."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Iterator

from common_lore_index.cli._resource_report_session import (
    ResourceReportSession,
    admit_report,
    close_report_session,
    finish_report,
    report_session,
)
from common_lore_index.ops.config_local import (
    LocalSqliteConfig,
    declared_storage_backend,
    load_graph_registry_config,
    load_graph_registry_config_home,
    local_graph_binding,
    sqlite_graph_database_path,
)
from common_lore_index.ops.config_records import OpsConfigError
from common_lore_index.ops.resource_view._context_projection import (
    project_compact_context,
    unfinished_compact_context,
)
from common_lore_index.retrieval.advisory_freshness import FreshnessCheckConfig
from common_lore_index.retrieval.context_admission import OmissionCounter
from common_lore_index.retrieval.context_assembly import (
    ContextReadPort,
    build_compact_context,
    select_context_sources,
)
from common_lore_index.retrieval.context_budget import (
    finalize_packet_within_budget,
    serialize_compact_json,
    validate_budget_bytes,
)
from common_lore_index.retrieval.context_contracts import (
    ContextRequest,
    ContextRequestError,
    MAX_BINDINGS,
    MAX_PREFIXES_PER_BINDING,
    MAX_SCAN_UNITS,
    valid_source_path_prefix,
)
from common_lore_index.retrieval.context_packet_builder import build_packet_skeleton
from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.retrieval.source_selection import compute_inline_scope_fingerprint
from common_lore_index.server.context_read_sqlite import SqliteContextReadAdapter
from common_lore_index.server.graph_selection import (
    McpOpsError,
    config_locations,
    configured_graph_root_path,
    find_graph,
    graph_path_markers,
)

_CONTEXT_OPS_COMMANDS = frozenset({"context-pack", "context-select"})


def _parse_kv_pairs(
    items: list[str], *, allow_multiple: bool
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw in items:
        if not isinstance(raw, str) or "=" not in raw:
            raise ContextRequestError(f"expected KEY=VALUE in {raw!r}")
        k, v = raw.split("=", 1)
        k = k.strip()
        if not k or not v:
            raise ContextRequestError(f"empty key or value in {raw!r}")
        if allow_multiple:
            out.setdefault(k, []).append(v)
        else:
            out[k] = Path(v)
    return out


@contextmanager
def _open_configured_context_port(
    args: argparse.Namespace, admit: Callable[[object], None] | None = None,
) -> Iterator[ContextReadPort]:
    config_path = getattr(args, "config", None)
    repo_map_home = getattr(args, "repo_map_home", None)
    config = (
        load_graph_registry_config(config_path)
        if config_path
        else load_graph_registry_config_home(repo_map_home)
    )
    graph = find_graph(config, args.graph)
    if not graph.enabled:
        raise McpOpsError(f"graph {args.graph!r} is not enabled")
    if graph.readback_unsupported_classification is not None:
        raise McpOpsError(graph.readback_unsupported_classification)
    if admit is not None:
        admit(config)  # opt-in destination admission: after config, before DB/source

    cfg_bindings = {
        b.binding_id: {
            "binding_id": b.binding_id,
            "revision": int(b.revision),
            "selection_policy_id": b.selection_policy_id,
            "source_definition_id": b.source_definition_id,
        }
        for b in graph.effective_source_bindings
    }
    markers = graph_path_markers(graph, config_locations(config))

    if isinstance(config, LocalSqliteConfig):
        db_path = sqlite_graph_database_path(config, graph)
        with SqliteContextReadAdapter(
            graph_id=graph.id,
            db_path=db_path,
            binding=local_graph_binding(graph),
            configured_bindings=cfg_bindings,
            private_markers=markers,
        ) as adapter:
            yield adapter
        return

    from common_lore_index.runtime.postgres_route import readback_postgres_authority
    from common_lore_index.server._ops_records import (
        McpOpsGraphContext,
        psql_command_from_environment,
    )
    from common_lore_index.server.context_read_postgres import PostgresContextReadAdapter

    ctx = McpOpsGraphContext(
        config=config,
        graph=graph,
        psql_command=psql_command_from_environment(),
    )
    authority = readback_postgres_authority(config)
    with PostgresContextReadAdapter(
        graph_id=graph.id,
        repository_id=ctx.repository_identity,
        root_path=configured_graph_root_path(graph),
        psql_args=authority.postgres.psql_args_for_database(ctx.database),
        psql_command=ctx.psql_command or "psql",
        password=authority.password,
        configured_bindings=cfg_bindings,
        private_markers=markers,
    ) as pg_adapter:
        yield pg_adapter


def _resolve_early_backend_metadata(
    args: argparse.Namespace, graph_id: str
) -> tuple[str, str, str]:
    config_path = getattr(args, "config", None)
    repo_map_home = getattr(args, "repo_map_home", None)
    if config_path or repo_map_home:
        declared = declared_storage_backend(
            repo_map_home=str(repo_map_home) if repo_map_home else None,
            config_path=str(config_path) if config_path else None,
        )
        if declared == "postgresql":
            return "postgresql", "per_statement_identity_checked", f"repo1:{graph_id}"
        if declared == "sqlite":
            return "sqlite", "single_read_transaction", f"repo1:{graph_id}"
        try:
            config = (
                load_graph_registry_config(config_path)
                if config_path
                else load_graph_registry_config_home(repo_map_home)
            )
            if not isinstance(config, LocalSqliteConfig):
                return "postgresql", "per_statement_identity_checked", f"repo1:{graph_id}"
        except Exception:
            pass
    return "sqlite", "single_read_transaction", f"repo1:{graph_id}"


def _write_refused_or_unavailable_pack(
    args: argparse.Namespace, status: str, reason: str
) -> int:
    req = ContextRequest(
        graph_id=str(getattr(args, "graph", "unknown")),
        mode=str(getattr(args, "mode", "ranked_discovery")),
        canonical_key=getattr(args, "canonical_key", None),
        query=getattr(args, "query", None),
        intent=getattr(args, "intent", None),
        budget_bytes=int(getattr(args, "budget_bytes", 16384)),
    )
    backend, consistency_mode, repo_id = _resolve_early_backend_metadata(args, req.graph_id)
    ledger = WorkLedger(backend=backend)
    omissions = OmissionCounter()
    omissions.increment(reason, 1)
    fp = compute_inline_scope_fingerprint(
        graph_id=req.graph_id,
        repository_id=repo_id,
        backend=backend,
        selection_source="all_configured",
        selected_binding_ids=(),
        path_prefixes=(),
    )
    pkt = build_packet_skeleton(
        request=req, status=status, effective_mode=None, fallback=None,
        consistency_mode=consistency_mode, backend=backend,
        repository_id=repo_id, selection_source="all_configured",
        selection_fingerprint=fp, selected_binding_ids=(), path_prefixes=(),
        scan_unit_count=0, unlocatable_patterns_excluded=(), scope_complete=False,
        publication=None, ambiguity_status="not_applicable", tied_top_count=0,
        expansion_state="not_requested", expansion_reason=None,
        seeds_expanded=0, omissions=omissions, ledger=ledger, reason=reason,
    )
    pkt["omissions"] = list(omissions.records)
    final_pkt = finalize_packet_within_budget(pkt, int(req.budget_bytes))
    sys.stdout.buffer.write(serialize_compact_json(final_pkt))
    return 1


def _context_pack(
    args: argparse.Namespace,
    req: ContextRequest,
    roots: dict[str, Any],
    session: ResourceReportSession | None,
    print_cli_error: Callable[..., None],
) -> tuple[int, Callable[[], Any] | None]:
    admit = None
    if session is not None:
        def admit(config: object) -> None:
            admit_report(args, config, overrides=tuple(roots.values()))
    try:
        # Without the option the historical one-argument seam is called unchanged.
        opened = (
            _open_configured_context_port(args) if admit is None
            else _open_configured_context_port(args, admit)
        )
        with opened as port:
            packet = build_compact_context(
                req,
                port,
                freshness=FreshnessCheckConfig(
                    enabled=(req.freshness == "check"), source_roots=roots
                ),
            )
    except (OpsConfigError, McpOpsError, ValueError) as error:
        print_cli_error(error, file=sys.stderr)
        return 1, unfinished_compact_context

    sys.stdout.buffer.write(serialize_compact_json(packet))
    st = packet.get("status")
    code = 0 if st == "complete" else (0 if args.allow_partial else 3) if st == "partial" else 1
    return code, lambda: project_compact_context(packet)


def dispatch_ops_context_command(
    args: argparse.Namespace,
    commands: ModuleType,
    print_cli_error: Callable[..., None],
) -> int | None:
    """Dispatch cloe ops context-pack and cloe ops context-select."""
    if args.command != "ops" or args.ops_command not in _CONTEXT_OPS_COMMANDS:
        return None

    if args.ops_command == "context-pack":
        budget_err = validate_budget_bytes(getattr(args, "budget_bytes", None))
        if budget_err is not None:
            sys.stdout.buffer.write(serialize_compact_json(budget_err))
            return 1
        try:
            pfxs = _parse_kv_pairs(list(args.path_prefixes or ()), allow_multiple=True)
            roots = _parse_kv_pairs(list(args.source_roots or ()), allow_multiple=False)
            req = ContextRequest(
                graph_id=args.graph,
                mode=args.mode,
                canonical_key=args.canonical_key,
                query=args.query,
                intent=args.intent,
                selection_path=args.selection,
                bindings=tuple(args.bindings or ()),
                path_prefixes=pfxs,
                kinds=tuple(args.kinds or ()),
                budget_bytes=args.budget_bytes,
                max_items=args.max_items,
                locations_per_item=args.locations_per_item,
                offset=args.offset,
                expand_depth=args.expand_depth,
                expand_seeds=args.expand_seeds,
                node_limit=args.node_limit,
                edge_limit=args.edge_limit,
                edge_kinds=tuple(args.edge_kinds or ()),
                fallback_to=args.fallback_to,
                freshness=args.freshness,
                source_roots=roots,
                allow_partial=bool(args.allow_partial),
            )
            req.validate()
        except ContextRequestError as exc:
            return _write_refused_or_unavailable_pack(args, "refused", exc.refusal_reason)
        except ValueError:
            return _write_refused_or_unavailable_pack(args, "refused", "invalid_request")

        if req.mode in {"literal_captured_text", "semantic_discovery"}:
            return _write_refused_or_unavailable_pack(args, "unavailable", "capability_not_admitted")
        # Early placeholder-ledger packets above never carry a report.
        session = report_session(args)
        try:
            code, factory = _context_pack(args, req, roots, session, print_cli_error)
        except BaseException:
            close_report_session(session, preserve_primary=True)
            raise
        return finish_report(session, code, factory)

    if args.ops_command == "context-select":
        try:
            pfxs = _parse_kv_pairs(list(args.path_prefixes or ()), allow_multiple=True)
            bids = list(dict.fromkeys(args.bindings or ()))
            if len(bids) > MAX_BINDINGS:
                raise ContextRequestError("binding_limit_exceeded", refusal_reason="binding_limit_exceeded")
            units = 0
            for bid, b_pfxs in pfxs.items():
                if bid not in bids:
                    raise ContextRequestError(f"path_prefix for unselected binding: {bid}")
                u_pfxs = list(dict.fromkeys(b_pfxs))
                if len(u_pfxs) > MAX_PREFIXES_PER_BINDING:
                    raise ContextRequestError("prefix_limit_exceeded", refusal_reason="prefix_limit_exceeded")
                for p in u_pfxs:
                    if not valid_source_path_prefix(p):
                        raise ContextRequestError(f"invalid path_prefix: {p!r}")
            for bid in bids:
                units += max(1, len(list(dict.fromkeys(pfxs.get(bid, ())))))
            if units > MAX_SCAN_UNITS:
                raise ContextRequestError("scan_unit_limit_exceeded", refusal_reason="scan_unit_limit_exceeded")
            with _open_configured_context_port(args) as port:
                record = select_context_sources(
                    port=port,
                    bindings=bids,
                    path_prefixes=pfxs,
                    pin_publication=bool(args.pin_publication),
                    output_path=args.output,
                )
        except (OpsConfigError, McpOpsError, ContextRequestError, ValueError, OSError) as error:
            print_cli_error(error, file=sys.stderr)
            return 1
        sys.stdout.buffer.write(serialize_compact_json(record.to_dict()))
        return 0
    return None
