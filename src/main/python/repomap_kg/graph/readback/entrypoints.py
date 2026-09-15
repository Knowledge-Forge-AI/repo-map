"""Entrypoint-query helpers built on file records."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from repomap_kg.graph.readback.files import (
    FileFilters,
    FileRecord,
    file_records_from_observations,
    filter_file_records,
    format_file_table,
    records_to_jsonable,
)
from repomap_kg.observations.raw import RawObservation

Obs = Iterable[RawObservation]
Records = tuple[FileRecord, ...]


def entrypoint_records_from_file_records(records: Iterable[FileRecord]) -> Records:
    return filter_file_records(records, FileFilters(role="entrypoint"))


def entrypoint_records_from_observations(observations: Obs) -> Records:
    return entrypoint_records_from_file_records(file_records_from_observations(observations))


def format_entrypoint_table(records: Iterable[FileRecord]) -> str:
    return format_file_table(records)


def entrypoints_to_jsonable(records: Iterable[FileRecord]) -> list[dict[str, Any]]:
    return records_to_jsonable(records)
