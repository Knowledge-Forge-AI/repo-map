from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import operator
from unittest.mock import patch

import pytest

from repomap_kg.canonicalization import _go_context as go_context_module
from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage import staged_rows as staged_rows_module
from repomap_kg.storage.row_spool import RowSpool
from repomap_kg.storage._staged_row_adapters import _MeasuredObservationReplay
from repomap_kg.storage.staging_observability import StagingMeasurementCategory, StagingMeasurements


@pytest.mark.parametrize("sized", [True, False])
def test_measured_replay_length_hint_preserves_iteration(sized: bool) -> None:
    observations = _observations(2)
    source = observations if sized else iter(observations)
    measurements = StagingMeasurements(lambda event: None)
    replay = _MeasuredObservationReplay(
        source, measurements, StagingMeasurementCategory.OBSERVATION_RAW_REPLAY,
        StagingMeasurementCategory.OBSERVATION_RAW_REPLAY_ROWS, 1,
    )
    if sized:
        assert len(replay) == 2
        assert operator.length_hint(replay, 7) == 2
    else:
        with pytest.raises(TypeError, match="has no len"):
            len(replay)
        assert operator.length_hint(replay, 7) == 7
    assert measurements.event_count == 0
    assert list(replay) == list(observations)
    assert measurements.event_count == 2


@dataclass(frozen=True)
class _PassAttribution:
    passes: tuple[tuple[str, int], ...]
    visits: tuple[tuple[str, int], ...]
    prepared_rows: int
    family_handles: int
    spooled_families: int
    spool_bytes: int
    go_context_claims: int
    checksum_manifest_digest: str


class _TrackedObservations(Sequence[RawObservation]):
    def __init__(self, values, active):
        self._values = tuple(values)
        self._active = active
        self.passes: Counter[str] = Counter()
        self.visits: Counter[str] = Counter()

    def __len__(self):
        return len(self._values)

    def __getitem__(self, index):
        return self._values[index]

    def __iter__(self) -> Iterator[RawObservation]:
        label = self._active[-1]
        self.passes[label] += 1
        for value in self._values:
            self.visits[label] += 1
            yield value


def _observations(size):
    return tuple(
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
    )


def _measure(size):
    active = ["unattributed"]
    observations = _TrackedObservations(_observations(size), active)
    original_file_rows = staged_rows_module.file_rows_from_observations
    original_canonicalize = staged_rows_module.canonicalize_observations
    original_go_context = go_context_module.build_go_canonical_context
    original_raw_rows = staged_rows_module._iter_raw_observation_rows
    go_context_claims = 0

    @contextmanager
    def attributed(label):
        active.append(label)
        try:
            yield
        finally:
            active.pop()

    def file_rows(values):
        with attributed("file_projection"):
            return original_file_rows(values)

    def canonicalize(values, *, repository_scope):
        with attributed("canonical_dispatch"):
            return original_canonicalize(
                values,
                repository_scope=repository_scope,
            )

    def go_context(values, *, repository_scope):
        nonlocal go_context_claims
        with attributed("go_context_filter"):
            result = original_go_context(
                values,
                repository_scope=repository_scope,
            )
        go_context_claims = (
            len(result.node_claims)
            + sum(len(keys) for keys in result.node_keys_by_source_id.values())
            + sum(
                len(edges) for edges in result.edge_claims_by_source_id.values()
            )
        )
        return result

    def raw_rows(values):
        def iterator():
            with attributed("raw_projection"):
                yield from original_raw_rows(values)

        return iterator()

    with (
        patch.object(
            staged_rows_module,
            "file_rows_from_observations",
            file_rows,
        ),
        patch.object(
            staged_rows_module,
            "canonicalize_observations",
            canonicalize,
        ),
        patch.object(
            go_context_module,
            "build_go_canonical_context",
            go_context,
        ),
        patch.object(
            staged_rows_module,
            "_iter_raw_observation_rows",
            raw_rows,
        ),
    ):
        prepared = staged_rows_module.build_staged_rows(
            observations,
            repository_name="arch6c-fixture",
            stage_id="stage-alpha",
        )
    try:
        spools = [
            rows
            for rows in prepared.family_rows.values()
            if isinstance(rows, RowSpool)
        ]
        manifest = {
            family: asdict(checksum)
            for family, checksum in prepared.checksums.items()
        }
        digest = hashlib.sha256(
            json.dumps(
                manifest,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return _PassAttribution(
            passes=tuple(sorted(observations.passes.items())),
            visits=tuple(sorted(observations.visits.items())),
            prepared_rows=sum(prepared.row_counts.values()),
            family_handles=len(prepared.family_rows),
            spooled_families=len(spools),
            spool_bytes=sum(spool.byte_count for spool in spools),
            go_context_claims=go_context_claims,
            checksum_manifest_digest=digest,
        )
    finally:
        prepared.close()


def test_arch6g_attributes_every_small_medium_full_observation_pass():
    measurements = [_measure(size) for size in (32, 512, 4_200)]
    labels = (
        "canonical_dispatch",
        "file_projection",
        "go_context_filter",
        "raw_projection",
    )

    assert [item.passes for item in measurements] == [
        tuple((label, 1) for label in labels),
        tuple((label, 1) for label in labels),
        tuple((label, 1) for label in labels),
    ]
    assert [item.visits for item in measurements] == [
        tuple((label, 32) for label in labels),
        tuple((label, 512) for label in labels),
        tuple((label, 4_200) for label in labels),
    ]
    assert [item.prepared_rows for item in measurements] == [160, 2_560, 21_000]
    assert [item.family_handles for item in measurements] == [7, 7, 7]
    assert [item.spooled_families for item in measurements] == [0, 0, 5]
    assert [item.spool_bytes for item in measurements] == [0, 0, 8_131_599]
    assert [item.go_context_claims for item in measurements] == [0, 0, 0]
    assert [item.checksum_manifest_digest for item in measurements] == [
        "bb6ac6c6dac4642ca8f56a44d9d2b3710bb34c73a40869b51cb864250cf1d079",
        "4a375515fed875822ca8672e8b73490bd3eea410c9d4a92bde29b2b9a5ca7741",
        "dc172e4b05e1905eeb7fbc5d8915ff9a8a46ff63a3c1b10e99325ba4b014f2a7",
    ]
