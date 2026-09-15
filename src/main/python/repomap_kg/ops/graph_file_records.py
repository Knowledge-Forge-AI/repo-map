"""Public-safe records for canonical graph-file readback."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping, Sequence

from repomap_kg.graph.keys import GRAPH_KEY_VERSION, GraphKeyError, parse_key


GRAPH_FILE_CANDIDATE_LIMIT = 20


@dataclass(frozen=True)
class GraphFileRecord:
    canonical_key: str
    graph_key_version: int
    path: str
    observation_state: str
    languages: tuple[str, ...]
    roles: tuple[str, ...]
    generated_states: tuple[bool, ...]
    executable_states: tuple[bool, ...]
    confidence: str
    conflict: bool
    ambiguous_fields: tuple[str, ...]
    language_overflow: int
    role_overflow: int
    evidence_count: int
    file_observation_count: int
    link_kinds: tuple[str, ...]
    link_kind_overflow: int
    binding_id: str | None = None
    binding_alias: str | None = None
    binding_role: str | None = None
    snapshot_id: str | None = None
    candidate_id: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "canonical_key": self.canonical_key,
            "graph_key_version": self.graph_key_version,
            "path": self.path,
            "source_binding": {
                "binding_id": self.binding_id,
                "alias": self.binding_alias,
                "role": self.binding_role,
                "snapshot_id": self.snapshot_id,
            } if self.binding_id is not None else None,
            "candidate_id": self.candidate_id,
            "observation_state": self.observation_state,
            "languages": list(self.languages),
            "roles": list(self.roles),
            "generated_states": list(self.generated_states),
            "executable_states": list(self.executable_states),
            "confidence": self.confidence,
            "conflict": self.conflict,
            "ambiguous_fields": list(self.ambiguous_fields),
            "candidate_overflow": {
                "languages": self.language_overflow,
                "roles": self.role_overflow,
            },
            "evidence": {
                "count": self.evidence_count,
                "file_observation_count": self.file_observation_count,
                "link_kinds": list(self.link_kinds),
                "link_kind_overflow": self.link_kind_overflow,
            },
        }


@dataclass(frozen=True)
class GraphFilePage:
    graph_id: str
    repository_name: str
    records: tuple[GraphFileRecord, ...]
    limit: int
    offset: int
    has_more: bool


def graph_file_record_from_payload(payload: Mapping[str, Any]) -> GraphFileRecord:
    canonical_key = str(payload["canonical_key"])
    try:
        parsed_key = parse_key(canonical_key)
    except GraphKeyError as error:
        raise ValueError("canonical graph file key is invalid") from error
    if parsed_key.namespace != "file" or parsed_key.path is None:
        raise ValueError("canonical graph file key must use the file namespace")
    graph_key_version = int(payload["graph_key_version"])
    if graph_key_version != GRAPH_KEY_VERSION:
        raise ValueError("unsupported graph key version")
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("canonical graph file metadata must be an object")
    languages, language_overflow = _bounded_text_candidates(metadata.get("language"))
    roles, role_overflow = _bounded_text_candidates(metadata.get("role"))
    generated_states = _boolean_candidates(metadata.get("generated"))
    executable_states = _boolean_candidates(metadata.get("executable"))
    link_kinds, link_kind_overflow = _bounded_text_candidates(payload.get("link_kinds"))
    evidence_count = _non_negative_int(payload.get("evidence_count"), "evidence count")
    file_observation_count = _non_negative_int(
        payload.get("file_observation_count"),
        "file observation count",
    )
    if file_observation_count > evidence_count:
        raise ValueError("file observation count exceeds evidence count")
    ambiguous_fields = tuple(
        name
        for name, values in (
            ("languages", languages),
            ("roles", roles),
            ("generated_states", generated_states),
            ("executable_states", executable_states),
        )
        if len(values) > 1
    )
    binding_id = _optional_single_text(metadata, "binding_id")
    binding_alias = _optional_single_text(metadata, "binding_alias")
    binding_role = _optional_single_text(metadata, "binding_role")
    snapshot_id = _optional_single_text(metadata, "snapshot_id")
    candidate_id = _optional_single_text(metadata, "candidate_id")
    source_relative_path = _optional_single_text(metadata, "source_relative_path")
    return GraphFileRecord(
        canonical_key=canonical_key,
        graph_key_version=graph_key_version,
        path=source_relative_path or parsed_key.path,
        observation_state="observed" if file_observation_count else "referenced",
        languages=languages,
        roles=roles,
        generated_states=generated_states,
        executable_states=executable_states,
        confidence=str(payload["confidence"]),
        conflict=bool(payload["conflict"]),
        ambiguous_fields=ambiguous_fields,
        language_overflow=language_overflow,
        role_overflow=role_overflow,
        evidence_count=evidence_count,
        file_observation_count=file_observation_count,
        link_kinds=link_kinds,
        link_kind_overflow=link_kind_overflow,
        binding_id=binding_id,
        binding_alias=binding_alias,
        binding_role=binding_role,
        snapshot_id=snapshot_id,
        candidate_id=candidate_id,
    )


def _optional_single_text(metadata: Mapping[str, Any], field: str) -> str | None:
    values, overflow = _bounded_text_candidates(metadata.get(field))
    if overflow or len(values) > 1:
        raise ValueError(f"canonical graph file {field} is ambiguous")
    return values[0] if values else None


def graph_file_page_to_jsonable(page: GraphFilePage) -> dict[str, Any]:
    return {
        "command": "graph-files",
        "schema_version": 1,
        "result": "success",
        "graph": {
            "id": page.graph_id,
            "repository_name": page.repository_name,
            "graph_key_version": GRAPH_KEY_VERSION,
        },
        "pagination": {
            "limit": page.limit,
            "offset": page.offset,
            "returned": len(page.records),
            "has_more": page.has_more,
        },
        "files": [record.to_jsonable() for record in page.records],
        "readback": {
            "mode": "canonical",
            "bounded": True,
            "raw_payloads_included": False,
        },
    }


def format_graph_file_table(page: GraphFilePage) -> str:
    columns = (
        "canonical_key",
        "path",
        "state",
        "languages",
        "roles",
        "generated",
        "executable",
        "confidence",
        "ambiguity",
        "evidence",
    )
    rows = [
        {
            "canonical_key": record.canonical_key,
            "path": record.path,
            "state": record.observation_state,
            "languages": _compact_json(record.languages),
            "roles": _compact_json(record.roles),
            "generated": _compact_json(record.generated_states),
            "executable": _compact_json(record.executable_states),
            "confidence": record.confidence,
            "ambiguity": _compact_json(record.ambiguous_fields),
            "evidence": str(record.evidence_count),
        }
        for record in page.records
    ]
    widths = {
        column: max([len(column), *(len(row[column]) for row in rows)])
        for column in columns
    }
    lines = [
        "RepoMap canonical graph files",
        f"graph={page.graph_id} repository={page.repository_name}",
        (
            f"limit={page.limit} offset={page.offset} "
            f"returned={len(page.records)} has_more={str(page.has_more).lower()}"
        ),
        _format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
    ]
    lines.extend(_format_table_row(row, columns, widths) for row in rows)
    return "\n".join(lines)


def _bounded_text_candidates(value: Any) -> tuple[tuple[str, ...], int]:
    values = _candidate_values(value)
    if any(not isinstance(candidate, str) for candidate in values):
        raise ValueError("canonical graph file text candidates must be strings")
    ordered = tuple(sorted(set(values)))
    return (
        ordered[:GRAPH_FILE_CANDIDATE_LIMIT],
        max(0, len(ordered) - GRAPH_FILE_CANDIDATE_LIMIT),
    )


def _boolean_candidates(value: Any) -> tuple[bool, ...]:
    values = _candidate_values(value)
    if any(not isinstance(candidate, bool) for candidate in values):
        raise ValueError("canonical graph file boolean candidates must be booleans")
    return tuple(sorted(set(values)))


def _candidate_values(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _non_negative_int(value: Any, label: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{label} must be non-negative")
    return parsed


def _compact_json(values: Sequence[Any]) -> str:
    return json.dumps(list(values), separators=(",", ":"), sort_keys=True)


def _format_table_row(
    row: Mapping[str, str],
    columns: Sequence[str],
    widths: Mapping[str, int],
) -> str:
    return "  ".join(row[column].ljust(widths[column]) for column in columns).rstrip()


__all__ = (
    "GRAPH_FILE_CANDIDATE_LIMIT",
    "GraphFilePage",
    "GraphFileRecord",
    "format_graph_file_table",
    "graph_file_page_to_jsonable",
    "graph_file_record_from_payload",
)
