"""Sanitization, redaction, and display helpers for MCP operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from repomap_kg.ops.config import (
    PRIVATE_PRIVACY,
    REDACTED,
    OpsGraphConfig,
    is_credentialed_url,
    is_secret_key,
    redact_text,
)
from repomap_kg.server._ops_records import McpOpsGraphContext

MAX_STRING_LENGTH = 500
PRIVATE_PATH_DISPLAY = "[private-path]"
PRIVATE_DATABASE_DISPLAY = "[private-database]"
GRAPH_ROOT_DISPLAY = "[graph-root]"
GRAPH_DATABASE_DISPLAY = "[graph-database]"
RAW_PAYLOAD_METADATA_SEMANTICS = (
    "include_raw controls the full raw payload field only; metadata remains included"
)
SUMMARY_ROOT_KEYS = frozenset(("root_path", "root_path_display", "root_path_expanded"))
SAFE_VALUE_KEYS = frozenset(
    {
        "canonical_key",
        "source_canonical_key",
        "target_canonical_key",
        "graph_key_version",
        "payload_hash",
        "identity_metadata_hash",
    }
)


def graph_database_display(graph: OpsGraphConfig, database: str | None) -> str | None:
    value = database or graph.database
    if not value:
        return value
    if graph.privacy in PRIVATE_PRIVACY:
        return PRIVATE_DATABASE_DISPLAY
    return GRAPH_DATABASE_DISPLAY


def graph_root_display(graph: OpsGraphConfig) -> str:
    if graph.privacy in PRIVATE_PRIVACY:
        return "[private-root]"
    return GRAPH_ROOT_DISPLAY


def safety_markers() -> dict[str, bool]:
    return {
        "read_only": True,
        "no_refresh": True,
        "no_discovery": True,
        "no_source_tree_reads": True,
        "no_source_mutation": True,
        "no_destructive_db_actions": True,
        "no_server_memory_read": True,
        "no_source_acquisition": True,
        "no_remote_exposure": True,
    }


def latest_run_consistency(payload: Mapping[str, Any]) -> dict[str, Any]:
    complete_without_finished_at = (
        payload.get("latest_run_status") == "complete"
        and payload.get("latest_run_finished_at") is None
    )
    if complete_without_finished_at:
        return {
            "complete_without_finished_at": True,
            "diagnostic": "complete run has no finished timestamp in storage",
        }
    return {"complete_without_finished_at": False}


def raw_payload_policy(include_raw: bool) -> dict[str, Any]:
    return {
        "include_raw": include_raw,
        "payload_included": include_raw,
        "metadata_included": True,
        "metadata_semantics": RAW_PAYLOAD_METADATA_SEMANTICS,
    }


def sanitize_jsonable(
    value: Any,
    *,
    private_markers: tuple[str, ...] = (),
) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_jsonable(
                redacted_mapping_item(key, item),
                private_markers=private_markers,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            sanitize_jsonable(item, private_markers=private_markers)
            for item in value
        ]
    if isinstance(value, tuple):
        return [
            sanitize_jsonable(item, private_markers=private_markers)
            for item in value
        ]
    if isinstance(value, str):
        return sanitize_text(value, private_markers=private_markers)
    return value


def sanitize_text(value: str, *, private_markers: tuple[str, ...] = ()) -> str:
    result = truncate_text(redact_text(value))
    if private_markers and any(marker in result for marker in private_markers):
        return PRIVATE_PATH_DISPLAY
    return result


def readback_path_markers(context: McpOpsGraphContext) -> tuple[str, ...]:
    markers: set[str] = set()
    values = [
        context.graph.root_path,
        context.graph.root_path_expanded,
        context.config.config_path,
        context.config.config_home,
        *context.config.config_files,
        str(Path.home()),
        Path.home().name,
    ]
    if context.graph.privacy in PRIVATE_PRIVACY:
        for binding in context.graph.effective_source_bindings:
            values.extend((binding.root_path, binding.root_path_expanded))
    for value in values:
        if isinstance(value, str):
            marker = value.strip()
            if marker and marker not in {".", "/", "~", "[private-root]"}:
                markers.add(marker)
    return tuple(sorted(markers, key=len, reverse=True))


def sanitize_summary_jsonable(value: Any, graph: OpsGraphConfig) -> Any:
    return _sanitize_summary_jsonable(value, graph, field_name=None)


def _sanitize_summary_jsonable(
    value: Any,
    graph: OpsGraphConfig,
    *,
    field_name: str | None,
) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_summary_jsonable(
                redacted_mapping_item(key, item),
                graph,
                field_name=str(key),
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _sanitize_summary_jsonable(item, graph, field_name=field_name)
            for item in value
        ]
    if isinstance(value, tuple):
        return [
            _sanitize_summary_jsonable(item, graph, field_name=field_name)
            for item in value
        ]
    if isinstance(value, str):
        if field_name in SUMMARY_ROOT_KEYS:
            return summary_root_value(value, graph)
        return truncate_text(redact_text(value))
    return value


def summary_root_value(value: str | None, graph: OpsGraphConfig) -> str | None:
    if value is None:
        return None
    return graph_root_display(graph)


def redacted_mapping_item(key: Any, value: Any) -> Any:
    text_key = str(key)
    if text_key in SAFE_VALUE_KEYS:
        return value
    if is_secret_key(text_key):
        return REDACTED
    if isinstance(value, str) and is_credentialed_url(value):
        return REDACTED
    return value


def truncate_text(value: str) -> str:
    if len(value) <= MAX_STRING_LENGTH:
        return value
    return value[: MAX_STRING_LENGTH - 15] + "...[truncated]"
