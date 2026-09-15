"""Parsing, extraction, and sanitization for server-memory JSONL files."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from repomap_kg.ops.config import (
    REDACTED,
    is_credentialed_url,
    is_secret_key,
)
from repomap_kg.server._server_memory_records import (
    ServerMemoryDiagnostic,
    ServerMemoryEntry,
)

DEFAULT_SERVER_MEMORY_LIMIT = 20
MAX_SERVER_MEMORY_LIMIT = 100
MAX_SNIPPET_LENGTH = 300
MAX_METADATA_STRING_LENGTH = 500
MAX_JSONL_FILE_BYTES = 1_000_000
MAX_JSONL_LINES = 10_000
MAX_SERVER_MEMORY_ENTRIES = 2_000

URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")
PATH_PATTERN = re.compile(
    r"(?<![\w:/])("
    r"~/?[^\s,\"'<>]+|"
    r"\.{1,2}/[^\s,\"'<>]+|"
    r"/[A-Za-z0-9._~/-]+|"
    r"[A-Za-z0-9._/-]+\.(?:md|py|toml|jsonl|json|yaml|yml)"
    r")"
)


def parse_server_memory_file(
    path: Path,
    *,
    start_index: int = 0,
    max_bytes: int = MAX_JSONL_FILE_BYTES,
    max_lines: int = MAX_JSONL_LINES,
    max_entries: int = MAX_SERVER_MEMORY_ENTRIES,
) -> tuple[list[ServerMemoryEntry], list[ServerMemoryDiagnostic], int]:
    diagnostics: list[ServerMemoryDiagnostic] = []
    entries: list[ServerMemoryEntry] = []
    malformed = 0

    try:
        file_size = path.stat().st_size
    except OSError as error:
        return (
            entries,
            [
                ServerMemoryDiagnostic(
                    "server-memory-read-error",
                    str(error),
                    severity="error",
                    file=str(path),
                )
            ],
            malformed,
        )
    if file_size > max_bytes:
        return (
            entries,
            [
                ServerMemoryDiagnostic(
                    "server-memory-file-too-large",
                    "server-memory JSONL file exceeds byte limit",
                    severity="error",
                    file=str(path),
                )
            ],
            malformed,
        )

    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if line_number > max_lines:
                    diagnostics.append(
                        ServerMemoryDiagnostic(
                            "server-memory-line-limit",
                            "server-memory JSONL line limit reached",
                            file=str(path),
                            line=line_number,
                        )
                    )
                    break
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    malformed += 1
                    diagnostics.append(
                        ServerMemoryDiagnostic(
                            "malformed-jsonl",
                            "server-memory JSONL line could not be parsed",
                            file=str(path),
                            line=line_number,
                        )
                    )
                    continue
                if not isinstance(payload, dict):
                    malformed += 1
                    diagnostics.append(
                        ServerMemoryDiagnostic(
                            "unsupported-jsonl-value",
                            "server-memory JSONL line is not an object",
                            file=str(path),
                            line=line_number,
                        )
                    )
                    continue
                for item in expand_server_memory_payload(payload):
                    if len(entries) + start_index >= max_entries:
                        diagnostics.append(
                            ServerMemoryDiagnostic(
                                "server-memory-entry-limit",
                                "server-memory entry limit reached",
                                file=str(path),
                                line=line_number,
                            )
                        )
                        break
                    entries.append(
                        build_server_memory_entry(
                            item,
                            index=start_index + len(entries),
                            file_path=path,
                            line=line_number,
                        )
                    )
    except OSError as error:
        diagnostics.append(
            ServerMemoryDiagnostic(
                "server-memory-read-error",
                str(error),
                severity="error",
                file=str(path),
            )
        )
    return entries, diagnostics, malformed


def expand_server_memory_payload(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    emitted = False
    entities = payload.get("entities")
    if isinstance(entities, list):
        for entity in entities:
            if isinstance(entity, dict):
                emitted = True
                yield {"type": "entity", **entity}
    relations = payload.get("relations")
    if isinstance(relations, list):
        for relation in relations:
            if isinstance(relation, dict):
                emitted = True
                yield {"type": "relation", **relation}
    if not emitted:
        yield payload


def build_server_memory_entry(
    payload: Mapping[str, Any],
    *,
    index: int,
    file_path: Path,
    line: int,
) -> ServerMemoryEntry:
    kind = classify_entry(payload)
    text_parts, redacted = safe_text_parts(payload)
    text = " ".join(part for part in text_parts if part)
    snippet = truncate(redact_server_memory_text(text), MAX_SNIPPET_LENGTH)
    name = safe_string(payload.get("name") or payload.get("id") or "")
    entry_type = safe_string(payload.get("entityType") or payload.get("type") or "")
    relation_source = optional_safe_string(payload.get("source"))
    relation_target = optional_safe_string(payload.get("target"))
    relation_type = optional_safe_string(payload.get("relationType"))
    label = build_label(kind, name, relation_source, relation_target, relation_type)
    local_paths = tuple(sorted(set(extract_path_candidates(text))))
    urls = tuple(sorted(set(extract_url_candidates(text))))
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return ServerMemoryEntry(
        index=index,
        file=file_path.name,
        line=line,
        kind=kind,
        entry_id=f"{file_path.name}:{line}:{index}",
        name=name,
        entry_type=entry_type,
        label=label,
        snippet=snippet,
        text_length=len(text),
        text_hash=text_hash,
        relation_source=relation_source,
        relation_target=relation_target,
        relation_type=relation_type,
        local_paths=local_paths,
        urls=urls,
        redacted=redacted or REDACTED in snippet,
    )


def classify_entry(payload: Mapping[str, Any]) -> str:
    entry_type = str(payload.get("type") or "").lower()
    if "relationType" in payload or {"source", "target"}.issubset(payload.keys()):
        return "relation"
    if "entityType" in payload or entry_type == "entity":
        return "entity"
    return "unknown"


def safe_text_parts(value: Any, *, key: str = "") -> tuple[list[str], bool]:
    if is_secret_key(key):
        return [REDACTED], True
    if isinstance(value, Mapping):
        parts: list[str] = []
        redacted = False
        for item_key, item_value in value.items():
            item_parts, item_redacted = safe_text_parts(item_value, key=str(item_key))
            parts.extend(item_parts)
            redacted = redacted or item_redacted
        return parts, redacted
    if isinstance(value, list):
        parts = []
        redacted = False
        for item in value:
            item_parts, item_redacted = safe_text_parts(item, key=key)
            parts.extend(item_parts)
            redacted = redacted or item_redacted
        return parts, redacted
    if isinstance(value, str):
        if is_credentialed_url(value):
            return [REDACTED], True
        text = redact_server_memory_text(value)
        return [truncate(text, MAX_METADATA_STRING_LENGTH)], text != value
    if value is None:
        return [], False
    return [truncate(str(value), MAX_METADATA_STRING_LENGTH)], False


def safe_string(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return truncate(redact_server_memory_text(value), MAX_METADATA_STRING_LENGTH)


def optional_safe_string(value: Any) -> str | None:
    text = safe_string(value)
    return text or None


def build_label(
    kind: str,
    name: str,
    source: str | None,
    target: str | None,
    relation_type: str | None,
) -> str:
    if kind == "relation":
        return truncate(
            " ".join(part for part in (source, relation_type, target) if part),
            MAX_METADATA_STRING_LENGTH,
        )
    return name or kind


def extract_url_candidates(text: str) -> list[str]:
    urls: list[str] = []
    for match in URL_PATTERN.findall(text):
        candidate = match.rstrip(").,;]")
        urls.append(REDACTED if is_credentialed_url(candidate) else truncate(candidate, 120))
    return urls[:20]


def redact_server_memory_text(value: str | None) -> str:
    if not value:
        return ""
    credentialed_url = re.compile(r"https?://[^\s/@:]+:[^\s/@]+@[^\s]+")
    assignment = re.compile(
        r"(?i)(password|passwd|secret|token|api[_-]?key|authorization|credential)"
        r"\s*[:=]\s*[^\s,;]+"
    )
    result = credentialed_url.sub(REDACTED, value)
    return assignment.sub(lambda match: match.group(1) + "=" + REDACTED, result)


def extract_path_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for match in PATH_PATTERN.findall(text):
        candidate = match.rstrip(").,;]")
        if "://" in candidate:
            continue
        candidates.append(truncate(candidate, 160))
    return candidates[:20]


def entry_search_text(entry: ServerMemoryEntry) -> str:
    return " ".join(
        [
            entry.kind,
            entry.name,
            entry.entry_type,
            entry.label,
            entry.snippet,
            " ".join(entry.local_paths),
            " ".join(entry.urls),
        ]
    )


def validate_server_memory_query(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("query is required")
    text = value.strip()
    if len(text) > MAX_METADATA_STRING_LENGTH:
        raise ValueError(f"query must be at most {MAX_METADATA_STRING_LENGTH} characters")
    return text


def validate_server_memory_limit(value: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("limit must be a positive integer") from error
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    return min(limit, MAX_SERVER_MEMORY_LIMIT)


def validate_server_memory_offset(value: int) -> int:
    try:
        offset = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("offset must be a non-negative integer") from error
    if offset < 0:
        raise ValueError("offset must be a non-negative integer")
    return offset


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 15] + "...[truncated]"
