"""Shared dataclasses and records for server-memory parsing and bridging."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from repomap_kg.ops.config import redact_text


@dataclass(frozen=True)
class ServerMemoryDiagnostic:
    code: str
    message: str
    severity: str = "warning"
    file: str | None = None
    line: int | None = None

    def to_jsonable(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": redact_text(self.message),
        }
        if self.file is not None:
            payload["file"] = redact_text(self.file)
        if self.line is not None:
            payload["line"] = self.line
        return payload


@dataclass(frozen=True)
class ServerMemoryEntry:
    index: int
    file: str
    line: int
    kind: str
    entry_id: str
    name: str
    entry_type: str
    label: str
    snippet: str
    text_length: int
    text_hash: str
    relation_source: str | None
    relation_target: str | None
    relation_type: str | None
    local_paths: tuple[str, ...]
    urls: tuple[str, ...]
    redacted: bool

    def to_jsonable(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "index": self.index,
            "line": self.line,
            "kind": self.kind,
            "entry_id": self.entry_id,
            "name": self.name,
            "type": self.entry_type,
            "label": self.label,
            "snippet": self.snippet,
            "text_length": self.text_length,
            "text_hash": self.text_hash,
            "local_paths": list(self.local_paths),
            "urls": list(self.urls),
            "redacted": self.redacted,
        }
        if self.relation_source is not None:
            payload["relation_source"] = self.relation_source
        if self.relation_target is not None:
            payload["relation_target"] = self.relation_target
        if self.relation_type is not None:
            payload["relation_type"] = self.relation_type
        return payload
