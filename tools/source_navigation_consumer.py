"""Optional handoff-first example; graph reads and caller-side source reads are separate.

Supply binding IDs mapped to intended checkout roots and a task-specific text
check. No host path is inferred from a graph path, binding alias or node key.
The returned trace describes simulated consumer decisions, not live model use.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, TypeGuard

ToolCall = Callable[[str, dict[str, Any]], dict[str, Any]]
MAX_SOURCE_BYTES = 65_536
MAX_SOURCE_LINES = 80


def _relative_path(value: Any) -> TypeGuard[str]:
    return (isinstance(value, str) and bool(value) and not value.startswith(("/", "~"))
            and ":" not in value and "\\" not in value
            and all(part not in {"", ".", ".."} for part in value.split("/"))
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _verify_source(
    location: dict[str, Any], bindings: Mapping[str, Path], repository_identity: str,
    source_check: Callable[[str], bool], trace: list[dict[str, Any]],
) -> bool:
    """One bounded local read, with an explicit mapping and caller's source check."""
    relative = location.get("source_relative_path")
    binding_id = location.get("binding_id")
    root = bindings.get(binding_id) if isinstance(binding_id, str) else None
    if (location.get("repository_identity") != repository_identity
            or root is None or not _relative_path(relative)):
        trace.append({"action": "source_refused", "reason": "unmapped_location"})
        return False
    start, end = location.get("start_line"), location.get("end_line")
    if start is None and end is None:
        first_line, last_line, path_only = 1, MAX_SOURCE_LINES, True
    elif (type(start) is int and type(end) is int
          and 1 <= start <= end and end - start < MAX_SOURCE_LINES):
        first_line, last_line, path_only = start, end, False
    else:
        trace.append({"action": "source_refused", "reason": "invalid_or_large_range"})
        return False
    try:
        root = root.resolve(strict=True)
        target = (root / relative).resolve(strict=True)
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError("outside intended source workspace")
        event = {"action": "source_read", "source_relative_path": relative,
                 "start_line": start, "end_line": end}
        trace.append(event)
        with target.open("rb") as stream:
            data = stream.read(MAX_SOURCE_BYTES + 1)
        if len(data) > MAX_SOURCE_BYTES:
            event["verified"] = False
            return False
        lines = data.decode("utf-8").splitlines(keepends=True)
        selected = lines[first_line - 1:last_line]
        valid = (path_only or last_line <= len(lines)) and bool(source_check("".join(selected)))
        event["verified"] = valid
        return valid
    except (OSError, UnicodeError, ValueError):
        trace.append({"action": "source_refused", "reason": "source_unavailable"})
        return False


def _direct_location(
    lead: dict[str, Any], graph_id: str, canonical_key: str, repository_identity: str,
) -> dict[str, Any] | None:
    """Accept one complete current direct lead; never choose history or metadata."""
    expected = {"detail": "compact", "schema_version": 1, "read_only": True,
                "repository_identity": repository_identity, "canonical_key": canonical_key,
                "evidence_role": "direct", "path_namespace": "graph_source_relative",
                "status": "located", "has_more": False, "freshness": "unverified",
                "ambiguity": "single_stored_location", "location_scope": "accepted_run"}
    if any(lead.get(key) != value for key, value in expected.items()):
        return None
    if lead["graph"]["graph_id"] != graph_id or len(lead["locations"]) != 1:
        return None
    row = lead["locations"][0]
    expected_row = {"publication_relation": "accepted_run", "evidence_role": "direct",
                    "run_id": lead["accepted_publication"]["run_id"], "path_status": "available"}
    if any(row.get(key) != value for key, value in expected_row.items()):
        return None
    if (row["run_id"] != lead["location_run_id"] or not _relative_path(row["path"])
            or row["raw_observation"]["status"] != "available"):
        return None
    binding_index = row["binding"]
    if type(binding_index) is not int or not 0 <= binding_index < len(lead["bindings"]):
        return None
    return {**lead["bindings"][binding_index], "repository_identity": repository_identity,
            "source_relative_path": row.get("source_relative_path"),
            "start_line": row["start_line"], "end_line": row["end_line"]}


def navigate(
    *, graph_id: str, repository_identity: str, bindings: Mapping[str, Path],
    source_check: Callable[[str], bool], handoff: dict[str, Any] | None = None,
    canonical_key: str | None = None, query: str | None = None,
    tool_call: ToolCall | None = None,
    source_text_paths: tuple[Path, ...] | None = None,
) -> dict[str, Any]:
    """Return verified source or bounded native-search fallback; never retry a helper.

    Handoff records explicitly supply repository_identity, binding_id,
    source_relative_path and nullable start_line/end_line. Verification means
    the supplied text check passed at read time, not that the whole checkout
    matches a graph snapshot. Path-only records check at most the first 80 lines.
    Tool callbacks use the existing handle_tool_call result envelope.
    Supplying source_text_paths explicitly requests literal source-text search
    within a tuple of caller-selected paths; other containers raise TypeError.
    Its bounded plan is returned, never run, and takes priority over canonical_key.
    A supplied handoff is verified first. None preserves indexed-subject lookup.
    """
    trace: list[dict[str, Any]] = []

    def finish(branch: str, verified: bool, native_action: dict[str, Any] | None = None) -> dict[str, Any]:
        if not verified:
            trace.append(native_action if native_action is not None else
                         {"action": "native_search", "reason": "bounded_task_search_needed"})
        return {"branch": branch, "outcome": "verified" if verified else "native_search",
                "graph_calls": sum(event["action"] == "tool_call" for event in trace),
                "trace": trace}

    if handoff is not None:
        verified = _verify_source(handoff, bindings, repository_identity, source_check, trace)
        if verified or source_text_paths is None:
            return finish("handoff", verified)
    if source_text_paths is not None:
        if not isinstance(source_text_paths, tuple):
            raise TypeError("source_text_paths must be a tuple of paths")
        return finish("source_text", False, {
            "action": "native_search", "reason": "caller_declared_source_text",
            "literal": query, "paths": [str(path) for path in source_text_paths],
            "max_matches": 20, "ready": bool(query) and bool(source_text_paths),
        })
    if tool_call is None:
        return finish("helper_absent", False)

    def read(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        trace.append({"action": "tool_call", "tool": name, "arguments": arguments})
        response = tool_call(name, arguments)
        if response.get("isError"):
            raise ValueError("helper refused")
        return response["structuredContent"]

    branch = "locator" if canonical_key else "search_locator"
    try:
        if canonical_key is None:
            if not query:
                return finish("subject_unresolved", False)
            found = read("repomap_search_nodes", {"graph_id": graph_id, "query": query, "limit": 2})
            if found["has_more"] or len(found["results"]) != 1:
                return finish(branch, False)
            canonical_key = found["results"][0]["canonical_key"]
        lead = read("repomap_node_locations", {
            "graph_id": graph_id, "canonical_key": canonical_key,
            "evidence_role": "direct", "detail": "compact", "limit": 2,
        })
        location = _direct_location(lead, graph_id, canonical_key, repository_identity)
    except Exception:  # Optional helper boundary: bounded fallback, no payload or exception leakage.
        trace.append({"action": "helper_failed", "reason": "unusable_helper_result"})
        return finish(branch, False)
    if location is None:
        return finish(branch, False)
    return finish(branch, _verify_source(location, bindings, repository_identity, source_check, trace))
