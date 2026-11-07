"""Main orchestrator for W4 bounded compact context and source selection (Epics A-C)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from common_lore_index.retrieval.advisory_freshness import FreshnessCheckConfig
from common_lore_index.retrieval.context_admission import OmissionCounter
from common_lore_index.retrieval.context_budget import (
    finalize_packet_within_budget,
    validate_budget_bytes,
)
from common_lore_index.retrieval.context_contracts import (
    ContextRequest,
    ContextRequestError,
    ExpectedPublicationPin,
)
from common_lore_index.retrieval.context_identity import (
    ContextIdentityError,
    normalize_accepted_publication,
)
from common_lore_index.retrieval.context_packet_builder import (
    build_packet_skeleton,
    execute_scans_and_pack,
)
from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.retrieval.intent_policy import (
    DIRECT_LOCATABLE_CANONICAL_KINDS_V1,
    unlocatable_patterns,
)
from common_lore_index.retrieval.source_selection import (
    SourceBindingSelection,
    SourceSelectionRecord,
    compute_inline_scope_fingerprint,
    read_selection_file,
    revalidate_selection_record,
    write_selection_file,
)
from common_lore_index.storage.navigation_search import NavigationSearchQuery


class ContextReadPort(Protocol):
    """Read-only port implemented by SQLite Local and PostgreSQL context adapters."""

    backend: str
    consistency_mode: str
    graph_id: str
    repository_id: str
    private_markers: tuple[str, ...]

    def configured_bindings_by_id(self) -> Mapping[str, Mapping[str, Any]]: ...
    def read_initial_identity(self, ledger: WorkLedger) -> dict[str, Any]: ...
    def query_candidates_unit(
        self,
        query: NavigationSearchQuery,
        *,
        ledger: WorkLedger,
        expected_identity: Mapping[str, Any],
    ) -> dict[str, Any]: ...
    def query_node_by_canonical_key(
        self,
        canonical_key: str,
        *,
        ledger: WorkLedger,
        expected_identity: Mapping[str, Any],
    ) -> dict[str, Any]: ...
    def expand_seeds_depth1(
        self,
        seed_keys: Sequence[str],
        *,
        edge_kinds: Sequence[str],
        node_limit: int,
        edge_limit: int,
        ledger: WorkLedger,
        expected_identity: Mapping[str, Any],
    ) -> dict[str, Any]: ...


def select_context_sources(
    *,
    port: ContextReadPort,
    bindings: Sequence[str],
    path_prefixes: Mapping[str, Sequence[str]],
    pin_publication: bool,
    output_path: Path | None = None,
) -> SourceSelectionRecord:
    """Build and optionally write a validated cloe-source-selection-v1 record."""
    unique_bids = tuple(dict.fromkeys(bindings))
    if not unique_bids:
        raise ContextRequestError("at least one binding is required")
    live_cfg = port.configured_bindings_by_id()
    for bid in unique_bids:
        if bid not in live_cfg:
            raise ContextRequestError(
                f"unknown binding_id: {bid}", refusal_reason="selection_binding_missing"
            )

    ledger = WorkLedger(backend=port.backend)
    init_res = port.read_initial_identity(ledger)
    if init_res.get("status") != "ok":
        raise ContextRequestError(
            init_res.get("reason", "publication_absent"),
            refusal_reason=init_res.get("reason", "publication_absent"),
        )
    try:
        accepted = init_res.get("accepted_publication")
        if not isinstance(accepted, Mapping):
            raise ContextIdentityError("accepted publication must be a mapping")
        acc = normalize_accepted_publication(
            accepted, require_pin=pin_publication
        )
    except (ContextIdentityError, TypeError) as exc:
        raise ContextRequestError(
            "accepted_publication_unverified",
            refusal_reason="accepted_publication_unverified",
        ) from exc
    vec_map = {
        binding_id: (revision, snapshot_id)
        for binding_id, revision, snapshot_id in acc["snapshot_vector"]
    }

    pin: ExpectedPublicationPin | None = None
    if pin_publication:
        job_id = acc.get("job_id", acc.get("publication_job_id"))
        attempt = acc.get("attempt", acc.get("publication_attempt"))
        if not isinstance(job_id, str) or not job_id.strip() or type(attempt) is not int or attempt < 1:
            raise ContextRequestError(
                "accepted_publication_unverified",
                refusal_reason="accepted_publication_unverified",
            )
        pin = ExpectedPublicationPin(
            accepted_run_id=acc["accepted_run_id"],
            publication_bundle_id=acc["publication_bundle_id"],
            snapshot_manifest_id=acc["snapshot_manifest_id"],
            generation=acc["generation"],
            job_id=job_id,
            attempt=attempt,
            extraction_receipt_id=acc["extraction_receipt_id"],
        ).validate()

    binding_objs: list[SourceBindingSelection] = []
    for bid in unique_bids:
        cfg_b = live_cfg[bid]
        if bid not in vec_map:
            raise ContextRequestError(
                f"binding missing from accepted vector: {bid}",
                refusal_reason="selection_binding_missing",
            )
        vec_rev, vec_snap = vec_map[bid]
        pfxs = tuple(dict.fromkeys(path_prefixes.get(bid, ())))
        binding_objs.append(
            SourceBindingSelection(
                binding_id=bid,
                revision=vec_rev,
                snapshot_id=vec_snap if pin_publication else None,
                selection_policy_id=str(cfg_b["selection_policy_id"]),
                source_definition_id=str(cfg_b["source_definition_id"]),
                path_prefixes=pfxs,
            ).validate()
        )
    record = SourceSelectionRecord.build(
        graph_id=init_res["graph_id"],
        repository_id=init_res["repository_id"],
        backend=port.backend,
        bindings=binding_objs,
        expected_publication=pin,
    )
    if output_path is not None:
        write_selection_file(record, output_path)
    return record


def build_compact_context(
    request: ContextRequest,
    port: ContextReadPort,
    *,
    freshness: FreshnessCheckConfig | None = None,
    freshness_step_hook: Callable[[str], None] | None = None,
    work_ledger: WorkLedger | None = None,
) -> dict[str, Any]:
    """Assemble a bounded cloe-compact-context-v1 packet over SQLite Local or PostgreSQL."""
    budget_err = validate_budget_bytes(request.budget_bytes)
    if budget_err is not None:
        return budget_err

    ledger = work_ledger or WorkLedger(backend=port.backend)
    omissions = OmissionCounter()
    budget_int = int(request.budget_bytes)

    def _early_packet(
        status: str,
        reason: str,
        *,
        pub: dict[str, Any] | None = None,
        sel_src: str = "all_configured",
        sel_fp: str | None = None,
        b_ids: Sequence[str] = (),
        p_pfxs: Sequence[Mapping[str, str]] = (),
        scan_units: int = 0,
    ) -> dict[str, Any]:
        fp = sel_fp or compute_inline_scope_fingerprint(
            graph_id=request.graph_id or port.graph_id,
            repository_id=port.repository_id,
            backend=port.backend,
            selection_source=sel_src,
            selected_binding_ids=b_ids,
            path_prefixes=p_pfxs,
        )
        omissions.increment(reason, 1)
        pkt = build_packet_skeleton(
            request=request, status=status, effective_mode=None, fallback=None,
            consistency_mode=port.consistency_mode, backend=port.backend,
            repository_id=port.repository_id, selection_source=sel_src,
            selection_fingerprint=fp, selected_binding_ids=b_ids,
            path_prefixes=p_pfxs, scan_unit_count=scan_units,
            unlocatable_patterns_excluded=(), scope_complete=False,
            publication=pub, ambiguity_status="not_applicable", tied_top_count=0,
            expansion_state="not_requested", expansion_reason=None,
            seeds_expanded=0, omissions=omissions, ledger=ledger, reason=reason,
        )
        pkt["omissions"] = list(omissions.records)
        return finalize_packet_within_budget(pkt, budget_int)

    try:
        request.validate()
    except ContextRequestError as exc:
        return _early_packet("refused", exc.refusal_reason)
    except ValueError:
        return _early_packet("refused", "invalid_request")

    if request.mode in {"literal_captured_text", "semantic_discovery"}:
        return _early_packet("unavailable", "capability_not_admitted")

    effective_mode = request.mode
    fallback_obj: dict[str, Any] | None = None
    if request.mode == "graph_investigation" and port.backend == "postgresql":
        if request.fallback_to is None:
            return _early_packet("unavailable", "backend_unsupported")
        effective_mode = request.fallback_to
        fallback_obj = {
            "requested_mode": "graph_investigation",
            "effective_mode": effective_mode,
            "reason": "backend_unsupported",
            "target_used": "canonical_key" if effective_mode == "exact_identity" else "query",
        }

    selection_record: SourceSelectionRecord | None = None
    selection_source = "all_configured"
    selected_binding_ids: list[str] = []
    path_prefix_entries: list[dict[str, str]] = []
    scan_units_list: list[tuple[str | None, str | None]] = []

    if request.selection_path is not None:
        selection_source = "selection_file"
        try:
            selection_record = read_selection_file(request.selection_path)
        except ContextRequestError as exc:
            return _early_packet("refused", exc.refusal_reason, sel_src="selection_file")
        ledger.config_revalidations_executed += 1
        for b in selection_record.bindings:
            selected_binding_ids.append(b.binding_id)
            if b.path_prefixes:
                for pfx in b.path_prefixes:
                    path_prefix_entries.append({"binding_id": b.binding_id, "prefix": pfx})
                    scan_units_list.append((b.binding_id, pfx))
            else:
                scan_units_list.append((b.binding_id, None))
        sel_fp = selection_record.selection_fingerprint
    elif request.bindings:
        selection_source = "inline_flags"
        ledger.config_revalidations_executed += 1
        live_cfg = port.configured_bindings_by_id()
        for bid in dict.fromkeys(request.bindings):
            if bid not in live_cfg:
                return _early_packet("refused", "selection_binding_missing", sel_src="inline_flags")
            selected_binding_ids.append(bid)
            pfxs = list(dict.fromkeys(request.path_prefixes.get(bid, ())))
            if pfxs:
                for pfx in pfxs:
                    path_prefix_entries.append({"binding_id": bid, "prefix": pfx})
                    scan_units_list.append((bid, pfx))
            else:
                scan_units_list.append((bid, None))
        sel_fp = compute_inline_scope_fingerprint(
            graph_id=request.graph_id, repository_id=port.repository_id,
            backend=port.backend, selection_source=selection_source,
            selected_binding_ids=selected_binding_ids, path_prefixes=path_prefix_entries,
        )
    else:
        scan_units_list.append((None, None))
        sel_fp = compute_inline_scope_fingerprint(
            graph_id=request.graph_id, repository_id=port.repository_id,
            backend=port.backend, selection_source="all_configured",
            selected_binding_ids=(), path_prefixes=(),
        )

    init_res = port.read_initial_identity(ledger)
    if init_res.get("status") != "ok":
        st = "partial" if init_res.get("status") == "exhausted" else "unavailable"
        return _early_packet(
            st, init_res.get("reason", "publication_absent"),
            sel_src=selection_source, sel_fp=sel_fp, b_ids=selected_binding_ids,
            p_pfxs=path_prefix_entries, scan_units=len(scan_units_list),
        )

    try:
        accepted = init_res.get("accepted_publication")
        if not isinstance(accepted, Mapping):
            raise ContextIdentityError("accepted publication must be a mapping")
        live_acc = normalize_accepted_publication(
            accepted, require_pin=False
        )
    except (ContextIdentityError, TypeError):
        return _early_packet(
            "unavailable", "accepted_publication_unverified",
            sel_src=selection_source, sel_fp=sel_fp, b_ids=selected_binding_ids,
            p_pfxs=path_prefix_entries, scan_units=len(scan_units_list),
        )
    pub_summary = {
        "generation": live_acc["generation"],
        "accepted_run_id": live_acc["accepted_run_id"],
        "publication_bundle_id": live_acc["publication_bundle_id"],
        "snapshot_manifest_id": live_acc["snapshot_manifest_id"],
    }
    if init_res.get("graph_id") != request.graph_id or init_res.get("repository_id") != port.repository_id:
        return _early_packet(
            "refused" if selection_record else "unavailable",
            "selection_graph_mismatch" if selection_record else "accepted_publication_unverified",
            pub=pub_summary, sel_src=selection_source, sel_fp=sel_fp,
            b_ids=selected_binding_ids, p_pfxs=path_prefix_entries, scan_units=len(scan_units_list),
        )

    if selection_record is not None:
        st_ov, r_ov = revalidate_selection_record(
            selection_record,
            live_graph_id=init_res["graph_id"],
            live_repository_id=init_res["repository_id"],
            live_backend=port.backend,
            live_bindings_by_id=port.configured_bindings_by_id(),
            live_accepted=live_acc,
        )
        if st_ov is not None and r_ov is not None:
            return _early_packet(
                st_ov, r_ov, pub=pub_summary, sel_src=selection_source, sel_fp=sel_fp,
                b_ids=selected_binding_ids, p_pfxs=path_prefix_entries, scan_units=len(scan_units_list),
            )
    elif request.expected_publication is not None:
        if not request.expected_publication.matches_accepted(live_acc):
            return _early_packet(
                "stale", "selection_publication_advanced", pub=pub_summary,
                sel_src=selection_source, sel_fp=sel_fp, b_ids=selected_binding_ids,
                p_pfxs=path_prefix_entries, scan_units=len(scan_units_list),
            )

    is_scoped = len(selected_binding_ids) > 0
    eff_intent = (
        None
        if effective_mode in {"exact_identity", "current_literal_enumeration"}
        else (request.intent or "general")
    )
    excluded_patterns: tuple[str, ...] = ()
    scope_complete = True
    if is_scoped:
        if any(k not in DIRECT_LOCATABLE_CANONICAL_KINDS_V1 for k in request.kinds):
            return _early_packet(
                "unavailable", "unlocatable_kind_in_scoped_selection", pub=pub_summary,
                sel_src=selection_source, sel_fp=sel_fp, b_ids=selected_binding_ids,
                p_pfxs=path_prefix_entries, scan_units=len(scan_units_list),
            )
        excluded_patterns, _ = unlocatable_patterns(eff_intent, request.kinds, scoped=True)
        if excluded_patterns:
            omissions.increment("unlocatable_kind_pattern_excluded", len(excluded_patterns))
            scope_complete = False

    return execute_scans_and_pack(
        request=request, port=port, ledger=ledger, omissions=omissions,
        effective_mode=effective_mode, fallback_obj=fallback_obj,
        selection_source=selection_source, sel_fp=sel_fp,
        selected_binding_ids=selected_binding_ids, path_prefix_entries=path_prefix_entries,
        scan_units_list=scan_units_list, excluded_patterns=excluded_patterns,
        scope_complete=scope_complete, live_acc=live_acc, pub_summary=pub_summary,
        eff_intent=eff_intent, freshness=freshness, freshness_step_hook=freshness_step_hook,
    )
