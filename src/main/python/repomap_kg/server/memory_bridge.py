"""Read-only server-memory JSONL bridge for local operations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from repomap_kg import __version__
from repomap_kg.ops.config import (
    OpsConfig,
    load_ops_config as load_ops_config,
    load_ops_config_home as load_ops_config_home,
    redact_text as redact_text,
)
import repomap_kg.server._server_memory_parsing as _server_memory_parsing
from repomap_kg.server._server_memory_parsing import (
    DEFAULT_SERVER_MEMORY_LIMIT as DEFAULT_SERVER_MEMORY_LIMIT,
    MAX_JSONL_FILE_BYTES as MAX_JSONL_FILE_BYTES,
    MAX_JSONL_LINES as MAX_JSONL_LINES,
    MAX_METADATA_STRING_LENGTH as MAX_METADATA_STRING_LENGTH,
    MAX_SERVER_MEMORY_ENTRIES as MAX_SERVER_MEMORY_ENTRIES,
    MAX_SERVER_MEMORY_LIMIT as MAX_SERVER_MEMORY_LIMIT,
    MAX_SNIPPET_LENGTH as MAX_SNIPPET_LENGTH,
    build_label as build_label,
    build_server_memory_entry as build_server_memory_entry,
    classify_entry as classify_entry,
    entry_search_text as entry_search_text,
    expand_server_memory_payload as expand_server_memory_payload,
    extract_path_candidates as extract_path_candidates,
    extract_url_candidates as extract_url_candidates,
    redact_server_memory_text as redact_server_memory_text,
    safe_string as safe_string,
    safe_text_parts as safe_text_parts,
    truncate as truncate,
    validate_server_memory_limit as validate_server_memory_limit,
    validate_server_memory_offset as validate_server_memory_offset,
    validate_server_memory_query as validate_server_memory_query,
)
from repomap_kg.server._server_memory_records import (
    ServerMemoryDiagnostic as ServerMemoryDiagnostic,
    ServerMemoryEntry as ServerMemoryEntry,
)


ENV_OPS_CONFIG = "REPOMAP_OPS_CONFIG"


@dataclass(frozen=True)
class ServerMemoryCatalog:
    enabled: bool
    mode: str
    path_display: str
    path_checked: bool
    path_exists: bool | None
    path_kind: str | None
    file_count: int
    entries: tuple[ServerMemoryEntry, ...]
    diagnostics: tuple[ServerMemoryDiagnostic, ...]
    malformed_line_count: int


def parse_server_memory_file(
    path: Path,
    *,
    start_index: int = 0,
    max_bytes: int | None = None,
    max_lines: int | None = None,
    max_entries: int | None = None,
) -> tuple[list[ServerMemoryEntry], list[ServerMemoryDiagnostic], int]:
    return _server_memory_parsing.parse_server_memory_file(
        path,
        start_index=start_index,
        max_bytes=MAX_JSONL_FILE_BYTES if max_bytes is None else max_bytes,
        max_lines=MAX_JSONL_LINES if max_lines is None else max_lines,
        max_entries=MAX_SERVER_MEMORY_ENTRIES if max_entries is None else max_entries,
    )


def server_memory_summary_payload(
    *,
    config_path: str | Path | None = None,
    config_home: str | Path | None = None,
) -> dict[str, Any]:
    config = load_server_memory_ops_config(config_path, config_home=config_home)
    catalog = load_server_memory_catalog(config)
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "enabled": catalog.enabled,
        "mode": catalog.mode,
        "path": path_payload(catalog),
        "summary": summary_counts(catalog),
        "diagnostics": [diagnostic.to_jsonable() for diagnostic in catalog.diagnostics],
        "linking": link_payload(),
        "safety": server_memory_safety_markers(catalog),
    }


def server_memory_search_payload(
    *,
    config_path: str | Path | None = None,
    config_home: str | Path | None = None,
    query: str,
    kind: str | None = None,
    limit: int = DEFAULT_SERVER_MEMORY_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    config = load_server_memory_ops_config(config_path, config_home=config_home)
    catalog = load_server_memory_catalog(config)
    safe_query = validate_server_memory_query(query)
    safe_limit = validate_server_memory_limit(limit)
    safe_offset = validate_server_memory_offset(offset)
    query_lower = safe_query.lower()
    matched = [
        entry
        for entry in catalog.entries
        if (kind is None or entry.kind == kind)
        and query_lower in entry_search_text(entry).lower()
    ]
    window = matched[safe_offset : safe_offset + safe_limit]
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "enabled": catalog.enabled,
        "mode": catalog.mode,
        "path": path_payload(catalog),
        "query": safe_query,
        "kind": kind,
        "limit": safe_limit,
        "offset": safe_offset,
        "result_count": len(window),
        "total": len(matched),
        "has_more": safe_offset + len(window) < len(matched),
        "results": [entry.to_jsonable() for entry in window],
        "diagnostics": [diagnostic.to_jsonable() for diagnostic in catalog.diagnostics],
        "linking": link_payload(),
        "safety": server_memory_safety_markers(catalog),
    }


def load_server_memory_catalog(config: OpsConfig) -> ServerMemoryCatalog:
    memory = config.server_memory
    path_display = redact_text(memory.path)
    if not memory.enabled:
        return ServerMemoryCatalog(
            enabled=False,
            mode=memory.mode,
            path_display=path_display,
            path_checked=False,
            path_exists=None,
            path_kind=None,
            file_count=0,
            entries=(),
            diagnostics=(
                ServerMemoryDiagnostic(
                    "server-memory-disabled",
                    "server-memory bridge is disabled in unified TOML config",
                ),
            ),
            malformed_line_count=0,
        )

    path = Path(memory.path_expanded)
    diagnostics: list[ServerMemoryDiagnostic] = []
    files: list[Path] = []
    path_exists = path.exists()
    path_kind: str | None = None
    if path.is_file():
        path_kind = "file"
        files = [path]
    elif path.is_dir():
        path_kind = "directory"
        files = sorted(candidate for candidate in path.iterdir() if candidate.suffix == ".jsonl")
        if not files:
            diagnostics.append(
                ServerMemoryDiagnostic(
                    "server-memory-directory-empty",
                    "server-memory directory contains no immediate JSONL files",
                )
            )
    else:
        diagnostics.append(
            ServerMemoryDiagnostic(
                "server-memory-path-missing",
                "server-memory path does not exist or is not a file/directory",
                severity="error",
            )
        )

    entries: list[ServerMemoryEntry] = []
    malformed_lines = 0
    for file_path in files:
        if len(entries) >= MAX_SERVER_MEMORY_ENTRIES:
            diagnostics.append(
                ServerMemoryDiagnostic(
                    "server-memory-entry-limit",
                    "server-memory entry limit reached",
                    file=str(file_path),
                )
            )
            break
        file_entries, file_diagnostics, file_malformed = parse_server_memory_file(
            file_path,
            start_index=len(entries),
            max_bytes=MAX_JSONL_FILE_BYTES,
            max_lines=MAX_JSONL_LINES,
            max_entries=MAX_SERVER_MEMORY_ENTRIES,
        )
        entries.extend(file_entries)
        diagnostics.extend(file_diagnostics)
        malformed_lines += file_malformed

    return ServerMemoryCatalog(
        enabled=True,
        mode=memory.mode,
        path_display=path_display,
        path_checked=True,
        path_exists=path_exists,
        path_kind=path_kind,
        file_count=len(files),
        entries=tuple(entries[:MAX_SERVER_MEMORY_ENTRIES]),
        diagnostics=tuple(diagnostics),
        malformed_line_count=malformed_lines,
    )


def load_server_memory_ops_config(
    config_path: str | Path | None = None,
    *,
    config_home: str | Path | None = None,
) -> OpsConfig:
    if config_home is not None:
        return load_ops_config_home(config_home)
    path_value = config_path or os.environ.get(ENV_OPS_CONFIG)
    if path_value:
        return load_ops_config(Path(path_value).expanduser())
    return load_ops_config_home()


def summary_counts(catalog: ServerMemoryCatalog) -> dict[str, int]:
    entries = catalog.entries
    return {
        "entry_count": len(entries),
        "entity_count": sum(1 for entry in entries if entry.kind == "entity"),
        "relation_count": sum(1 for entry in entries if entry.kind == "relation"),
        "unknown_count": sum(1 for entry in entries if entry.kind == "unknown"),
        "malformed_line_count": catalog.malformed_line_count,
        "redaction_count": sum(1 for entry in entries if entry.redacted),
        "local_path_pointer_count": sum(len(entry.local_paths) for entry in entries),
        "url_pointer_count": sum(len(entry.urls) for entry in entries),
        "diagnostic_count": len(catalog.diagnostics),
    }


def path_payload(catalog: ServerMemoryCatalog) -> dict[str, Any]:
    return {
        "display": catalog.path_display,
        "checked": catalog.path_checked,
        "exists": catalog.path_exists,
        "kind": catalog.path_kind,
        "file_count": catalog.file_count,
    }


def link_payload() -> dict[str, bool]:
    return {
        "implemented": False,
        "storage_lookup": False,
        "graph_roots_read": False,
    }


def server_memory_safety_markers(catalog: ServerMemoryCatalog) -> dict[str, bool]:
    return {
        "local_only": True,
        "read_only": True,
        "server_memory_read": catalog.enabled and catalog.path_checked,
        "server_memory_mutated": False,
        "source_trees_mutated": False,
        "graph_refresh": False,
        "discovery": False,
        "source_acquisition": False,
        "network_fetch": False,
        "destructive_db_actions": False,
    }


def format_server_memory_summary_table(payload: Mapping[str, Any]) -> str:
    summary = payload["summary"]
    path = payload["path"]
    safety = payload["safety"]
    return "\n".join(
        [
            (
                "server_memory: "
                f"enabled={str(payload['enabled']).lower()} "
                f"mode={payload['mode']} "
                f"path_checked={str(path['checked']).lower()} "
                f"kind={path['kind'] or 'none'}"
            ),
            (
                "entries: "
                f"total={summary['entry_count']} "
                f"entities={summary['entity_count']} "
                f"relations={summary['relation_count']} "
                f"unknown={summary['unknown_count']}"
            ),
            (
                "pointers: "
                f"local_paths={summary['local_path_pointer_count']} "
                f"urls={summary['url_pointer_count']} "
                f"linked=0"
            ),
            (
                "diagnostics: "
                f"malformed={summary['malformed_line_count']} "
                f"redactions={summary['redaction_count']} "
                f"total={summary['diagnostic_count']}"
            ),
            (
                "safety: "
                f"read_only={str(safety['read_only']).lower()} "
                f"server_memory_mutated={str(safety['server_memory_mutated']).lower()} "
                f"network_fetch={str(safety['network_fetch']).lower()}"
            ),
        ]
    )


def format_server_memory_search_table(payload: Mapping[str, Any]) -> str:
    lines = [
        (
            "server_memory_search: "
            f"query={payload['query']} "
            f"results={payload['result_count']} "
            f"total={payload['total']} "
            f"has_more={str(payload['has_more']).lower()}"
        )
    ]
    for entry in payload["results"]:
        lines.append(
            f"- line={entry['line']} kind={entry['kind']} label={entry['label']}"
        )
    return "\n".join(lines)
