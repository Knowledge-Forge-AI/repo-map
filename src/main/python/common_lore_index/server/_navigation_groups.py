"""Scope and group a complete bounded candidate scan after public projection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from common_lore_index.server._ops_sanitization import _public_location, _relative_path, sanitize_jsonable
from common_lore_index.storage.navigation_search import DOC_KINDS, HINT_LIMIT, NavigationSearchQuery


def _withheld(value: Any) -> bool:
    return isinstance(value, str) and any(marker in value for marker in (
        "[REDACTED]", "[private-path]", "[private-root]", "...[truncated]",
    ))


def _destination(location: dict[str, Any], markers: tuple[str, ...]) -> dict[str, Any] | None:
    source = location["source"]
    path = _relative_path(source.get("source_relative_path"), markers)
    if (location.get("source_identity_status") != "verified_vector" or not location["path"] or not path
            or not isinstance(source.get("binding_id"), str)
            or not isinstance(source.get("snapshot_id"), str)
            or type(source.get("binding_revision")) is not int
            or any(_withheld(value) for value in (*source.values(), location["path"]))):
        return None
    return {"source_binding_id": source["binding_id"], "binding_revision": source["binding_revision"],
            "snapshot_id": source["snapshot_id"], "source_relative_path": path,
            "run_id": location["run_id"], "publication_relation": location["publication_relation"],
            "path_namespace": "source_relative", "graph_path": location["path"]}


def _member(node: dict[str, Any], markers: tuple[str, ...]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    locations = [_public_navigation_location(row, markers) for row in node["locations"]]
    result = sanitize_jsonable({key: value for key, value in node.items() if key != "locations"},
                               private_markers=markers)
    result.update(source_hints=[_hint(row) for row in locations[:HINT_LIMIT]],
                  source_hints_has_more=len(locations) > HINT_LIMIT,
                  source_hint_count=len(locations), matched=True,
                  identity_status="available" if result["canonical_key"] == node["canonical_key"]
                  and not _withheld(result["canonical_key"]) else "withheld")
    return result, locations


def _public_navigation_location(row: dict[str, Any], markers: tuple[str, ...]) -> dict[str, Any]:
    public = _public_location(row, markers)
    # Redaction must never manufacture an identity shared by unrelated subjects.
    identity_fields = ("binding_id", "binding_revision", "snapshot_id", "source_relative_path")
    if any(row["source"].get(key) != public["source"].get(key) for key in identity_fields):
        public["source_identity_status"] = "withheld"
    return public


def location_in_scope(row: dict[str, Any], query: NavigationSearchQuery,
                      markers: tuple[str, ...]) -> bool:
    """Same definitive public admission for SQL predicates and presentation."""
    return _in_scope([_public_navigation_location(row, markers)], query, markers)


def source_scope_admission(query: NavigationSearchQuery, markers: tuple[str, ...]) -> Callable[[dict[str, Any]], bool]:
    """Bind public policy once per read, outside SQLite's predicate evaluations."""
    return lambda row: location_in_scope(row, query, markers)


def _hint(row: dict[str, Any]) -> dict[str, Any]:
    """Keep navigation facts after sanitization; full evidence uses the locator."""
    result = {key: row[key] for key in (
        "path", "path_namespace", "path_status", "start_line", "end_line", "range_status",
        "run_id", "publication_relation", "evidence_role", "source_identity_status", "source",
    )}
    result["raw_observation"] = {key: row["raw_observation"][key]
                                 for key in ("status", "ordinal", "kind")}
    return result


def _in_scope(locations: list[dict[str, Any]], query: NavigationSearchQuery,
              markers: tuple[str, ...]) -> bool:
    if query.source_binding_id is None:
        return True
    prefix = None if query.source_path_prefix is None else query.source_path_prefix.rstrip("/")
    for row in locations:
        source = row["source"]
        path = _relative_path(source.get("source_relative_path"), markers)
        # Unknown/withheld/unbound evidence cannot satisfy an explicit restriction.
        if _destination(row, markers) is None or source.get("binding_id") != query.source_binding_id:
            continue
        if prefix is None or path == prefix or (path is not None and path.startswith(prefix + "/")):
            return True
    return False


def _identity(locations: list[dict[str, Any]], markers: tuple[str, ...]) -> tuple[dict[str, Any] | None, str | None]:
    if not locations:
        return None, "no_direct_evidence"
    destinations = [_destination(row, markers) for row in locations]
    if any(item is None for item in destinations):
        return None, "missing_withheld_or_unbound_identity"
    first = destinations[0]
    if any(item != first for item in destinations):
        return None, "conflicting_direct_identities"
    return first, None


def group_page(scan: dict[str, Any], query: NavigationSearchQuery,
               markers: tuple[str, ...]) -> dict[str, Any]:
    if scan["status"] != "ok":
        return {"results": [], "result_count": 0, "has_more": scan["status"] == "incomplete",
                "page_end": query.offset, "scope_excluded_count": None}
    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    excluded = 0
    for index, node in enumerate(scan["nodes"]):
        member, locations = _member(node, markers)
        if not _in_scope(locations, query, markers):
            excluded += 1
            continue
        destination, reason = _identity(locations, markers)
        if member["identity_status"] == "withheld":
            reason = "canonical_identity_withheld"
        is_document = node["kind"] in DOC_KINDS
        grouped = (query.grouping == "source_document" and is_document and destination is not None
                   and member["identity_status"] == "available")
        identity = ("document", *destination.values()) if grouped and destination is not None else ("node", index)
        if identity not in groups:
            groups[identity] = {
                "basis": "direct_source_document" if grouped else "singleton",
                "unresolved_reason": reason, "destination": destination, "members": [], "context": [],
            }
        groups[identity]["members"].append(member)
    ordered = list(groups.values())  # Insertion order is the first matching canonical key.
    page = ordered[query.offset:query.offset + query.limit]
    for group in page:
        members = group["members"]
        group["matched_member_count"] = len(members)
        group["member_has_more"] = len(members) > query.member_limit
        group["members"] = members[:query.member_limit]
    result = {"results": page, "result_count": len(page), "has_more": len(ordered) > query.offset + query.limit,
              "page_end": query.offset + len(page), "scope_excluded_count": excluded}
    if "admission" in scan["scan"]:
        result.update(scope_excluded_count=None, scope_excluded_count_basis="not_counted_before_admission",
                      post_admission_scope_excluded_count=excluded)
    return result
