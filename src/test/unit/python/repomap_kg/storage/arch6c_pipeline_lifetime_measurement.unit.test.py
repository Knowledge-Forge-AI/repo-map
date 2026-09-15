from dataclasses import asdict, dataclass
import hashlib
import itertools
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.observations import RawObservation
from repomap_kg.storage import row_spool as row_spool_module
from repomap_kg.storage import staged_rows as staged_rows_module
from repomap_kg.storage.row_spool import RowSpool
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_kg.storage.staging_observability import (
    StagingMeasurementCategory,
    StagingMeasurementEvent,
    StagingMeasurements,
)


class _CountingObservations(list[RawObservation]):
    def __init__(self, values):
        super().__init__(values)
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()


@dataclass(frozen=True)
class _PipelineMeasurement:
    observations: int
    observation_iterations: int
    live_families: int
    aggregate_rows: int
    normalized_bytes: int
    spool_bytes: int
    spooled_families: int
    spool_replay_passes: int
    spool_replayed_rows: int
    event_count: int
    checksum_events: int
    spooled_checksum_duration_ns: int
    checksum_manifest_digest: str


def _clock():
    values = itertools.count(start=10_000, step=100)
    return lambda: next(values)


def _observations(size):
    return _CountingObservations(
        [
            RawObservation(
                kind="file",
                source_id=f"fixtures/files/file-{index:05d}.txt",
                path=f"fixtures/files/file-{index:05d}.txt",
                confidence="extracted",
                extractor="arch6c-fixture",
                extractor_version="1.0.0",
                metadata={"extension": ".txt", "size_bytes": index + 1},
            )
            for index in range(size)
        ]
    )


def _measure(size, stage_id):
    observations = _observations(size)
    events: list[StagingMeasurementEvent] = []
    replay_passes = 0
    replayed_rows = 0
    original_iter = RowSpool.__iter__

    def counted_iter(spool):
        nonlocal replay_passes, replayed_rows
        replay_passes += 1
        for row in original_iter(spool):
            replayed_rows += 1
            yield row

    with patch.object(RowSpool, "__iter__", counted_iter):
        prepared = build_staged_rows(
            observations,
            repository_name="arch6c-fixture",
            stage_id=stage_id,
            staging_measurements=StagingMeasurements(
                events.append,
                monotonic_ns=_clock(),
            ),
        )
    try:
        checksum_manifest = {
            family: asdict(checksum)
            for family, checksum in prepared.checksums.items()
        }
        checksum_manifest_digest = hashlib.sha256(
            json.dumps(
                checksum_manifest,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        spools = [
            rows
            for rows in prepared.family_rows.values()
            if isinstance(rows, RowSpool)
        ]
        spooled_families = {
            family
            for family, rows in prepared.family_rows.items()
            if isinstance(rows, RowSpool)
        }
        checksum_events = [
            event
            for event in events
            if event.category is StagingMeasurementCategory.CHECKSUM
        ]
        return _PipelineMeasurement(
            observations=size,
            observation_iterations=observations.iterations,
            live_families=len(prepared.family_rows),
            aggregate_rows=sum(prepared.row_counts.values()),
            normalized_bytes=sum(prepared.normalized_byte_counts.values()),
            spool_bytes=sum(spool.byte_count for spool in spools),
            spooled_families=len(spools),
            spool_replay_passes=replay_passes,
            spool_replayed_rows=replayed_rows,
            event_count=len(events),
            checksum_events=len(checksum_events),
            spooled_checksum_duration_ns=sum(
                event.value or 0
                for event in checksum_events
                if event.family in spooled_families
            ),
            checksum_manifest_digest=checksum_manifest_digest,
        )
    finally:
        prepared.close()


def test_arch6d_fuses_spool_checksums_with_exact_small_medium_full_parity():
    measurements = []
    for size in (32, 512, 4_200):
        first = _measure(size, "stage-alpha")
        second = _measure(size, "stage-bravo")
        assert first == second
        measurements.append(first)

    assert [measurement.observation_iterations for measurement in measurements] == [
        4,
        4,
        4,
    ]
    assert [measurement.live_families for measurement in measurements] == [7, 7, 7]
    assert [measurement.aggregate_rows for measurement in measurements] == [
        160,
        2_560,
        21_000,
    ]
    assert [measurement.spooled_families for measurement in measurements] == [
        0,
        0,
        5,
    ]
    assert [measurement.normalized_bytes for measurement in measurements] == [
        104_311,
        1_676_802,
        13_810_869,
    ]
    assert [measurement.spool_bytes for measurement in measurements] == [
        0,
        0,
        8_131_599,
    ]
    assert [measurement.spool_replay_passes for measurement in measurements] == [
        0,
        0,
        0,
    ]
    assert [measurement.spool_replayed_rows for measurement in measurements] == [
        0,
        0,
        0,
    ]
    assert [measurement.event_count for measurement in measurements] == [55, 55, 55]
    assert [measurement.checksum_events for measurement in measurements] == [7, 7, 7]
    assert [
        measurement.spooled_checksum_duration_ns for measurement in measurements
    ] == [0, 0, 2_100_500]
    assert [measurement.checksum_manifest_digest for measurement in measurements] == [
        "bb6ac6c6dac4642ca8f56a44d9d2b3710bb34c73a40869b51cb864250cf1d079",
        "4a375515fed875822ca8672e8b73490bd3eea410c9d4a92bde29b2b9a5ca7741",
        "dc172e4b05e1905eeb7fbc5d8915ff9a8a46ff63a3c1b10e99325ba4b014f2a7",
    ]


def test_arch6d_checksum_failure_removes_completed_and_partial_spools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    original_mkstemp = tempfile.mkstemp
    original_add = staged_rows_module._FamilyChecksumAccumulator.add
    calls = 0

    def private_mkstemp(*, prefix, suffix):
        return original_mkstemp(prefix=prefix, suffix=suffix, dir=tmp_path)

    def fail_after_first_family(accumulator, row):
        nonlocal calls
        calls += 1
        if calls == 4_201:
            raise ValueError("synthetic checksum failure")
        original_add(accumulator, row)

    monkeypatch.setattr(row_spool_module.tempfile, "mkstemp", private_mkstemp)
    monkeypatch.setattr(
        staged_rows_module._FamilyChecksumAccumulator,
        "add",
        fail_after_first_family,
    )

    with pytest.raises(ValueError, match="synthetic checksum failure"):
        build_staged_rows(
            _observations(4_200),
            repository_name="arch6d-fixture",
            stage_id="stage-failure",
        )

    assert calls == 4_201
    assert not tuple(tmp_path.iterdir())
