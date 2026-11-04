"""Current-graph baseline adapter over real SQLite Local and PostgreSQL read stores (S3)."""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

import common_lore_index.retrieval.query_contracts as qc
from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from common_lore_index.retrieval.projection_policy import (
    ALLOWED_BINDING_PRIVACY, ALLOWED_EVIDENCE_RETENTION, ALLOWED_GRAPH_PRIVACY,
)
from common_lore_index.server.ops import investigation_stores
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.node_locations import NodeLocationsQuery
from repomap_test_support.retrieval_evaluation_fixture import (
    binding_id_for_alias,
)
from retrieval_evaluation_accounting import ByteLayerAccounting
import retrieval_evaluation_correspondence_graph_scope as graph_scope
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask
from retrieval_evaluation_observation_contracts import ObservationPublicationPin, CurrentObservationReadError
from retrieval_evaluation_graph_records import (
    _parse_prefixed_graph_path as _parse_prefixed_graph_path,
    _opt_pos_int as _opt_pos_int,
    _make_hit as _make_hit,
    _json_len as _json_len,
    _locator_from_observation_row as _locator_from_observation_row,
    _build_available_envelope as _build_available_envelope,
)
from retrieval_evaluation_graph_traversal import _traverse_graph_neighborhood as _traverse_graph_neighborhood
from retrieval_evaluation_graph_pages import GraphPageEvidence
from retrieval_evaluation_scope import source_path_matches_prefix

_GraphTaskOutcome = tuple[ExecutionState, qc.QueryEnvelope, int, ByteLayerAccounting]


class _NavigationReadStore(Protocol):
    """Minimal navigation surface consumed by the evaluator adapter."""

    def navigation_search(
        self, graph_id: str, query: NavigationSearchQuery,
    ) -> Mapping[str, Any]: ...


class _LocationsReadStore(Protocol):
    """Minimal node-location surface consumed by direct handoff evaluation."""

    def node_locations(
        self, graph_id: str, query: NodeLocationsQuery,
    ) -> Mapping[str, Any]: ...


def _execute_navigation_or_locations_mode(
    inv_store: _NavigationReadStore, task: EvaluationTask,
    scope: qc.QueryScope, requested_mode: qc.QueryMode,
) -> _GraphTaskOutcome:
    t0, plan = time.perf_counter_ns(), task.permitted_query_plan
    limit = int(plan.get("limit", 10))
    selected_b_ids = {binding_id_for_alias(a, task.graph_id) for a in task.selected_bindings}
    source_b_id = (
        binding_id_for_alias(task.selected_bindings[0], task.graph_id)
        if len(task.selected_bindings) == 1 else None
    )
    nav_q = NavigationSearchQuery(
        query=str(plan.get("graph_query") or plan["query"]),
        scope="all", source_binding_id=source_b_id,
    )
    nav_res = inv_store.navigation_search(task.graph_id, nav_q)
    elapsed = time.perf_counter_ns() - t0
    acct = ByteLayerAccounting(observed_output_payload_bytes=_json_len(nav_res))
    if nav_res.get("status") == "unavailable":
        reason = str(nav_res.get("reason") or "backend_unsupported")
        env = qc.unavailable_envelope(requested_mode=requested_mode, scope=scope, reason=reason)
        return ExecutionState.UNAVAILABLE, env, elapsed, acct
    page_evidence = GraphPageEvidence()
    scan = nav_res.get("scan")
    if nav_res.get("status") != "ok" or not isinstance(scan, Mapping) or scan.get("complete") is not True:
        reason = str(nav_res.get("reason") or "navigation_scan_incomplete")
        page_evidence.omit(reason)
        env = _build_available_envelope(
            requested_mode, qc.MatchSurface.STORED_METADATA, scope, [],
            omissions=page_evidence.omissions, scope_complete=False,
        )
        return ExecutionState.COMPLETED, env, elapsed, acct
    hits: list[qc.QueryHit] = []
    for node in nav_res.get("nodes", ()):
        c_key = str(node.get("canonical_key") or "") or None
        for loc in node.get("locations", ()):
            src = loc.get("source", {})
            b_id, rel = str(src.get("binding_id") or ""), str(src.get("source_relative_path") or "")
            if not b_id or not rel or b_id not in selected_b_ids:
                continue
            if not source_path_matches_prefix(rel, task.source_path_prefix):
                continue
            ev_loc = qc.EvaluationLocator(
                binding_id=b_id, source_relative_path=rel,
                start_line=_opt_pos_int(loc.get("start_line")),
                end_line=_opt_pos_int(loc.get("end_line")), canonical_key=c_key,
                evidence_key=str(loc.get("evidence_key") or "") or None,
                link_kind=str(loc.get("evidence_role") or "") or None,
            ).validate()
            hits.append(_make_hit(ev_loc, qc.MatchSurface.STORED_METADATA, len(hits) + 1))
    if len(hits) > limit:
        page_evidence.omit("graph_result_limit")
    env = _build_available_envelope(
        requested_mode, qc.MatchSurface.STORED_METADATA, scope, hits[:limit],
        omissions=page_evidence.omissions, scope_complete=page_evidence.scope_complete,
    )
    return ExecutionState.COMPLETED, env, elapsed, acct


def _evaluate_graph_body_safety_refusal(
    config: Any, task: EvaluationTask, requested_mode: qc.QueryMode
) -> str | None:
    if (
        requested_mode != qc.QueryMode.LITERAL_CAPTURED_TEXT
        and task.intended_match_surface != "captured_text"
    ):
        return None
    graph_cfg = next(
        (
            g for g in getattr(config, "graphs", ())
            if (getattr(g, "id", None) or getattr(g, "graph_id", None)) == task.graph_id
        ),
        None,
    )
    if graph_cfg is None:
        return None
    bindings = getattr(
        graph_cfg, "effective_source_bindings", getattr(graph_cfg, "source_bindings", ())
    )
    by_alias = {getattr(b, "alias", ""): b for b in bindings}
    explicit = bool(getattr(graph_cfg, "explicit_source_bindings", False))
    graph_priv = (
        ALLOWED_GRAPH_PRIVACY if explicit
        else str(getattr(graph_cfg, "privacy", ALLOWED_GRAPH_PRIVACY))
    )
    reasons: list[str] = []
    for alias in task.selected_bindings:
        b = by_alias.get(alias)
        if b is None:
            continue
        if (
            graph_priv != ALLOWED_GRAPH_PRIVACY
            or str(getattr(b, "privacy", "")) != ALLOWED_BINDING_PRIVACY
        ):
            reasons.append("binding_privacy_not_authorized")
            continue
        sk_raw = getattr(b, "source_kind", "")
        s_kind = str(getattr(sk_raw, "value", sk_raw)).lower()
        role = str(getattr(b, "role", "")).lower()
        if s_kind in {"email_archive", "feed_archive"} or role in {
            "email", "mailbox", "feed", "feeds"
        }:
            reasons.append("email_or_feed_body_not_authorized")
        elif str(getattr(b, "evidence_retention", "")) != ALLOWED_EVIDENCE_RETENTION:
            reasons.append("binding_retention_not_authorized")
    if task.selected_bindings and len(reasons) == len(task.selected_bindings):
        return reasons[0]
    return None


def _execute_direct_handoff(
    inv_store: _LocationsReadStore, task: EvaluationTask, scope: qc.QueryScope,
    requested_mode: qc.QueryMode, selected_b_ids: tuple[str, ...],
) -> _GraphTaskOutcome:
    t0 = time.perf_counter_ns()
    c_key = str(task.permitted_query_plan.get("canonical_key") or "file:core/pkg/pipeline.py")
    loc_res = inv_store.node_locations(
        task.graph_id, NodeLocationsQuery(canonical_key=c_key, evidence_role="direct", limit=5)
    )
    elapsed = time.perf_counter_ns() - t0
    acct = ByteLayerAccounting(observed_output_payload_bytes=_json_len(loc_res))
    if loc_res.get("status") != "ok":
        reason = str(loc_res.get("reason") or "backend_unsupported")
        env = qc.unavailable_envelope(requested_mode=requested_mode, scope=scope, reason=reason)
        return ExecutionState.UNAVAILABLE, env, elapsed, acct
    dh_hits: list[qc.QueryHit] = []
    for loc in loc_res.get("locations", ()):
        if not isinstance(loc, Mapping):
            continue
        src = loc.get("source")
        if isinstance(src, Mapping) and src.get("binding_id") and src.get("source_relative_path"):
            b_id, rel = str(src["binding_id"]), str(src["source_relative_path"])
        else:
            parsed = _parse_prefixed_graph_path(str(loc.get("path") or ""))
            if parsed is None:
                continue
            b_id, rel = parsed
        if b_id not in set(selected_b_ids):
            continue
        if not source_path_matches_prefix(rel, task.source_path_prefix):
            continue
        ev_loc = qc.EvaluationLocator(
            binding_id=b_id, source_relative_path=rel,
            start_line=_opt_pos_int(loc.get("start_line")),
            end_line=_opt_pos_int(loc.get("end_line")), canonical_key=c_key,
            evidence_key=str(loc.get("evidence_key") or "") or None,
            link_kind=str(loc.get("evidence_role") or loc.get("link_kind") or "") or None,
        ).validate()
        dh_hits.append(_make_hit(ev_loc, qc.MatchSurface.DIRECT_HANDOFF, len(dh_hits) + 1))
    page_evidence = GraphPageEvidence()
    if loc_res.get("has_more") is True:
        page_evidence.omit("direct_location_limit")
    if not dh_hits and page_evidence.scope_complete:
        env = qc.unavailable_envelope(
            requested_mode=requested_mode, scope=scope, reason="no_direct_locations_in_scope"
        )
        return ExecutionState.UNAVAILABLE, env, elapsed, acct
    env = _build_available_envelope(
        requested_mode, qc.MatchSurface.DIRECT_HANDOFF, scope, dh_hits,
        with_provenance=False, omissions=page_evidence.omissions,
        scope_complete=page_evidence.scope_complete,
    )
    return ExecutionState.COMPLETED, env, elapsed, acct


def _execute_graph_baseline_task(
    task: EvaluationTask, home_root: Path, *, psql_command: str = "psql",
    expected_pin: ObservationPublicationPin | None = None,
) -> _GraphTaskOutcome:
    """Execute one evaluation task against the real SQLite or PostgreSQL read store."""
    config = load_graph_registry_config_home(home_root)
    backend = "sqlite" if isinstance(config, LocalSqliteConfig) else "postgresql"
    requested_mode = qc.QueryMode(task.requested_mode)
    selected_b_ids = tuple(
        sorted(binding_id_for_alias(a, task.graph_id) for a in task.selected_bindings)
    )
    scope = qc.QueryScope(
        graph_id=task.graph_id, backend=backend,
        selected_binding_ids=selected_b_ids, source_path_prefix=task.source_path_prefix,
    )
    refusal_code = _evaluate_graph_body_safety_refusal(config, task, requested_mode)
    zero_bytes = ByteLayerAccounting(observed_output_payload_bytes=0)
    if refusal_code is not None:
        omission = qc.OmissionRecord(
            binding_id=selected_b_ids[0] if selected_b_ids else "scope",
            source_relative_path=None, reason_code=refusal_code,
            detail="graph baseline refuses unauthorized body request from binding policy",
        )
        env = qc.refused_envelope(
            requested_mode=requested_mode, scope=scope,
            refusal_code=refusal_code, omissions=(omission,),
        )
        return ExecutionState.REFUSED, env, 0, zero_bytes
    if requested_mode in {qc.QueryMode.LITERAL_CAPTURED_TEXT, qc.QueryMode.SEMANTIC_DISCOVERY}:
        reason = (
            "captured_text_surface_unsupported_by_metadata_graph"
            if requested_mode == qc.QueryMode.LITERAL_CAPTURED_TEXT
            else "semantic_discovery_not_admitted"
        )
        env = qc.unavailable_envelope(requested_mode=requested_mode, scope=scope, reason=reason)
        return ExecutionState.UNAVAILABLE, env, 0, zero_bytes
    inv_store = investigation_stores(config).investigation_store()
    plan = task.permitted_query_plan
    if (
        str(plan.get("workflow") or "") == "direct_handoff"
        or task.intended_match_surface == "direct_handoff"
    ):
        return _execute_direct_handoff(inv_store, task, scope, requested_mode, selected_b_ids)
    if requested_mode == qc.QueryMode.RANKED_DISCOVERY:
        return _execute_navigation_or_locations_mode(inv_store, task, scope, requested_mode)

    t0 = time.perf_counter_ns()
    q_text, limit = str(plan.get("graph_query") or plan["query"]), int(plan.get("limit", 10))
    is_inv = requested_mode == qc.QueryMode.GRAPH_INVESTIGATION
    surf = qc.MatchSurface.GRAPH_TOPOLOGY if is_inv else qc.MatchSurface.STORED_METADATA
    page_evidence = GraphPageEvidence()
    if is_inv:
        seed = str(plan.get("seed_node") or "file:core/pkg/pipeline.py")
        hits_list, payload_bytes = _traverse_graph_neighborhood(
            inv_store, config, task, seed, q_text, limit, selected_b_ids,
            psql_command=psql_command, expected_pin=expected_pin, page_evidence=page_evidence,
        )
    else:
        obs_res = graph_scope.query_fenced_current_observations(
            config, graph_id=task.graph_id, query=q_text, limit=limit,
            task_scope=task,
            expected_pin=expected_pin, psql_command=psql_command,
        )
        page_evidence.observe(obs_res)
        payload_bytes, hits_list = _json_len(obs_res.rows), []
        for row in obs_res.rows:
            loc = _locator_from_observation_row(row) if isinstance(row, Mapping) else None
            if loc is None:
                page_evidence.omit("observation_locator_unavailable")
                continue
            if loc.binding_id not in set(selected_b_ids) or not source_path_matches_prefix(
                loc.source_relative_path, task.source_path_prefix,
            ):
                raise CurrentObservationReadError("graph_observation_scope_mismatch", "current reader returned an out-of-scope locator")
            hits_list.append(_make_hit(loc, surf, len(hits_list) + 1))
            if len(hits_list) >= limit:
                break
    elapsed = time.perf_counter_ns() - t0
    env = _build_available_envelope(requested_mode, surf, scope, hits_list[:limit],
        omissions=page_evidence.omissions, scope_complete=page_evidence.scope_complete)
    return ExecutionState.COMPLETED, env, elapsed, ByteLayerAccounting(observed_output_payload_bytes=payload_bytes)
execute_graph_baseline_task = graph_scope.bind_graph_execution(_execute_graph_baseline_task)
