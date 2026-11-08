"""Packet skeleton builder and scan/pack execution for cloe-compact-context-v1 (W4 §4.1-4.2)."""
from __future__ import annotations
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from common_lore_index.retrieval.advisory_freshness import (
    FreshnessCheckConfig, default_freshness_summary, evaluate_packet_freshness,
)
from common_lore_index.retrieval.context_admission import (
    OmissionCounter, admit_items_and_relations, format_context_item, format_context_relation,
)
from common_lore_index.retrieval.context_budget import (
    CANONICAL_KEY_CAP_BYTES, build_budget_error_envelope, finalize_packet_within_budget,
    maximally_compacted_skeleton_bytes, sanitize_stored_string, sha256_prefixed,
)
from common_lore_index.retrieval.context_contracts import (
    ADMISSION_ORDER_POLICY_ID, COMPACT_CONTEXT_SCHEMA_VERSION, ContextRequest,
    UNAVAILABLE_REASONS,
)
from common_lore_index.retrieval.context_budget_reservation import (
    empty_packet_size_with_reservation, packet_size_with_reservation,
)
from common_lore_index.retrieval.context_work import WorkLedger
from common_lore_index.retrieval.intent_policy import (
    INTENT_RANK_VERSION, INTENT_TABLES_VERSION, INTENT_TIEBREAK_VERSION,
    classify_subject_intent_family,
)
from common_lore_index.retrieval.intent_ranking import (
    CANONICAL_KEY_ORDER_VERSION, CandidateRankingInput,
    first_verified_destination_tuple, order_candidates_canonical_key_asc, rank_candidates,
)
from common_lore_index.server._navigation_groups import _destination, _in_scope, _withheld, project_navigation_member
from common_lore_index.storage.navigation_search import NavigationSearchQuery
def _sanitized_unavailable_reason(value: Any) -> str:
    return value if isinstance(value, str) and value in UNAVAILABLE_REASONS else "database_unavailable"
def _required_budget_error(budget: int, required: int) -> dict[str, Any]:
    return build_budget_error_envelope(reason="required_envelope_does_not_fit", budget_bytes=budget, required_min_bytes=required)
def _finish_unavailable(packet: dict[str, Any], reason: str, ledger: WorkLedger, budget: int) -> dict[str, Any]:
    packet.update(status="unavailable", reason=reason, unavailable_reason=reason)
    packet["scope"]["scope_complete"] = False; packet["work_ledger"] = ledger.to_dict()
    return finalize_packet_within_budget(packet, budget)
def _finish_stale(packet: dict[str, Any], ledger: WorkLedger, budget: int) -> dict[str, Any]:
    packet.update(status="stale", reason="publication_advanced_during_assembly")
    packet["scope"]["scope_complete"] = False; packet["work_ledger"] = ledger.to_dict()
    return finalize_packet_within_budget(packet, budget)
def port_supports_depth1_expansion(port: Any) -> bool:
    return getattr(port, "supports_depth1_expansion", port.backend != "postgresql") is True
def project_node_to_candidate(
    node: Mapping[str, Any], *, markers: tuple[str, ...]
) -> tuple[CandidateRankingInput, dict[str, Any], list[dict[str, Any]]]:
    """Project a raw scan node via project_navigation_member and build CandidateRankingInput."""
    node_dict = dict(node)
    member, public_locs = project_navigation_member(node_dict, markers)
    ck, kind, dn = str(node_dict.get("canonical_key", "")), str(node_dict.get("kind", "")), str(node_dict.get("display_name") or "")
    verified_dests: list[dict[str, Any]] = []
    has_current_pub, first_rel_path = False, None
    for loc in public_locs:
        if loc.get("publication_relation") == "accepted_run":
            has_current_pub = True
        dest = _destination(loc, markers)
        if dest is not None:
            verified_dests.append(dest)
            if first_rel_path is None:
                first_rel_path = dest.get("source_relative_path")
    any_loc_withheld = any(
        loc.get("source_identity_status") == "withheld"
        or loc.get("path_status") == "missing_or_withheld"
        or _withheld(loc.get("path"))
        for loc in public_locs
    )
    id_withheld = member.get("identity_status") == "withheld" or (not verified_dests and any_loc_withheld)
    family = classify_subject_intent_family(kind=kind, canonical_key=ck, display_name=dn, source_relative_path=first_rel_path)
    cand = CandidateRankingInput(
        canonical_key=ck, kind=kind, display_name=dn, subject_family=family,
        has_direct_evidence=len(public_locs) > 0, has_verified_direct_location=len(verified_dests) > 0,
        identity_withheld=id_withheld, is_current_publication=has_current_pub,
        first_verified_destination=first_verified_destination_tuple(verified_dests),
        payload={"node": node_dict, "member": member, "public_locs": public_locs},
    )
    return cand, member, public_locs
def _edge_filter_mode(request: ContextRequest, effective_mode: str | None) -> str:
    if request.effective_expand_depth() == 0 or effective_mode in {
        "exact_identity", "current_literal_enumeration", None,
    }:
        return "none"
    if request.edge_kinds:
        return "explicit_edge_kinds"
    eff_intent = request.effective_intent() or "general"
    return "all_canonical_edge_kinds" if eff_intent == "general" else "intent_default"
def build_packet_skeleton(
    *,
    request: ContextRequest, status: str, effective_mode: str | None,
    fallback: dict[str, Any] | None, consistency_mode: str, backend: str,
    repository_id: str, selection_source: str, selection_fingerprint: str,
    selected_binding_ids: Sequence[str], path_prefixes: Sequence[Mapping[str, str]],
    scan_unit_count: int, unlocatable_patterns_excluded: Sequence[str],
    scope_complete: bool, publication: dict[str, Any] | None,
    ambiguity_status: str, tied_top_count: int, expansion_state: str,
    expansion_reason: str | None, seeds_expanded: int,
    omissions: OmissionCounter, ledger: WorkLedger, reason: str | None = None,
) -> dict[str, Any]:
    """Assemble the 19-key cloe-compact-context-v1 packet skeleton in locked key order."""
    eff_mode_for_target = effective_mode or request.mode
    if eff_mode_for_target in {"exact_identity", "graph_investigation"} and request.canonical_key is not None:
        target_kind, raw_target = "canonical_key", request.canonical_key
    else:
        target_kind, raw_target = "query", (request.query or request.canonical_key or "")
    target_sha256 = sha256_prefixed(raw_target)
    clean_echo, echo_err = sanitize_stored_string(raw_target, field_cap_bytes=CANONICAL_KEY_CAP_BYTES)
    if echo_err is not None:
        omissions.increment(echo_err)
    target_withheld = clean_echo is None and bool(raw_target)
    eff_intent = (
        None if eff_mode_for_target in {"exact_identity", "current_literal_enumeration"}
        else (request.intent or "general")
    )
    is_ranked = eff_mode_for_target in {"ranked_discovery", "graph_investigation"}
    is_scoped = len(selected_binding_ids) > 0 or len(path_prefixes) > 0
    absence_basis = (
        (
            "stored_direct_locatable_metadata_fields_in_selected_scope"
            if is_scoped else "stored_metadata_fields_in_selected_scope"
        )
        if status in {"complete", "partial"} else None
    )
    packet: dict[str, Any] = {
        "schema": COMPACT_CONTEXT_SCHEMA_VERSION, "status": status,
        "requested_mode": request.mode, "effective_mode": effective_mode,
        "fallback": fallback, "consistency_mode": consistency_mode,
        "request": {
            "mode": request.mode, "intent": eff_intent, "target_kind": target_kind,
            "target_echo": clean_echo, "target_sha256": target_sha256,
            "target_echo_withheld": target_withheld, "offset": request.offset,
            "max_items": request.max_items, "locations_per_item": request.locations_per_item,
            "expand_depth": request.effective_expand_depth(),
            "expand_seeds": request.expand_seeds, "budget_bytes": int(request.budget_bytes),
        },
        "scope": {
            "graph_id": request.graph_id, "backend": backend,
            "selection_source": selection_source, "selection_fingerprint": selection_fingerprint,
            "selected_binding_count": len(selected_binding_ids),
            "path_prefix_count": len(path_prefixes), "scan_unit_count": scan_unit_count,
            "unlocatable_kind_patterns_excluded": list(unlocatable_patterns_excluded),
            "scope_echo_complete": True, "selected_binding_ids": list(selected_binding_ids),
            "path_prefixes": [dict(p) for p in path_prefixes],
            "scope_complete": scope_complete, "repository_id": repository_id,
        },
        "publication": publication,
        "ordering": {
            "ordering_policy_version": INTENT_RANK_VERSION if is_ranked else CANONICAL_KEY_ORDER_VERSION,
            "tie_break_version": INTENT_TIEBREAK_VERSION,
            "intent_tables_version": INTENT_TABLES_VERSION if is_ranked else None,
            "admission_layout": ADMISSION_ORDER_POLICY_ID,
            "ambiguity": {"status": ambiguity_status, "tied_top_count": tied_top_count},
        },
        "expansion": {
            "state": expansion_state, "reason": expansion_reason,
            "edge_filter_mode": _edge_filter_mode(request, effective_mode),
            "seeds_expanded": seeds_expanded, "neighbors_admitted": 0, "relations_admitted": 0,
        },
        "omission_counts": omissions.to_counts_dict(),
        "work_ledger": ledger.to_dict(),
        "freshness": default_freshness_summary(state="not_requested"),
        "absence_basis": absence_basis,
        "items": [], "neighbors": [], "relations": [], "omissions": [],
    }
    if reason is not None and status in {"refused", "stale", "unavailable", "failed"}:
        packet["reason"] = reason
        if status == "refused":
            packet["refusal_code"] = reason
        elif status == "unavailable":
            packet["unavailable_reason"] = reason
    return packet
def _loc_matches_units(
    public_locs: list[dict[str, Any]],
    scan_units: Sequence[tuple[str | None, str | None]],
    markers: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not scan_units or scan_units == [(None, None)]:
        return public_locs
    return [
        loc for loc in public_locs
        if any(
            _in_scope([loc], NavigationSearchQuery(query="x", source_binding_id=b, source_path_prefix=p), markers)
            for b, p in scan_units
        )
    ]
def execute_scans_and_pack(
    *, request: ContextRequest, port: Any, ledger: WorkLedger, omissions: OmissionCounter,
    effective_mode: str, fallback_obj: dict[str, Any] | None, selection_source: str,
    sel_fp: str, selected_binding_ids: Sequence[str],
    path_prefix_entries: Sequence[Mapping[str, str]],
    scan_units_list: Sequence[tuple[str | None, str | None]],
    excluded_patterns: Sequence[str], scope_complete: bool,
    live_acc: Mapping[str, Any], pub_summary: dict[str, Any], eff_intent: str | None,
    freshness: FreshnessCheckConfig | None,
    freshness_step_hook: Callable[[str], None] | None,
) -> dict[str, Any]:
    """Run candidate scans, rank, expand depth-1, admit within budget, and check freshness."""
    budget_int = int(request.budget_bytes)
    active_freshness = freshness or FreshnessCheckConfig(
        enabled=(request.freshness == "check"), source_roots=request.source_roots
    )
    exp_depth = request.expand_depth if request.expand_depth is not None else (1 if effective_mode == "graph_investigation" else 0)
    exp_state, exp_reason = ("completed" if exp_depth == 1 else "not_requested"), None
    skeleton = build_packet_skeleton(
        request=request, status="complete", effective_mode=effective_mode,
        fallback=fallback_obj, consistency_mode=port.consistency_mode,
        backend=port.backend, repository_id=port.repository_id,
        selection_source=selection_source, selection_fingerprint=sel_fp,
        selected_binding_ids=selected_binding_ids, path_prefixes=path_prefix_entries,
        scan_unit_count=len(scan_units_list), unlocatable_patterns_excluded=excluded_patterns,
        scope_complete=scope_complete, publication=pub_summary,
        ambiguity_status="unambiguous", tied_top_count=0,
        expansion_state=exp_state, expansion_reason=exp_reason,
        seeds_expanded=0, omissions=omissions, ledger=ledger,
    )
    merged_nodes: dict[str, dict[str, Any]] = {}
    is_scoped = len(selected_binding_ids) > 0
    if effective_mode in {"exact_identity", "graph_investigation"}:
        res = port.query_node_by_canonical_key(request.canonical_key or "", ledger=ledger, expected_identity=live_acc)
        if res.get("status") == "unavailable":
            return _finish_unavailable(skeleton, _sanitized_unavailable_reason(res.get("reason")), ledger, budget_int)
        if res.get("status") == "stale":
            return _finish_stale(skeleton, ledger, budget_int)
        if res.get("status") == "exhausted":
            scope_complete = False
            omissions.increment("candidate_scan_incomplete", 1, detail=res.get("reason"))
        elif res.get("status") == "ok" and res.get("node") is not None:
            node = dict(res["node"])
            if not request.kinds or node.get("kind") in request.kinds:
                if is_scoped:
                    _, _, pub_locs = project_node_to_candidate(node, markers=port.private_markers)
                    matched_locs = _loc_matches_units(pub_locs, scan_units_list, port.private_markers)
                    if matched_locs:
                        node["locations"] = matched_locs
                        merged_nodes[str(node["canonical_key"])] = node
                else:
                    merged_nodes[str(node["canonical_key"])] = node
    else:
        kinds_to_scan: tuple[str | None, ...] = request.kinds if request.kinds else (None,)
        stop_scans = False
        for b_id, pfx in scan_units_list:
            if stop_scans:
                break
            unit_nodes: dict[str, dict[str, Any]] = {}
            unit_incomplete = False
            for k in kinds_to_scan:
                nav_q = NavigationSearchQuery(
                    query=(request.query or "").strip(), kind=k,
                    source_binding_id=b_id, source_path_prefix=pfx,
                )
                scan_res = port.query_candidates_unit(nav_q, ledger=ledger, expected_identity=live_acc)
                st = scan_res.get("status")
                if st == "unavailable":
                    return _finish_unavailable(skeleton, _sanitized_unavailable_reason(scan_res.get("reason")), ledger, budget_int)
                if st == "stale":
                    return _finish_stale(skeleton, ledger, budget_int)
                if st in {"exhausted", "incomplete"}:
                    scope_complete = False
                    unit_incomplete = True
                    stop_scans = st == "exhausted"
                    omissions.increment(
                        "candidate_scan_incomplete", 1,
                        detail=f"binding={b_id},prefix={pfx},reason={scan_res.get('reason')}",
                    )
                    break
                for n in scan_res.get("nodes", ()):
                    ck = str(n["canonical_key"])
                    if ck not in unit_nodes:
                        unit_nodes[ck] = {**n, "locations": list(n.get("locations", ()))}
                    else:
                        unit_nodes[ck]["locations"].extend(n.get("locations", ()))
            if not unit_incomplete:
                for ck, n in unit_nodes.items():
                    if ck not in merged_nodes:
                        merged_nodes[ck] = n
                    else:
                        merged_nodes[ck]["locations"].extend(n["locations"])
    cand_inputs = [project_node_to_candidate(n, markers=port.private_markers)[0] for n in merged_nodes.values()]
    ranked, ambiguity = (
        rank_candidates(cand_inputs, query=(request.query or "").strip(), intent=eff_intent or "general")
        if effective_mode == "ranked_discovery" else order_candidates_canonical_key_asc(cand_inputs)
    )
    top_tied_keys: frozenset[str] = frozenset()
    if ambiguity.status == "ambiguous" and ranked:
        top_sig = (ranked[0].tiers.exactness_tier, ranked[0].tiers.affinity_tier, ranked[0].tiers.match_class_tier)
        top_tied_keys = frozenset(
            rc.candidate.canonical_key for rc in ranked
            if (rc.tiers.exactness_tier, rc.tiers.affinity_tier, rc.tiers.match_class_tier) == top_sig
        )
    post_offset = ranked[request.offset:]
    window = post_offset[: request.max_items]
    overflow_tied = sum(1 for rc in post_offset[request.max_items:] if rc.candidate.canonical_key in top_tied_keys)
    candidate_seeds: list[dict[str, Any]] = []
    for idx, rc in enumerate(window):
        payload = rc.candidate.payload or {}
        member, node_dict = payload.get("member", {}), payload.get("node", {})
        candidate_seeds.append(
            format_context_item(
                item_id=f"seed:{idx + 1}", item_role="seed",
                canonical_key=rc.candidate.canonical_key, kind=rc.candidate.kind,
                display_name=member.get("display_name", rc.candidate.display_name),
                identity_status=member.get("identity_status", "available"),
                raw_locations=node_dict.get("locations", ()),
                markers=port.private_markers, locations_per_item=request.locations_per_item,
                reserve_freshness=active_freshness.enabled, omissions=omissions,
                match_surface="stored_metadata", rank=rc.rank,
                match_class=rc.match_class, rank_tiers=rc.tiers.to_dict(), rank_reasons=rc.reasons,
            )
        )
    neighbor_units: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    extra_relations: list[dict[str, Any]] = []
    seeds_expanded = 0
    if exp_depth == 1:
        if not port_supports_depth1_expansion(port):
            exp_state, exp_reason, scope_complete = "unavailable", "backend_unsupported", False
            omissions.increment("expansion_backend_unsupported", 1)
        else:
            seed_cks = [
                s["canonical_key"] for s in candidate_seeds[: request.expand_seeds]
                if isinstance(s.get("canonical_key"), str)
            ]
            if seed_cks:
                exp_res = port.expand_seeds_depth1(
                    seed_cks, edge_kinds=request.effective_edge_kinds(),
                    node_limit=request.node_limit, edge_limit=request.edge_limit,
                    ledger=ledger, expected_identity=live_acc,
                )
                if exp_res.get("status") == "unavailable":
                    return _finish_unavailable(skeleton, _sanitized_unavailable_reason(exp_res.get("reason")), ledger, budget_int)
                if exp_res.get("status") == "stale":
                    return _finish_stale(skeleton, ledger, budget_int)
                seeds_expanded = int(exp_res.get("seeds_expanded", 0))
                for hit_key, om_key, r_name in (
                    ("edge_limit_hit", "expansion_edge_limit", "edge_limit"),
                    ("node_limit_hit", "expansion_node_limit", "node_limit"),
                ):
                    if exp_res.get(hit_key, 0) > 0:
                        omissions.increment(om_key, int(exp_res[hit_key]))
                        exp_state, exp_reason, scope_complete = "partial", (exp_reason or r_name), False
                if exp_res.get("neighbor_locations_incomplete"):
                    omissions.increment("candidate_scan_incomplete", 1, detail="neighbor_locations_evidence_scan_limit")
                    exp_state, exp_reason, scope_complete = "partial", (exp_reason or "evidence_scan_limit"), False
                if exp_res.get("status") == "partial":
                    exp_state, exp_reason, scope_complete = "partial", (exp_reason or exp_res.get("reason")), False
                for n_idx, nbr_entry in enumerate(exp_res.get("neighbor_units", ())):
                    nbr_node = nbr_entry["node"]
                    nbr_member, _ = project_navigation_member(nbr_node, port.private_markers)
                    nbr_item = format_context_item(
                        item_id=f"neighbor:{n_idx + 1}", item_role="neighbor",
                        canonical_key=nbr_node["canonical_key"], kind=nbr_node["kind"],
                        display_name=nbr_member.get("display_name", nbr_node.get("display_name")),
                        identity_status=nbr_member.get("identity_status", "available"),
                        raw_locations=nbr_node.get("locations", ()),
                        markers=port.private_markers, locations_per_item=request.locations_per_item,
                        reserve_freshness=active_freshness.enabled, omissions=omissions,
                        match_surface="graph_topology",
                    )
                    neighbor_units.append((nbr_item, [format_context_relation(e) for e in nbr_entry.get("edges", ())]))
                extra_relations = [format_context_relation(e) for e in exp_res.get("seed_to_seed_edges", ())]
    skeleton["ordering"]["ambiguity"] = ambiguity.to_dict()
    skeleton["expansion"].update(state=exp_state, reason=exp_reason, seeds_expanded=seeds_expanded)
    skeleton["work_ledger"] = ledger.to_dict()
    skeleton["omission_counts"] = omissions.to_counts_dict()
    if active_freshness.enabled:
        skeleton["freshness"] = default_freshness_summary(state="checked")
    required_min_bytes = maximally_compacted_skeleton_bytes(skeleton)
    if required_min_bytes > budget_int:
        return _required_budget_error(budget_int, required_min_bytes)
    admit_items_and_relations(
        skeleton, candidate_seeds=candidate_seeds, total_post_offset_seeds=len(post_offset),
        top_tied_keys=top_tied_keys, overflow_tied_count=overflow_tied,
        neighbor_units=neighbor_units, extra_relations=extra_relations,
        omissions=omissions, budget_bytes=budget_int,
    )
    if skeleton["items"]:
        skeleton["absence_basis"] = None
    skeleton["omission_counts"] = omissions.to_counts_dict()
    required_min_bytes = maximally_compacted_skeleton_bytes(skeleton)
    if required_min_bytes > budget_int:
        return _required_budget_error(budget_int, required_min_bytes)
    if skeleton["items"]:
        if packet_size_with_reservation(skeleton) > budget_int:
            raise AssertionError("admitted packet exceeded the pre-freshness reservation")
    elif empty_packet_size_with_reservation(skeleton) > budget_int:
        if skeleton["omissions"]:
            raise AssertionError("empty packet retained optional records beyond its reservation")
    sel_set = set(selected_binding_ids) if selected_binding_ids else None
    evaluate_packet_freshness(skeleton, active_freshness, selected_bindings=sel_set, step_hook=freshness_step_hook)
    is_complete = (
        scope_complete and not omissions.any_omissions()
        and ledger.exhausted_reason is None and exp_state in {"not_requested", "completed"}
    )
    skeleton["scope"]["scope_complete"] = is_complete
    skeleton["status"] = "complete" if is_complete else "partial"
    skeleton["work_ledger"] = ledger.to_dict()
    return finalize_packet_within_budget(
        skeleton, budget_int, top_tied_keys=top_tied_keys,
        required_min_bytes=(maximally_compacted_skeleton_bytes(skeleton) if not skeleton["items"] else required_min_bytes),
    )
