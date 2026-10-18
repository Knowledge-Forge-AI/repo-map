"""Optional caller-side one-hop view; only supplied callbacks perform graph reads.

Inspect one exact key, then explicitly select up to two displayed related keys.
Projection/export are pure. Locations are unverified leads, never source reads.
See docs/ops/source-navigation.md for the local workflow and producer semantics.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

ToolCall = Callable[[str, dict[str, Any]], dict[str, Any]]
MAX_CAPTURE_BYTES = 262_144
MAX_VIEW_BYTES = 65_536
NODE_FIELDS = ("canonical_key kind display_name graph_key_version confidence conflict "
               "first_seen_run_id last_seen_run_id repository_identity").split()
EDGE_FIELDS = ("source_key edge_kind target_key graph_key_version identity_metadata "
               "identity_metadata_hash confidence conflict first_seen_run_id last_seen_run_id").split()
FACT_FIELDS = ("repository_identity graph_key_version accepted_publication location_run_id "
               "run_id revision publication source_generation").split()
WINDOW_FIELDS = ("has_more complete truncated node_limit edge_limit node_offset edge_offset "
                 "nodes_has_more edges_has_more").split()


def _pick(value: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    return {key: value[key] for key in fields if key in value}


def _copy(value: Any, limit: int) -> Any:
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if len(payload.encode("utf-8")) > limit:
        raise ValueError("reduce selected content")
    return json.loads(payload)


def _failure(view: dict[str, Any], reason: str) -> dict[str, Any]:
    return {**view, "status": reason, "next_action": {
        "action": "native_navigation_or_review", "reason": reason,
    }}


def _known_key(value: Any) -> bool:
    return (type(value) is str and bool(value) and "[REDACTED]" not in value
            and "[private-path]" not in value and not value.endswith("...[truncated]"))


def _callable(value: Any) -> bool:
    """Runtime validation at the optional callback boundary, independent of typing."""
    return callable(value)


def _options(graph_id: str, canonical_key: str, direction: str,
             node_limit: int, edge_limit: int, repository_identity: str | None) -> bool:
    return (type(graph_id) is str and bool(graph_id)
            and _known_key(canonical_key)
            and type(direction) is str and direction in {"in", "out", "both"}
            and type(node_limit) is int and 1 <= node_limit <= 8
            and type(edge_limit) is int and 1 <= edge_limit <= 16
            and (repository_identity is None or
                 (type(repository_identity) is str and bool(repository_identity))))


def _facts(payload: dict[str, Any]) -> dict[str, Any]:
    graph = payload.get("graph", {})
    return {**_pick(payload, FACT_FIELDS), "graph": _pick(graph, ["graph_id", "repository_name"])}


def _identity(facts: dict[str, Any], selection: dict[str, Any]) -> str:
    if facts["graph"].get("graph_id") != selection["graph_id"]:
        return "unbound_or_wrong_graph"
    expected = selection.get("repository_identity")
    if expected is not None and "repository_identity" in facts and facts["repository_identity"] != expected:
        return "wrong_repository"
    return "selected_graph"


def _direction(edge: dict[str, Any], center: str) -> str:
    source, target = edge.get("source_key"), edge.get("target_key")
    if source == center == target:
        return "self"
    if source == center:
        return "out"
    if target == center:
        return "in"
    return "not_incident" if _known_key(source) and _known_key(target) else "unknown"


def _node_state(key: Any, rows: list[dict[str, Any]], displayed: list[dict[str, Any]]) -> str:
    found = [row for row in rows if key is not None and row.get("canonical_key") == key]
    if not found:
        return "not_returned"
    if len(found) != 1 or not isinstance(found[0].get("kind"), str):
        return "conflicting_or_unknown"
    return "displayed" if found[0] in displayed else "outside_display_window"


def _relationships(payload: dict[str, Any], selection: dict[str, Any],
                   node_limit: int, edge_limit: int) -> dict[str, Any]:
    result, key = payload["result"], selection["canonical_key"]
    center, nodes, edges = result["center"], result["nodes"], result["edges"]
    if center is not None and center.get("canonical_key") != key:
        raise ValueError("wrong center")
    shown_nodes = nodes[:node_limit]
    endpoints = ([center] if center is not None else []) + nodes
    shown_edges = []
    for edge in edges[:edge_limit]:
        direction = _direction(edge, key)
        shown_edges.append({**_pick(edge, EDGE_FIELDS), "direction": direction,
            "in_requested_direction": None if direction == "unknown" else
                                      direction == "self" or direction == selection["direction"]
                                      or (selection["direction"] == "both" and direction in {"in", "out"}),
            "source_node_status": _node_state(edge.get("source_key"), endpoints, endpoints[:1] + shown_nodes),
            "target_node_status": _node_state(edge.get("target_key"), endpoints, endpoints[:1] + shown_nodes),
            "explanation": {"status": "unavailable", "reason": "legacy_project_identity_not_established"}})
    # The producer's node window is independent of its edge window. Only actual,
    # unique displayed node identities are selectable, including with withheld edges.
    eligible = [row["canonical_key"] for row in shown_nodes
                if center is not None and _known_key(row.get("canonical_key")) and row["canonical_key"] != key
                and _node_state(row["canonical_key"], endpoints, endpoints) == "displayed"
                and not row.get("conflict", False)
                and not any(edge["in_requested_direction"] is False and row["canonical_key"] in
                            (edge.get("source_key"), edge.get("target_key")) for edge in shown_edges)
                and all(row.get(field, expected) == expected for field, expected in {
                    "repository_identity": selection.get("repository_identity", payload.get("repository_identity")),
                    "graph_key_version": None if center is None else center.get("graph_key_version"),
                }.items() if expected is not None)]
    return {"center": None if center is None else _pick(center, NODE_FIELDS),
            "nodes": [_pick(row, NODE_FIELDS) for row in shown_nodes], "edges": shown_edges,
            "eligible_keys": eligible,
            "backend_window": {"outer": _pick(payload, WINDOW_FIELDS),
                               "result": _pick(result, WINDOW_FIELDS)},
            "backend_completeness": "unknown" if not any(k in result or k in payload for k in
                                      ("has_more", "complete", "truncated", "nodes_has_more", "edges_has_more"))
                                    else "see_backend_window",
            "display_window": {"node_limit": node_limit, "edge_limit": edge_limit,
                               "nodes_truncated": len(nodes) > node_limit,
                               "edges_truncated": len(edges) > edge_limit},
            "absence_scope": "only returned relations in this selected read and direction"}


def project_neighborhood(response: dict[str, Any], *, graph_id: str, canonical_key: str,
                         direction: str = "both", node_limit: int = 8, edge_limit: int = 16,
                         repository_identity: str | None = None) -> dict[str, Any]:
    """Pure projection of an existing handle_tool_call envelope; zero graph calls.

    Windows are independent. Missing endpoint nodes never become invented nodes.
    Backend completeness is preserved when supplied and otherwise stays unknown.
    """
    selection = dict(graph_id=graph_id, canonical_key=canonical_key, direction=direction)
    if repository_identity is not None:
        selection["repository_identity"] = repository_identity
    view: dict[str, Any] = {"selection": selection, "graph_calls": 0, "locations": [],
                            "snapshot_relation": "not_guaranteed", "source_verification": "not_performed"}
    base = dict(view)
    if not _options(graph_id, canonical_key, direction, node_limit, edge_limit, repository_identity):
        return _failure(view, "invalid_options")
    try:
        reply = _copy(response, MAX_CAPTURE_BYTES)
        if reply.get("isError"):
            return _failure(view, "neighborhood_failed")
        payload = reply["structuredContent"]
        facts = _facts(payload)
        view.update(facts=facts, identity=_identity(facts, selection))
        if payload.get("depth") != 1 or payload.get("read_only") is not True:
            return _failure(view, "unusable_neighborhood")
        view.update(_relationships(payload, selection, node_limit, edge_limit))
        if view["identity"] != "selected_graph":
            view["eligible_keys"] = []
            return _failure(view, view["identity"])
        view["status"] = "captured"
        return _copy(view, MAX_VIEW_BYTES)
    except (KeyError, TypeError, AttributeError, ValueError, RecursionError, UnicodeError):
        return _failure({**base, "eligible_keys": []}, "unusable_or_reduction_needed")


def inspect_related(*, graph_id: str, canonical_key: str, direction: str = "both",
                    node_limit: int = 8, edge_limit: int = 16,
                    repository_identity: str | None = None,
                    tool_call: ToolCall | None = None) -> dict[str, Any]:
    """One graph-scoped neighborhood read; no search, retry or implicit expansion."""
    options: dict[str, Any] = dict(graph_id=graph_id, canonical_key=canonical_key, direction=direction,
                                  node_limit=node_limit, edge_limit=edge_limit, repository_identity=repository_identity)
    base = project_neighborhood({}, **options)
    if not _options(**options):
        return base
    if tool_call is None:
        return _failure(base, "helper_absent")
    if not _callable(tool_call):
        return _failure(base, "invalid_options")
    try:
        reply = tool_call("repomap_neighborhood", {"graph_id": graph_id, "node": canonical_key,
                                                  "direction": direction, "depth": 1})
        return {**project_neighborhood(reply, **options), "graph_calls": 1}
    except Exception:  # Optional callback failure: no exception/payload leakage or retry.
        return _failure({**base, "graph_calls": 1}, "neighborhood_failed")


def _joined_location(reply: dict[str, Any], view: dict[str, Any], key: str) -> dict[str, Any]:
    if reply.get("isError"):
        raise ValueError("locator refused")
    lead = reply["structuredContent"]
    facts, previous = _facts(lead), view["facts"]
    if (_identity(facts, view["selection"]) != "selected_graph"
            or lead.get("canonical_key") != key
            or lead.get("detail") != "compact" or lead.get("evidence_role") != "direct"
            or lead.get("schema_version") != 1 or lead.get("read_only") is not True):
        raise ValueError("unbound location")
    for field in ("repository_name",):
        if field in previous["graph"] and facts["graph"].get(field) != previous["graph"][field]:
            raise ValueError("repository mismatch")
    for field in ("repository_identity", "graph_key_version"):
        if field in previous and facts.get(field) != previous[field]:
            raise ValueError("identity mismatch")
    selected = next(row for row in view["nodes"] if row.get("canonical_key") == key)
    for field in ("repository_identity", "graph_key_version"):
        if field in selected and facts.get(field) != selected[field]:
            raise ValueError("selected node identity mismatch")
    current = _pick(previous, ["accepted_publication", "run_id", "revision", "publication", "source_generation"])
    newer = _pick(facts, list(current))
    comparison = ("unavailable" if not current or len(newer) != len(current) else
                  "equal_labels_only" if current == newer else "different")
    rows = {}
    for window in ("locations", "historical_locations"):
        if len(lead[window]) > 2:
            raise ValueError("reduce locator window")
        rows[window] = [_pick(row, ("path source_relative_path start_line end_line path_status range_status "
                         "run_id evidence_role publication_relation binding publication").split())
                        | {"raw_observation": _pick(row.get("raw_observation", {}), ["status", "kind", "ordinal"])}
                        for row in lead[window]]
    return {"canonical_key": key, "lookup": "returned", "facts": facts,
            "publication_comparison": comparison, **rows,
            **_pick(lead, ("status reason freshness ambiguity has_more historical_has_more location_scope path_namespace "
                           "bindings publications limit evidence_role metadata_location").split())}


def expand_selected(view: dict[str, Any], selected_keys: tuple[str, ...] = (), *,
                    tool_call: ToolCall | None = None) -> dict[str, Any]:
    """One locator per explicit displayed key, once per captured view; at most two.

    Validate the entire selection before any callback. Each failed lookup is local.
    Reusing an expanded view refuses further calls, including retries of failures.
    """
    try:
        result = _copy(view, MAX_VIEW_BYTES)
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return _failure({}, "unusable_or_reduction_needed")
    if type(selected_keys) is tuple and not selected_keys:
        return result
    if (type(selected_keys) is not tuple or len(selected_keys) > 2
            or any(type(key) is not str for key in selected_keys)
            or len(set(selected_keys)) != len(selected_keys)
            or any(key not in result.get("eligible_keys", []) for key in selected_keys)
            or result.get("expansion_attempted") or result.get("status") != "captured"):
        return _failure(result, "invalid_selection")
    if tool_call is not None and not _callable(tool_call):
        return _failure(result, "invalid_options")
    result["expansion_attempted"] = True
    if tool_call is None:
        return _failure(result, "helper_absent")
    for key in selected_keys:
        result["graph_calls"] += 1
        try:
            reply = _copy(tool_call("repomap_node_locations", {
                "graph_id": result["selection"]["graph_id"], "canonical_key": key,
                "evidence_role": "direct", "detail": "compact", "limit": 2,
            }), MAX_CAPTURE_BYTES)
            location = _joined_location(reply, result, key)
            _copy({**result, "locations": result["locations"] + [location]}, MAX_VIEW_BYTES)
        except Exception:  # Independent optional lookup: retain relationships and other locations.
            location = {"canonical_key": key, "lookup": "failed_or_unbound_or_reduction_needed",
                        "next_action": {"action": "native_navigation_or_review"}}
        result["locations"].append(location)
    return result


def export(view: dict[str, Any]) -> str:
    """Pure JSON presentation; reject excess bytes without truncating keys or paths."""
    payload = json.dumps(_copy(view, MAX_VIEW_BYTES), ensure_ascii=False, sort_keys=True) + "\n"
    if len(payload.encode("utf-8")) > MAX_VIEW_BYTES:
        raise ValueError("reduce selected content")
    return payload
