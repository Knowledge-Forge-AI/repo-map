"""File-query helpers built on normalized raw observations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from repomap_kg.observations.normalization import normalize_observations
from repomap_kg.observations.raw import RawObservation


@dataclass(frozen=True)
class FileRecord:
    path: str
    language: str
    role: str
    confidence: str
    generated: bool
    executable: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FileFilters:
    role: str | None = None
    language: str | None = None
    generated: str = "include"


def file_records_from_observations(
    observations: Iterable[RawObservation],
) -> tuple[FileRecord, ...]:
    raw_observations = list(observations)
    graph = normalize_observations(raw_observations)
    observations_by_node_key = {
        node_key_for_observation(observation): observation
        for observation in raw_observations
    }
    records = []

    for node in graph.nodes:
        if node.kind != "file":
            continue
        observation = observations_by_node_key[node.stable_key]
        records.append(
            FileRecord(
                path=node.path,
                language=metadata_text(node.metadata, "language", "unknown"),
                role=metadata_text(node.metadata, "role", "unknown"),
                confidence=observation.confidence,
                generated=metadata_bool(node.metadata, "generated"),
                executable=metadata_bool(node.metadata, "executable"),
            )
        )

    return tuple(sorted(records, key=lambda record: record.path))


def filter_file_records(
    records: Iterable[FileRecord], filters: FileFilters
) -> tuple[FileRecord, ...]:
    return tuple(record for record in records if matches_filters(record, filters))


def matches_filters(record: FileRecord, filters: FileFilters) -> bool:
    if filters.role is not None and record.role != filters.role:
        return False
    if filters.language is not None and record.language != filters.language:
        return False
    if filters.generated == "exclude" and record.generated:
        return False
    if filters.generated == "only" and not record.generated:
        return False
    return True


def records_to_jsonable(records: Iterable[FileRecord]) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def format_file_table(records: Iterable[FileRecord]) -> str:
    rows = [record.to_dict() for record in records]
    columns = ("path", "language", "role", "confidence", "generated", "executable")
    rendered_rows = [
        {
            key: render_table_value(row[key])
            for key in columns
        }
        for row in rows
    ]
    widths = {
        key: max([len(key), *(len(row[key]) for row in rendered_rows)])
        for key in columns
    }
    lines = [format_table_row(dict(zip(columns, columns, strict=True)), columns, widths)]
    for row in rendered_rows:
        lines.append(format_table_row(row, columns, widths))
    return "\n".join(lines)


def format_table_row(
    row: dict[str, str], columns: tuple[str, ...], widths: dict[str, int]
) -> str:
    return "  ".join(row[key].ljust(widths[key]) for key in columns).rstrip()


def render_table_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def metadata_text(metadata: dict[str, Any], key: str, default: str) -> str:
    value = metadata.get(key, default)
    if not isinstance(value, str) or not value:
        return default
    return value


def metadata_bool(metadata: dict[str, Any], key: str) -> bool:
    return bool(metadata.get(key, False))


def node_key_for_observation(observation: RawObservation) -> str:
    return f"node:{observation.path}:{observation.kind}:{observation.source_id}"
