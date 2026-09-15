"""Deterministic row adaptation for the SCALE staging COPY boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from itertools import chain
from typing import Any, cast

from repomap_kg.canonicalization.main import canonicalize_observations
from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage._staged_row_adapters import (
    _canonical_edge_evidence_row,
    _canonical_edge_row,
    _canonical_evidence_row,
    _canonical_node_evidence_row,
    _canonical_node_row,
    _file_row,
    _indexed,
    _measured_observation_replay,
    _raw_row,
    _stage_row,
)
from repomap_kg.storage.canonical_rows import (
    _iter_canonical_edge_evidence_rows,
    _iter_canonical_edge_rows,
    _iter_canonical_evidence_rows,
    _iter_canonical_node_evidence_rows,
    _iter_canonical_node_rows,
    _iter_raw_observation_rows,
)
from repomap_kg.storage.errors import StorageSchemaError
from repomap_kg.storage.file_rows import (
    FileRow,
    file_rows_from_observations,
)
from repomap_kg.storage.row_spool import RowSpool
from repomap_kg.storage.staged_row_measurements import (
    measure_family_checksum,
    measure_family_preparation,
    record_family_checksum_duration,
    record_prepared_family,
)
from repomap_kg.storage.staging_checksums import (
    FamilyChecksum,
    _FamilyChecksumAccumulator,
    checksum_family,
)
from repomap_kg.storage.staging_family_catalog import family_privacy_classifications
from repomap_kg.storage.staging_family_contracts import (
    PrivacyClassification,
    STAGING_FAMILY_DESCRIPTORS,
    StageFamily,
    StageFamilyDescriptor,
)
from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurements,
)

__all__ = ("PreparedStageRows", "build_staged_rows")

_stage_row = _stage_row


_ROW_SPOOL_THRESHOLD = 4096


@dataclass(frozen=True)
class _PreparedFamilyRows:
    rows: Iterable[dict[str, object]]
    checksum: FamilyChecksum | None = None
    checksum_elapsed_ns: int = 0


@dataclass(frozen=True)
class PreparedStageRows:
    """All active COPY families and their public-safe aggregate evidence."""

    family_rows: Mapping[str, Iterable[dict[str, object]]]
    checksums: Mapping[str, FamilyChecksum]
    row_counts: Mapping[str, int]
    normalized_byte_counts: Mapping[str, int]
    privacy_classifications: Mapping[str, PrivacyClassification]
    files: int

    def close(self) -> None:
        """Remove private family spools after the caller finishes with them."""

        for rows in self.family_rows.values():
            if isinstance(rows, RowSpool):
                rows.close()


def build_staged_rows(
    observations: Iterable[RawObservation],
    *,
    repository_name: str,
    stage_id: str,
    staging_measurements: StagingMeasurements | None = None,
    spool_artifact_observer: Callable[[str, int], None] | None = None,
) -> PreparedStageRows:
    """Adapt one canonicalized observation sequence to every stage family."""

    file_rows = file_rows_from_observations(
        _measured_observation_replay(
            observations,
            staging_measurements,
            StagingMeasurementCategory.OBSERVATION_FILE_REPLAY,
            StagingMeasurementCategory.OBSERVATION_FILE_REPLAY_ROWS,
            expected_replays=1,
        )
    )
    if staging_measurements is None:
        result = canonicalize_observations(
            cast(Sequence[RawObservation], observations),
            repository_scope=repository_name,
        )
    else:
        with staging_measurements.phase("refresh.canonicalization"):
            result = canonicalize_observations(
                cast(Sequence[RawObservation], _measured_observation_replay(
                    observations,
                    staging_measurements,
                    StagingMeasurementCategory.OBSERVATION_CANONICALIZATION_REPLAY,
                    StagingMeasurementCategory.OBSERVATION_CANONICALIZATION_REPLAY_ROWS,
                    expected_replays=2,
                )),
                repository_scope=repository_name,
            )
    if not result.ok:
        from repomap_kg.storage.main import canonicalization_error_message

        raise StorageSchemaError(
            f"canonicalization failed: {canonicalization_error_message(result)}"
        )
    rows: Mapping[str, Iterable[dict[str, object]]] = {}
    try:
        prepared_families = _family_rows(
            stage_id,
            observations,
            file_rows,
            result,
            staging_measurements,
            spool_artifact_observer,
        )
        rows = {
            family: prepared.rows
            for family, prepared in prepared_families.items()
        }
        del result
        checksums: dict[str, FamilyChecksum] = {}
        for family_str, prepared in prepared_families.items():
            family = cast(StageFamily, family_str)
            family_rows = prepared.rows
            if prepared.checksum is None:
                checksum = measure_family_checksum(
                    staging_measurements,
                    family,
                    lambda: checksum_family(
                        (
                            {
                                key: value
                                for key, value in row.items()
                                if key != "stage_id"
                            }
                            for row in family_rows
                        ),
                        identity_fields=STAGING_FAMILY_DESCRIPTORS[
                            family
                        ].identity_columns,
                    ),
                )
            else:
                checksum = prepared.checksum
                record_family_checksum_duration(
                    staging_measurements,
                    family,
                    prepared.checksum_elapsed_ns,
                )
            record_prepared_family(staging_measurements, family, family_rows, checksum)
            checksums[family] = checksum
        return PreparedStageRows(
            family_rows=rows,
            checksums=checksums,
            row_counts={
                family: checksum.row_count for family, checksum in checksums.items()
            },
            normalized_byte_counts={
                family: checksum.normalized_byte_count
                for family, checksum in checksums.items()
            },
            privacy_classifications={str(k): v for k, v in family_privacy_classifications().items()},
            files=len(file_rows),
        )
    except BaseException:
        _close_family_rows(rows)
        raise


def _family_rows(
    stage_id: str,
    observations: Iterable[RawObservation],
    file_rows: Sequence[FileRow],
    result: Any,
    staging_measurements: StagingMeasurements | None,
    spool_artifact_observer: Callable[[str, int], None] | None,
) -> Mapping[str, _PreparedFamilyRows]:
    edges_by_key = {edge.edge_key: edge for edge in result.graph.edges}
    sources: Mapping[str, tuple[Iterable[Any], Any]] = {
        "files": (file_rows, _file_row),
        "raw_observations": (
            _iter_raw_observation_rows(
                _measured_observation_replay(
                    observations,
                    staging_measurements,
                    StagingMeasurementCategory.OBSERVATION_RAW_REPLAY,
                    StagingMeasurementCategory.OBSERVATION_RAW_REPLAY_ROWS,
                    expected_replays=1,
                )
            ),
            _raw_row,
        ),
        "canonical_nodes": (_iter_canonical_node_rows(result), _canonical_node_row),
        "canonical_edges": (_iter_canonical_edge_rows(result), _canonical_edge_row),
        "canonical_evidence": (
            _iter_canonical_evidence_rows(result),
            _canonical_evidence_row,
        ),
        "canonical_node_evidence": (
            _iter_canonical_node_evidence_rows(result),
            _canonical_node_evidence_row,
        ),
        "canonical_edge_evidence": (
            _iter_canonical_edge_evidence_rows(result, edges_by_key),
            _canonical_edge_evidence_row,
        ),
    }
    families: dict[str, _PreparedFamilyRows] = {}
    try:
        for family, descriptor in STAGING_FAMILY_DESCRIPTORS.items():
            families[family] = measure_family_preparation(
                staging_measurements,
                family,
                lambda: _materialize_or_spool(
                    _indexed(descriptor, stage_id, *sources[family]),
                    descriptor=descriptor,
                    staging_measurements=staging_measurements,
                    spool_artifact_observer=spool_artifact_observer,
                ),
            )
        return families
    except BaseException:
        _close_prepared_families(families)
        raise


def _materialize_or_spool(
    rows: Iterable[dict[str, object]],
    *,
    descriptor: StageFamilyDescriptor,
    staging_measurements: StagingMeasurements | None,
    spool_artifact_observer: Callable[[str, int], None] | None,
) -> _PreparedFamilyRows:
    iterator = iter(rows)
    buffered: list[dict[str, object]] = []
    for _ in range(_ROW_SPOOL_THRESHOLD + 1):
        try:
            buffered.append(next(iterator))
        except StopIteration:
            return _PreparedFamilyRows(tuple(buffered))
    accumulator = _FamilyChecksumAccumulator(descriptor.identity_columns)
    checksum_elapsed_ns = 0

    def rows_with_checksum() -> Iterator[dict[str, object]]:
        nonlocal checksum_elapsed_ns
        for row in chain(buffered, iterator):
            checksum_row = {
                key: value for key, value in row.items() if key != "stage_id"
            }
            if staging_measurements is None:
                accumulator.add(checksum_row)
            else:
                _, elapsed_ns = staging_measurements.measure_elapsed(
                    lambda: accumulator.add(checksum_row)
                )
                checksum_elapsed_ns += elapsed_ns
            yield row

    checksum_phase = (
        nullcontext()
        if staging_measurements is None
        else staging_measurements.phase(
            f"staging.family_spool.{descriptor.family}"
        )
    )
    with checksum_phase:
        artifact_observer = (
            None
            if spool_artifact_observer is None
            else lambda projected_bytes: spool_artifact_observer(
                descriptor.family,
                projected_bytes,
            )
        )
        spool = RowSpool.from_rows(
            rows_with_checksum(),
            artifact_observer=artifact_observer,
            timing_observer=(
                None
                if staging_measurements is None
                else lambda elapsed_ns: staging_measurements.record_duration(
                    StagingMeasurementCategory.FAMILY_SPOOL_WRITE,
                    elapsed_ns,
                    family=descriptor.family,
                )
            ),
        )
        try:
            if staging_measurements is None:
                checksum = accumulator.finish()
            else:
                checksum, elapsed_ns = staging_measurements.measure_elapsed(
                    accumulator.finish
                )
                checksum_elapsed_ns += elapsed_ns
        except BaseException:
            spool.close()
            raise
    return _PreparedFamilyRows(spool, checksum, checksum_elapsed_ns)


def _close_family_rows(rows: Mapping[str, Iterable[dict[str, object]]]) -> None:
    for family_rows in rows.values():
        if isinstance(family_rows, RowSpool):
            family_rows.close()


def _close_prepared_families(
    families: Mapping[str, _PreparedFamilyRows],
) -> None:
    _close_family_rows(
        {family: prepared.rows for family, prepared in families.items()}
    )
