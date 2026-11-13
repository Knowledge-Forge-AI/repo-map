"""Deterministic row adaptation for the SCALE staging COPY boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from common_lore_index.canonicalization.main import canonicalize_observations
from common_lore_index.observations.raw import RawObservation
from common_lore_index.storage._staged_row_adapters import (
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
from common_lore_index.storage.canonical_rows import (
    _iter_canonical_edge_evidence_rows,
    _iter_canonical_edge_rows,
    _iter_canonical_evidence_rows,
    _iter_canonical_node_evidence_rows,
    _iter_canonical_node_rows,
    _iter_raw_observation_rows,
)
from common_lore_index.storage.errors import StorageSchemaError
from common_lore_index.storage.file_rows import (
    FileRow,
    file_rows_from_observations,
)
from common_lore_index.storage.row_spool import RowSpool
from common_lore_index.storage._preparation_iterators import check_preparation, close_preparation_iterators
from common_lore_index.storage._staged_spool_preparation import (
    _PreparedFamilyRows, _SpoolPreparation, prepare_family_rows,
)
from common_lore_index.storage._spool_cleanup import close_spooled_rows
from common_lore_index.storage.staged_row_measurements import (
    measure_family_checksum,
    measure_family_preparation,
    record_family_checksum_duration,
    record_prepared_family,
)
from common_lore_index.storage.staging_checksums import (
    FamilyChecksum,
    _FamilyChecksumAccumulator,
    checksum_family,
)
from common_lore_index.storage.staging_family_catalog import family_privacy_classifications
from common_lore_index.storage.staging_family_contracts import (
    PrivacyClassification,
    STAGING_FAMILY_DESCRIPTORS,
    StageFamily,
    StageFamilyDescriptor,
)
from common_lore_index.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurements,
)

if TYPE_CHECKING:
    from common_lore_index.canonicalization.rust_pilot_family import WitnessedCanonicalization

__all__ = ("PreparedStageRows", "build_staged_rows")

_stage_row = _stage_row


_ROW_SPOOL_THRESHOLD = 4096




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

        _close_family_rows(self.family_rows)

    def __enter__(self) -> PreparedStageRows:
        return self

    def __exit__(self, _exc_type: object, exc: object, _traceback: object) -> None:
        _close_family_rows(self.family_rows, preserve_primary=exc is not None)


def build_staged_rows(
    observations: Iterable[RawObservation],
    *,
    repository_name: str,
    stage_id: str,
    staging_measurements: StagingMeasurements | None = None,
    spool_artifact_observer: Callable[[str, int], None] | None = None,
    witnessed: WitnessedCanonicalization | None = None,
    spool_dir: Path | str | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> PreparedStageRows:
    """Adapt one canonicalized observation sequence to every stage family."""

    if witnessed is not None:
        from common_lore_index.canonicalization.rust_pilot_family import WitnessedCanonicalization
        if type(witnessed) is not WitnessedCanonicalization:
            raise StorageSchemaError("invalid Rust pilot witness")
        if not witnessed.verify_live():
            raise StorageSchemaError("Rust pilot witness is not live")
        if type(observations) is not tuple or observations is not witnessed.observations:
            raise StorageSchemaError("Rust pilot observation identity mismatch")
    file_rows = file_rows_from_observations(
        _measured_observation_replay(
            observations,
            staging_measurements,
            StagingMeasurementCategory.OBSERVATION_FILE_REPLAY,
            StagingMeasurementCategory.OBSERVATION_FILE_REPLAY_ROWS,
            expected_replays=1,
        )
    )
    check_preparation(cancel_check)
    if witnessed is not None:
        result = witnessed.result
    elif staging_measurements is None:
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
        from common_lore_index.storage.main import canonicalization_error_message

        raise StorageSchemaError(
            f"canonicalization failed: {canonicalization_error_message(result)}"
        )
    check_preparation(cancel_check)
    rows: Mapping[str, Iterable[dict[str, object]]] = {}
    try:
        prepared_families = _family_rows(
            stage_id,
            observations,
            file_rows,
            result,
            staging_measurements,
            spool_artifact_observer,
            spool_dir,
            cancel_check,
        )
        rows = {
            family: prepared.rows
            for family, prepared in prepared_families.items()
        }
        if witnessed is not None and not witnessed.verify_live():
            raise StorageSchemaError("Rust pilot witness changed before staging rows were returned")
        del result
        checksums: dict[str, FamilyChecksum] = {}
        for family_str, prepared in prepared_families.items():
            check_preparation(cancel_check)
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
        _close_family_rows(rows, preserve_primary=True)
        raise


def _family_rows(
    stage_id: str,
    observations: Iterable[RawObservation],
    file_rows: Sequence[FileRow],
    result: Any,
    staging_measurements: StagingMeasurements | None,
    spool_artifact_observer: Callable[[str, int], None] | None,
    spool_dir: Path | str | None,
    cancel_check: Callable[[], None] | None = None,
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
    failed = False
    try:
        def prepare(family: StageFamily, descriptor: StageFamilyDescriptor) -> _PreparedFamilyRows:
            prepared = _materialize_or_spool(
                _indexed(descriptor, stage_id, *sources[family]), descriptor=descriptor,
                staging_measurements=staging_measurements,
                spool_artifact_observer=spool_artifact_observer, spool_dir=spool_dir,
                cancel_check=cancel_check,
            )
            families[family] = prepared
            return prepared

        for family, descriptor in STAGING_FAMILY_DESCRIPTORS.items():
            check_preparation(cancel_check)
            measure_family_preparation(
                staging_measurements,
                family,
                lambda: prepare(family, descriptor),
            )
        return families
    except BaseException:
        failed = True
        _close_prepared_families(families)
        raise
    finally:
        if cancel_check is not None:
            try:
                close_preparation_iterators(
                    (source for source, _ in sources.values()), preserve_primary=failed,
                )
            except BaseException:
                _close_prepared_families(families)
                raise


def _materialize_or_spool(
    rows: Iterable[dict[str, object]],
    *,
    descriptor: StageFamilyDescriptor,
    staging_measurements: StagingMeasurements | None,
    spool_artifact_observer: Callable[[str, int], None] | None,
    spool_dir: Path | str | None = None,
    cancel_check: Callable[[], None] | None = None,
) -> _PreparedFamilyRows:
    options = _SpoolPreparation(
        descriptor, staging_measurements, spool_artifact_observer, spool_dir,
        _ROW_SPOOL_THRESHOLD, RowSpool, _FamilyChecksumAccumulator,
    )
    return prepare_family_rows(rows, options, cancel_check)


def _close_family_rows(
    rows: Mapping[str, Iterable[dict[str, object]]], *, preserve_primary: bool = False,
) -> None:
    close_spooled_rows(rows.values(), preserve_primary=preserve_primary)


def _close_prepared_families(
    families: Mapping[str, _PreparedFamilyRows],
) -> None:
    _close_family_rows(
        {family: prepared.rows for family, prepared in families.items()},
        preserve_primary=True,
    )
