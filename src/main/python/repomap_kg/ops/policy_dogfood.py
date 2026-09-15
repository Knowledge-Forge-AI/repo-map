"""Public-safe operational policy dogfooding readback."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

from repomap_kg import __version__
from repomap_kg.ops.config import (
    PRIVATE_PRIVACY,
    REDACTED,
    OpsConfig,
    OpsGraphConfig,
    load_ops_config,
    load_ops_config_home,
    redact_text,
)
from repomap_kg.server.memory_bridge import (
    ServerMemoryCatalog,
    ServerMemoryEntry,
    load_server_memory_catalog,
    summary_counts,
    truncate,
)

MAX_POLICY_EXAMPLES = 5
MAX_SUGGESTED_RULES = 8
MAX_EXCLUDE_SUMMARY = 12

DURABLE_POLICY_TERMS = (
    "agents",
    "policy",
    "rule",
    "instruction",
    "boundary",
    "should",
    "must",
)
PRIVATE_LOCAL_TERMS = (
    "private",
    "local",
    "machine",
    "path",
    ".codex",
    ".rpl.toml",
    "/path/to",
)
EPHEMERAL_TERMS = (
    "temporary",
    "ephemeral",
    "session",
    "task",
    "todo",
    "expires",
)


def policy_dogfood_payload(
    *,
    graph_id: str,
    config_path: str | Path | None = None,
    config_home: str | Path | None = None,
) -> dict[str, Any]:
    config = load_policy_ops_config(config_path=config_path, config_home=config_home)
    graph = find_policy_graph(config, graph_id)
    diagnostics = graph_access_diagnostics(graph)
    catalog = (
        load_server_memory_catalog(config)
        if graph.enabled and graph.mcp_visible
        else empty_server_memory_catalog(config)
    )
    buckets = classify_policy_boundaries(graph, catalog.entries)
    server_memory = server_memory_policy_summary(catalog)
    suggestions = build_agents_suggestions(graph, buckets, server_memory)
    return {
        "server": "repomap-kg",
        "version": __version__,
        "command": "policy-dogfood",
        "read_only": True,
        "graph": policy_graph_payload(graph),
        "server_memory": server_memory,
        "policy_boundary": buckets,
        "agents_refinement": {
            "applied": False,
            "target": "AGENTS.md",
            "suggested_rules": suggestions,
            "report_only": True,
        },
        "leakage_checks": {
            "public_safe": True,
            "secrets_redacted": True,
            "raw_server_memory_jsonl_emitted": False,
            "raw_private_policy_content_emitted": False,
            "real_private_roots_read": False,
            "agents_modified": False,
        },
        "diagnostics": diagnostics,
        "safety": policy_safety_markers(catalog),
    }


def load_policy_ops_config(
    *,
    config_path: str | Path | None = None,
    config_home: str | Path | None = None,
) -> OpsConfig:
    if config_home is not None:
        return load_ops_config_home(config_home)
    if config_path is not None:
        return load_ops_config(Path(config_path).expanduser())
    return load_ops_config_home()


def find_policy_graph(config: OpsConfig, graph_id: str) -> OpsGraphConfig:
    if not isinstance(graph_id, str) or not graph_id.strip():
        raise ValueError("graph id is required")
    for graph in config.graphs:
        if graph.id == graph_id:
            return graph
    raise ValueError(f"unknown graph id: {graph_id}")


def graph_access_diagnostics(graph: OpsGraphConfig) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    if not graph.enabled:
        diagnostics.append(
            {
                "severity": "warning",
                "code": "graph-disabled",
                "message": "policy dogfooding does not inspect disabled graphs",
            }
        )
    if not graph.mcp_visible:
        diagnostics.append(
            {
                "severity": "warning",
                "code": "graph-not-mcp-visible",
                "message": "policy dogfooding does not inspect hidden graphs",
            }
        )
    return diagnostics


def empty_server_memory_catalog(config: OpsConfig) -> ServerMemoryCatalog:
    memory = config.server_memory
    return ServerMemoryCatalog(
        enabled=memory.enabled,
        mode=memory.mode,
        path_display=redact_text(memory.path),
        path_checked=False,
        path_exists=None,
        path_kind=None,
        file_count=0,
        entries=(),
        diagnostics=(),
        malformed_line_count=0,
    )


def policy_graph_payload(graph: OpsGraphConfig) -> dict[str, Any]:
    private = graph.privacy in PRIVATE_PRIVACY
    return {
        "graph_id": graph.id,
        "name": redact_text(graph.name),
        "repository_name": graph.repository_name_display,
        "privacy": graph.privacy,
        "enabled": graph.enabled,
        "mcp_visible": graph.mcp_visible,
        "private": private,
        "root_path_display": "[private-root]" if private else redact_text(graph.root_path),
        "root_path_checked": False,
        "exclude_paths_count": len(graph.exclude_paths),
        "exclude_paths_enforced": True,
        "exclude_paths_summary": [
            redact_text(path) for path in graph.exclude_paths[:MAX_EXCLUDE_SUMMARY]
        ],
    }


def server_memory_policy_summary(catalog: ServerMemoryCatalog) -> dict[str, Any]:
    counts = summary_counts(catalog)
    return {
        "enabled": catalog.enabled,
        "mode": catalog.mode,
        "path_checked": catalog.path_checked,
        "path_kind": catalog.path_kind,
        "file_count": catalog.file_count,
        "entry_count": counts["entry_count"],
        "entity_count": counts["entity_count"],
        "relation_count": counts["relation_count"],
        "unknown_count": counts["unknown_count"],
        "local_path_pointer_count": counts["local_path_pointer_count"],
        "url_pointer_count": counts["url_pointer_count"],
        "redaction_count": counts["redaction_count"],
        "diagnostic_count": counts["diagnostic_count"],
    }


def classify_policy_boundaries(
    graph: OpsGraphConfig,
    entries: Iterable[ServerMemoryEntry],
) -> dict[str, dict[str, Any]]:
    entry_list = tuple(entries)
    buckets = {
        "durable_operational_rules": bucket_payload(
            entry
            for entry in entry_list
            if entry_matches(entry, DURABLE_POLICY_TERMS)
        ),
        "private_local_preferences": bucket_payload(
            entry
            for entry in entry_list
            if entry_matches(entry, PRIVATE_LOCAL_TERMS) or entry.local_paths
        ),
        "ephemeral_task_state": bucket_payload(
            entry
            for entry in entry_list
            if entry_matches(entry, EPHEMERAL_TERMS)
        ),
        "generated_graph_evidence": {
            "count": 1 if graph.enabled and graph.mcp_visible else 0,
            "examples": (
                [
                    truncate(
                        f"configured graph {graph.id} "
                        f"({graph.repository_name_display}, {graph.privacy})",
                        160,
                    )
                ]
                if graph.enabled and graph.mcp_visible
                else []
            ),
        },
        "secrets_sensitive": bucket_payload(
            entry for entry in entry_list if entry.redacted or REDACTED in entry.snippet
        ),
    }
    return buckets


def bucket_payload(entries: Iterable[ServerMemoryEntry]) -> dict[str, Any]:
    entry_list = tuple(entries)
    return {
        "count": len(entry_list),
        "examples": [safe_entry_label(entry) for entry in entry_list[:MAX_POLICY_EXAMPLES]],
    }


def entry_matches(entry: ServerMemoryEntry, terms: tuple[str, ...]) -> bool:
    text = " ".join(
        (
            entry.kind,
            entry.name,
            entry.entry_type,
            entry.label,
            entry.snippet,
            " ".join(entry.local_paths),
        )
    ).lower()
    return any(term in text for term in terms)


def safe_entry_label(entry: ServerMemoryEntry) -> str:
    return truncate(redact_text(entry.label or entry.name or entry.kind), 160)


def build_agents_suggestions(
    graph: OpsGraphConfig,
    buckets: Mapping[str, Mapping[str, Any]],
    server_memory: Mapping[str, Any],
) -> list[str]:
    suggestions = [
        "Document that server-memory is a compact card catalog, not the policy library.",
        "Document that RepoMap graph evidence is generated readback and should not be manually duplicated as policy.",
        "Require explicit user approval before reading or editing private operational policy roots.",
        "Keep secrets, credentials, raw JSONL payloads, and private machine-specific facts out of public AGENTS.md.",
        "Keep destructive database lifecycle work in local administrative CLI flows, not ordinary MCP tools.",
    ]
    if graph.exclude_paths:
        suggestions.append(
            "Document that folder-tree graphs exclude server-memory runtime files before ingestion."
        )
    if int(server_memory.get("local_path_pointer_count", 0)) > 0:
        suggestions.append(
            "Treat server-memory path pointers as navigation hints that require privacy checks before opening targets."
        )
    if int(buckets["ephemeral_task_state"]["count"]) > 0:
        suggestions.append(
            "Keep ephemeral task state in session notes or bounded server-memory cards instead of durable AGENTS.md policy."
        )
    return suggestions[:MAX_SUGGESTED_RULES]


def policy_safety_markers(catalog: ServerMemoryCatalog) -> dict[str, bool]:
    return {
        "local_only": True,
        "read_only": True,
        "server_memory_read": catalog.enabled and catalog.path_checked,
        "server_memory_mutated": False,
        "no_graph_refresh": True,
        "no_discovery": True,
        "no_graph_root_reads": True,
        "no_private_root_reads": True,
        "no_source_tree_mutation": True,
        "no_agents_modification": True,
        "no_destructive_db_actions": True,
        "no_db_lifecycle_invocation": True,
        "no_network_fetch": True,
    }


def format_policy_dogfood_table(payload: Mapping[str, Any]) -> str:
    graph = payload["graph"]
    memory = payload["server_memory"]
    buckets = payload["policy_boundary"]
    safety = payload["safety"]
    return "\n".join(
        [
            (
                "policy_dogfood: "
                f"graph={graph['graph_id']} "
                f"privacy={graph['privacy']} "
                f"enabled={str(graph['enabled']).lower()} "
                f"mcp_visible={str(graph['mcp_visible']).lower()}"
            ),
            (
                "server_memory: "
                f"enabled={str(memory['enabled']).lower()} "
                f"read={str(safety['server_memory_read']).lower()} "
                f"entries={memory['entry_count']} "
                f"redactions={memory['redaction_count']}"
            ),
            (
                "policy_buckets: "
                f"durable={buckets['durable_operational_rules']['count']} "
                f"private_local={buckets['private_local_preferences']['count']} "
                f"ephemeral={buckets['ephemeral_task_state']['count']} "
                f"graph_evidence={buckets['generated_graph_evidence']['count']} "
                f"sensitive={buckets['secrets_sensitive']['count']}"
            ),
            (
                "agents: "
                f"suggestions={len(payload['agents_refinement']['suggested_rules'])} "
                f"agents_applied={str(payload['agents_refinement']['applied']).lower()}"
            ),
            (
                "safety: "
                f"read_only={str(safety['read_only']).lower()} "
                f"graph_root_reads={str(not safety['no_graph_root_reads']).lower()} "
                f"server_memory_mutated={str(safety['server_memory_mutated']).lower()} "
                f"destructive_db_actions={str(not safety['no_destructive_db_actions']).lower()}"
            ),
        ]
    )
