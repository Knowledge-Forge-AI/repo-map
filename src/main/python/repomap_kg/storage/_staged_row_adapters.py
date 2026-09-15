"""Internal row adapter and observation replay helpers for staged rows."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sized
from typing import Any

from repomap_kg.graph.keys import GRAPH_KEY_VERSION
from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.file_rows import FileRow
from repomap_kg.storage.staging_family_contracts import StageFamilyDescriptor
from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurements,
)

__all__ = (
    "_canonical_edge_evidence_row",
    "_canonical_edge_row",
    "_canonical_evidence_row",
    "_canonical_node_evidence_row",
    "_canonical_node_row",
    "_file_row",
    "_indexed",
    "_measured_observation_replay",
    "_raw_row",
    "_stage_row",
)


def _indexed(
    descriptor: StageFamilyDescriptor,
    stage_id: str,
    rows: Iterable[Any],
    adapter: Any,
) -> Iterator[dict[str, object]]:
    for ordinal, row in enumerate(rows):
        yield _stage_row(descriptor, stage_id, ordinal, adapter(row))


def _measured_observation_replay(
    observations: Iterable[RawObservation],
    measurements: StagingMeasurements | None,
    duration_category: StagingMeasurementCategory,
    rows_category: StagingMeasurementCategory,
    *,
    expected_replays: int,
) -> Iterable[RawObservation]:
    if measurements is None:
        return observations
    return _MeasuredObservationReplay(
        observations,
        measurements,
        duration_category,
        rows_category,
        expected_replays,
    )


class _MeasuredObservationReplay:
    def __init__(
        self,
        observations: Iterable[RawObservation],
        measurements: StagingMeasurements,
        duration_category: StagingMeasurementCategory,
        rows_category: StagingMeasurementCategory,
        expected_replays: int,
    ) -> None:
        self._observations = observations
        self._measurements = measurements
        self._duration_category = duration_category
        self._rows_category = rows_category
        self._expected_replays = expected_replays
        self._elapsed_ns = 0
        self._completed_replays = 0

    def __len__(self) -> int:
        if isinstance(self._observations, Sized):
            return len(self._observations)
        raise TypeError(
            f"object of type '{type(self._observations).__name__}' has no len()"
        )

    def __iter__(self) -> Iterator[RawObservation]:
        iterator = iter(self._observations)
        count = 0
        while True:
            try:
                observation, elapsed = self._measurements.measure_elapsed(
                    lambda: next(iterator)
                )
            except StopIteration:
                self._completed_replays += 1
                if self._completed_replays == self._expected_replays:
                    self._measurements.record_duration(
                        self._duration_category, self._elapsed_ns
                    )
                    self._measurements.record_rows(self._rows_category, count)
                return
            self._elapsed_ns += elapsed
            count += 1
            yield observation


def _stage_row(
    descriptor: StageFamilyDescriptor,
    stage_id: str,
    proposal_ordinal: int,
    payload: Mapping[str, object],
) -> dict[str, object]:
    values = dict(payload)
    if descriptor.technical_ordinal not in values:
        values = {descriptor.technical_ordinal: proposal_ordinal, **values}
    row = {"stage_id": stage_id, **values}
    if set(row) != set(descriptor.copy_columns):
        raise StorageSchemaError("staged family row shape is invalid")
    return {column: row[column] for column in descriptor.copy_columns}


def _file_row(row: FileRow) -> dict[str, object]:
    return {
        "path": row.path,
        "language": row.language,
        "role": row.role,
        "confidence": row.confidence,
        "content_hash": row.content_hash,
        "executable": row.executable,
        "generated": row.generated,
        "metadata_json": row.metadata_json,
    }


def _raw_row(row: Any) -> dict[str, object]:
    return {
        "source_ordinal": row.ordinal,
        "schema_version": row.schema_version,
        "kind": row.kind,
        "source_id": row.source_id,
        "path": row.path,
        "payload_json": row.payload_json,
        "payload_hash": row.payload_hash,
    }


def _canonical_node_row(row: Any) -> dict[str, object]:
    return {
        "graph_key_version": row.graph_key_version,
        "canonical_key": row.canonical_key,
        "kind": row.kind,
        "display_name": row.display_name,
        "metadata_json": row.metadata_json,
        "confidence": row.confidence,
        "conflict": row.conflict,
    }


def _canonical_edge_row(row: Any) -> dict[str, object]:
    return {
        "graph_key_version": row.graph_key_version,
        "source_canonical_key": row.source_key,
        "edge_kind": row.edge_kind,
        "target_canonical_key": row.target_key,
        "identity_metadata_json": row.identity_metadata_json,
        "identity_metadata_hash": row.identity_metadata_hash,
        "metadata_json": row.metadata_json,
        "confidence": row.confidence,
        "conflict": row.conflict,
    }


def _canonical_evidence_row(row: Any) -> dict[str, object]:
    return {
        "graph_key_version": row.graph_key_version,
        "evidence_key": row.evidence_key,
        "raw_observation_ordinal": row.raw_observation_ordinal,
        "raw_schema_version": row.raw_schema_version,
        "raw_kind": row.raw_kind,
        "raw_source_id": row.raw_source_id,
        "path": row.path,
        "start_line": row.start_line,
        "end_line": row.end_line,
        "extractor": row.extractor,
        "extractor_version": row.extractor_version,
        "confidence": row.confidence,
        "metadata_json": row.metadata_json,
    }


def _canonical_node_evidence_row(row: Any) -> dict[str, object]:
    return {
        "graph_key_version": GRAPH_KEY_VERSION,
        "canonical_key": row.canonical_key,
        "evidence_key": row.evidence_key,
        "link_kind": row.link_kind,
    }


def _canonical_edge_evidence_row(row: Any) -> dict[str, object]:
    return {
        "graph_key_version": row.graph_key_version,
        "source_canonical_key": row.source_key,
        "edge_kind": row.edge_kind,
        "target_canonical_key": row.target_key,
        "identity_metadata_hash": row.identity_metadata_hash,
        "evidence_key": row.evidence_key,
        "link_kind": row.link_kind,
    }
