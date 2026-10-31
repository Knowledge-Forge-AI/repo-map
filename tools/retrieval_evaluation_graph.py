"""Current-graph baseline adapter over real SQLite Local and PostgreSQL read stores (S3)."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import common_lore_index.retrieval.query_contracts as qc
from common_lore_index.ops.config_local import LocalSqliteConfig, load_graph_registry_config_home
from common_lore_index.retrieval.projection_policy import (
    ALLOWED_BINDING_PRIVACY, ALLOWED_EVIDENCE_RETENTION, ALLOWED_GRAPH_PRIVACY,
)
from common_lore_index.server.investigation_read_store import (
    ConfiguredNeighborhoodQuery, GraphSearchQuery, InvestigationReadStore,
)
from common_lore_index.server.ops import investigation_stores
from common_lore_index.storage.navigation_search import NavigationSearchQuery
from common_lore_index.storage.node_locations import NodeLocationsQuery
from repomap_test_support.retrieval_evaluation_fixture import (
    MIXED_V1_BINDING_IDS, binding_id_for_alias,
)
from retrieval_evaluation_accounting import ByteLayerAccounting
from retrieval_evaluation_grading import ExecutionState
from retrieval_evaluation_schema import EvaluationTask

_GraphTaskOutcome = tuple[ExecutionState, qc.QueryEnvelope, int, ByteLayerAccounting]


def _parse_prefixed_graph_path(graph_path: str) -> tuple[str, str] | None:
    if "/" not in graph_path:
        return None
    alias, rel = graph_path.split("/", 1)
    b_id = MIXED_V1_BINDING_IDS.get(alias)
    return (b_id, rel) if b_id is not None and rel else None


def _opt_pos_int(val: Any) -> int | None:
    return int(val) if isinstance(val, int) and val >= 1 else None


def _make_hit(locator: qc.EvaluationLocator, surface: qc.MatchSurface, rank: int) -> qc.QueryHit:
    return qc.QueryHit(locator=locator, match_surface=surface, rank=rank, score=1.0 / rank)


def _json_len(obj: Any) -> int:
    return len(json.dumps(obj, default=str).encode("utf-8"))


def _locator_from_observation_row(
    row: Mapping[str, Any], *, canonical_key: str | None = None
) -> qc.EvaluationLocator | None:
    meta = row.get("metadata")
    if isinstance(meta, Mapping):
        b_id, rel = meta.get("binding_id"), meta.get("source_relative_path")
        start = meta.get("start_line") or meta.get("line")
        end = meta.get("end_line") or start
        if isinstance(b_id, str) and isinstance(rel, str) and b_id and rel:
            s_int = _opt_pos_int(start)
            e_int = int(end) if isinstance(end, int) and s_int is not None and end >= s_int else s_int
            return qc.EvaluationLocator(
                binding_id=b_id, source_relative_path=rel,
                start_line=s_int, end_line=e_int, canonical_key=canonical_key,
            ).validate()
    raw_path = row.get("path")
    parsed = _parse_prefixed_graph_path(raw_path) if isinstance(raw_path, str) else None
    if parsed is not None:
        return qc.EvaluationLocator(
            binding_id=parsed[0], source_relative_path=parsed[1], canonical_key=canonical_key
        ).validate()
    return None


def _build_available_envelope(
    mode: qc.QueryMode, surface: qc.MatchSurface, scope: qc.QueryScope,
    hits: list[qc.QueryHit], *, with_provenance: bool = True,
) -> qc.QueryEnvelope:
    prov = (
        {"adapter_id": f"current_graph_baseline:{scope.backend}", "backend": scope.backend}
        if with_provenance else {}
    )
    return qc.QueryEnvelope(
        contract_version=qc.QUERY_CONTRACT_VERSION, requested_mode=mode, effective_mode=mode,
        match_surface=surface, scope=scope,
        ordering_policy_version=qc.DEFAULT_ORDERING_POLICY_VERSION,
        capability_state=qc.CapabilityState.AVAILABLE, hits=tuple(hits),
        scope_complete=True, provenance=prov,
    ).validate()


def _execute_navigation_or_locations_mode(
    inv_store: InvestigationReadStore, task: EvaluationTask,
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
    hits: list[qc.QueryHit] = []
    for node in nav_res.get("nodes", ()):
        c_key = str(node.get("canonical_key") or "") or None
        for loc in node.get("locations", ()):
            src = loc.get("source", {})
            b_id, rel = str(src.get("binding_id") or ""), str(src.get("source_relative_path") or "")
            if not b_id or not rel or b_id not in selected_b_ids:
                continue
            if task.source_path_prefix and not rel.startswith(task.source_path_prefix):
                continue
            ev_loc = qc.EvaluationLocator(
                binding_id=b_id, source_relative_path=rel,
                start_line=_opt_pos_int(loc.get("start_line")),
                end_line=_opt_pos_int(loc.get("end_line")), canonical_key=c_key,
                evidence_key=str(loc.get("evidence_key") or "") or None,
                link_kind=str(loc.get("evidence_role") or "") or None,
            ).validate()
            hits.append(_make_hit(ev_loc, qc.MatchSurface.STORED_METADATA, len(hits) + 1))
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
    env = _build_available_envelope(requested_mode, qc.MatchSurface.STORED_METADATA, scope, hits)
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


def _traverse_graph_neighborhood(
    inv_store: InvestigationReadStore, task: EvaluationTask, seed_node: str,
    q_text: str, limit: int, selected_b_ids: tuple[str, ...],
) -> tuple[list[qc.QueryHit], int]:
    visited: dict[str, tuple[int, Any]] = {}
    incident_by_file: dict[str, list[str]] = {}
    frontier: list[tuple[int, str]] = [(0, seed_node)]
    payload_bytes, expansions = 0, 0
    while frontier and expansions < 16:
        hop, node_key = frontier.pop(0)
        if node_key in visited:
            continue
        nb = inv_store.configured_neighborhood(
            ConfiguredNeighborhoodQuery(
                graph_id=task.graph_id, node=node_key,
                direction="both", depth=1, graph_key_version=1,
            )
        )
        expansions += 1
        nb_dict = nb.to_dict() if hasattr(nb, "to_dict") else (nb if isinstance(nb, Mapping) else {})
        payload_bytes += _json_len(nb_dict)
        center = nb_dict.get("center")
        if not isinstance(center, Mapping):
            continue
        visited[str(center.get("canonical_key") or node_key)] = (hop, center)
        edges = nb_dict.get("edges", ())
        for edge in edges if isinstance(edges, (list, tuple)) else ():
            if not isinstance(edge, Mapping):
                continue
            s_k, t_k = str(edge.get("source_key") or ""), str(edge.get("target_key") or "")
            if s_k.startswith("file:") and not t_k.startswith("file:"):
                incident_by_file.setdefault(s_k.removeprefix("file:"), []).append(t_k)
            elif t_k.startswith("file:") and not s_k.startswith("file:"):
                incident_by_file.setdefault(t_k.removeprefix("file:"), []).append(s_k)
        neighbors = nb_dict.get("nodes", ())
        for n_obj in neighbors if isinstance(neighbors, (list, tuple)) else ():
            if not isinstance(n_obj, Mapping):
                continue
            n_key = str(n_obj.get("canonical_key") or "")
            if not n_key or n_key in visited:
                continue
            if hop + 1 <= 3:
                frontier.append((hop + 1, n_key))
            else:
                visited[n_key] = (hop + 1, n_obj)

    reached = sorted(
        (hop, k.removeprefix("file:")) for k, (hop, _) in visited.items() if k.startswith("file:")
    )
    hits_list: list[qc.QueryHit] = []
    q_lower, selected_set = q_text.lower(), set(selected_b_ids)
    for _hop, graph_path in reached:
        parsed = _parse_prefixed_graph_path(graph_path)
        if parsed is None or parsed[0] not in selected_set:
            continue
        if task.source_path_prefix and not parsed[1].startswith(task.source_path_prefix):
            continue
        cands = incident_by_file.get(graph_path, [])
        attr_key = next(
            (k for k in cands if q_lower and q_lower in k.lower()),
            cands[0] if cands else f"file:{graph_path}",
        )
        obs_res = inv_store.search(
            GraphSearchQuery(
                graph_id=task.graph_id, target="observations", query=q_text,
                kind=None, path=graph_path, limit=limit, offset=0, include_raw=False,
            )
        )
        payload_bytes += _json_len(obs_res.rows)
        for row in obs_res.rows:
            loc = (
                _locator_from_observation_row(row, canonical_key=attr_key)
                if isinstance(row, Mapping) else None
            )
            if loc is not None and loc.binding_id in selected_set:
                hits_list.append(_make_hit(loc, qc.MatchSurface.GRAPH_TOPOLOGY, len(hits_list) + 1))
                if len(hits_list) >= limit:
                    return hits_list, payload_bytes
    return hits_list, payload_bytes


def _execute_direct_handoff(
    inv_store: InvestigationReadStore, task: EvaluationTask, scope: qc.QueryScope,
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
        if task.source_path_prefix and not rel.startswith(task.source_path_prefix):
            continue
        ev_loc = qc.EvaluationLocator(
            binding_id=b_id, source_relative_path=rel,
            start_line=_opt_pos_int(loc.get("start_line")),
            end_line=_opt_pos_int(loc.get("end_line")), canonical_key=c_key,
            evidence_key=str(loc.get("evidence_key") or "") or None,
            link_kind=str(loc.get("evidence_role") or loc.get("link_kind") or "") or None,
        ).validate()
        dh_hits.append(_make_hit(ev_loc, qc.MatchSurface.DIRECT_HANDOFF, len(dh_hits) + 1))
    if not dh_hits:
        env = qc.unavailable_envelope(
            requested_mode=requested_mode, scope=scope, reason="no_direct_locations_in_scope"
        )
        return ExecutionState.UNAVAILABLE, env, elapsed, acct
    env = _build_available_envelope(
        requested_mode, qc.MatchSurface.DIRECT_HANDOFF, scope, dh_hits, with_provenance=False
    )
    return ExecutionState.COMPLETED, env, elapsed, acct


def execute_graph_baseline_task(task: EvaluationTask, home_root: Path) -> _GraphTaskOutcome:
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
    if is_inv:
        seed = str(plan.get("seed_node") or "file:core/pkg/pipeline.py")
        hits_list, payload_bytes = _traverse_graph_neighborhood(
            inv_store, task, seed, q_text, limit, selected_b_ids
        )
    else:
        obs_res = inv_store.search(
            GraphSearchQuery(
                graph_id=task.graph_id, target="observations", query=q_text,
                kind=None, path=None, limit=limit, offset=0, include_raw=False,
            )
        )
        payload_bytes, hits_list = _json_len(obs_res.rows), []
        for row in obs_res.rows:
            loc = _locator_from_observation_row(row) if isinstance(row, Mapping) else None
            if loc is None or loc.binding_id not in set(selected_b_ids):
                continue
            if task.source_path_prefix and not loc.source_relative_path.startswith(task.source_path_prefix):
                continue
            hits_list.append(_make_hit(loc, surf, len(hits_list) + 1))
            if len(hits_list) >= limit:
                break
    elapsed = time.perf_counter_ns() - t0
    env = _build_available_envelope(requested_mode, surf, scope, hits_list[:limit])
    return ExecutionState.COMPLETED, env, elapsed, ByteLayerAccounting(observed_output_payload_bytes=payload_bytes)
