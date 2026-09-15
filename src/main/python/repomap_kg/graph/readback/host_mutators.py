"""Host-mutator query helpers built on raw observations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from repomap_kg.graph.readback.files import format_table_row, render_table_value
from repomap_kg.observations.raw import RawObservation


@dataclass(frozen=True)
class HostMutatorRecord:
    path: str
    line: int
    name: str
    target: str
    category: str
    tool: str
    privileged: bool
    confidence: str
    reason: str
    argv: tuple[str, ...]
    effective_argv: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["argv"] = list(self.argv)
        payload["effective_argv"] = list(self.effective_argv)
        return payload


@dataclass(frozen=True)
class HostMutatorSummaryRecord:
    category: str
    tool: str
    count: int
    privileged_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def host_mutator_records_from_observations(
    observations: Iterable[RawObservation],
) -> tuple[HostMutatorRecord, ...]:
    records = []
    for observation in observations:
        if observation.kind != "shell.host_mutation":
            continue
        records.append(record_from_observation(observation))
    return tuple(
        sorted(records, key=lambda record: (record.path, record.line, record.name))
    )


def filter_host_mutator_records(
    records: Iterable[HostMutatorRecord],
    *,
    category: str | None = None,
    tool: str | None = None,
) -> tuple[HostMutatorRecord, ...]:
    filtered = []
    for record in records:
        if category is not None and record.category != category:
            continue
        if tool is not None and record.tool != tool:
            continue
        filtered.append(record)
    return tuple(filtered)


def summarize_host_mutator_records(
    records: Iterable[HostMutatorRecord],
) -> tuple[HostMutatorSummaryRecord, ...]:
    counts: dict[tuple[str, str], tuple[int, int]] = {}
    for record in records:
        key = (record.category, record.tool)
        count, privileged_count = counts.get(key, (0, 0))
        counts[key] = (count + 1, privileged_count + int(record.privileged))
    return tuple(
        HostMutatorSummaryRecord(
            category=category,
            tool=tool,
            count=count,
            privileged_count=privileged_count,
        )
        for (category, tool), (count, privileged_count) in sorted(counts.items())
    )


def record_from_observation(observation: RawObservation) -> HostMutatorRecord:
    metadata = observation.metadata
    return HostMutatorRecord(
        path=observation.path,
        line=observation.start_line or 0,
        name=observation.name or "",
        target=observation.target or "",
        category=metadata_text(metadata, "category", "unknown"),
        tool=metadata_text(metadata, "tool", "unknown"),
        privileged=metadata_bool(metadata, "privileged"),
        confidence=observation.confidence,
        reason=metadata_text(metadata, "reason", ""),
        argv=metadata_string_tuple(metadata, "argv"),
        effective_argv=metadata_string_tuple(metadata, "effective_argv"),
    )


def host_mutators_to_jsonable(
    records: Iterable[HostMutatorRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def host_mutator_summaries_to_jsonable(
    records: Iterable[HostMutatorSummaryRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def format_host_mutator_table(records: Iterable[HostMutatorRecord]) -> str:
    rows = [record.to_dict() for record in records]
    columns = ("path", "line", "category", "tool", "privileged", "name")
    rendered_rows = [
        {key: render_table_value(row[key]) for key in columns}
        for row in rows
    ]
    widths = {
        key: max([len(key), *(len(row[key]) for row in rendered_rows)])
        for key in columns
    }
    lines = [
        format_table_row(dict(zip(columns, columns, strict=True)), columns, widths)
    ]
    for row in rendered_rows:
        lines.append(format_table_row(row, columns, widths))
    return "\n".join(lines)


def format_host_mutator_summary_table(
    records: Iterable[HostMutatorSummaryRecord],
) -> str:
    rows = [record.to_dict() for record in records]
    columns = ("category", "tool", "count", "privileged_count")
    rendered_rows = [
        {key: render_table_value(row[key]) for key in columns}
        for row in rows
    ]
    widths = {
        key: max([len(key), *(len(row[key]) for row in rendered_rows)])
        for key in columns
    }
    lines = [
        format_table_row(dict(zip(columns, columns, strict=True)), columns, widths)
    ]
    for row in rendered_rows:
        lines.append(format_table_row(row, columns, widths))
    return "\n".join(lines)


def metadata_text(metadata: Mapping[str, Any], key: str, default: str) -> str:
    value = metadata.get(key, default)
    if not isinstance(value, str) or not value:
        return default
    return value


def metadata_bool(metadata: Mapping[str, Any], key: str) -> bool:
    return bool(metadata.get(key, False))


def metadata_string_tuple(metadata: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = metadata.get(key, ())
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))
