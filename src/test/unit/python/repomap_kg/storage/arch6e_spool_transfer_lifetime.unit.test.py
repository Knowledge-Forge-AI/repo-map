from dataclasses import asdict, dataclass
import hashlib
import json
from unittest.mock import patch

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from repomap_kg.observations.raw import RawObservation
else:
    from repomap_kg.observations import RawObservation
from repomap_kg.storage.row_spool import RowSpool
from repomap_kg.storage.staged_ingestion import _copy_families
from repomap_kg.storage.staged_rows import build_staged_rows


@dataclass(frozen=True)
class _TransferLifetime:
    prepared_rows: int
    copied_rows: int
    live_spools_before_copy: tuple[int, ...]
    live_spool_bytes_before_copy: tuple[int, ...]
    final_live_spools: int
    final_live_spool_bytes: int
    spool_replay_passes: int
    spool_replayed_rows: int
    checksum_manifest_digest: str


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
    prepared = build_staged_rows(
        _observations(size),
        repository_name="arch6c-fixture",
        stage_id="stage-alpha",
    )
    spools = {
        family: rows
        for family, rows in prepared.family_rows.items()
        if isinstance(rows, RowSpool)
    }
    family_by_rows = {
        id(rows): family for family, rows in prepared.family_rows.items()
    }
    live_spools_before_copy = []
    live_spool_bytes_before_copy = []
    copied_rows = 0
    replay_passes = 0
    replayed_rows = 0
    original_iter = RowSpool.__iter__

    def counted_iter(spool):
        nonlocal replay_passes, replayed_rows
        replay_passes += 1
        for row in original_iter(spool):
            replayed_rows += 1
            yield row

    def copy_rows(_connection, _table, rows, *, expected_stage_id):
        nonlocal copied_rows
        assert expected_stage_id == "stage-alpha"
        assert id(rows) in family_by_rows
        live = [spool for spool in spools.values() if spool.path.exists()]
        live_spools_before_copy.append(len(live))
        live_spool_bytes_before_copy.append(
            sum(spool.byte_count for spool in live)
        )
        copied_rows += sum(1 for _row in rows)

    try:
        with (
            patch.object(RowSpool, "__iter__", counted_iter),
            patch(
                "repomap_kg.storage._staged_ingestion_stages.copy_stage_rows",
                copy_rows,
            ),
        ):
            _copy_families(object(), prepared, "stage-alpha")
        checksum_manifest = {
            family: asdict(checksum)
            for family, checksum in prepared.checksums.items()
        }
        digest = hashlib.sha256(
            json.dumps(
                checksum_manifest,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        final_live = [spool for spool in spools.values() if spool.path.exists()]
        return _TransferLifetime(
            prepared_rows=sum(prepared.row_counts.values()),
            copied_rows=copied_rows,
            live_spools_before_copy=tuple(live_spools_before_copy),
            live_spool_bytes_before_copy=tuple(live_spool_bytes_before_copy),
            final_live_spools=len(final_live),
            final_live_spool_bytes=sum(
                spool.byte_count for spool in final_live
            ),
            spool_replay_passes=replay_passes,
            spool_replayed_rows=replayed_rows,
            checksum_manifest_digest=digest,
        )
    finally:
        prepared.close()


def test_arch6f_releases_each_spool_after_exact_small_medium_full_copy():
    measurements = [_measure(size) for size in (32, 512, 4_200)]

    assert [item.prepared_rows for item in measurements] == [160, 2_560, 21_000]
    assert [item.copied_rows for item in measurements] == [160, 2_560, 21_000]
    assert [item.live_spools_before_copy for item in measurements] == [
        (0, 0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0, 0),
        (5, 4, 3, 2, 2, 1, 0),
    ]
    assert [item.live_spool_bytes_before_copy for item in measurements] == [
        (0, 0, 0, 0, 0, 0, 0),
        (0, 0, 0, 0, 0, 0, 0),
        (
            8_131_599,
            6_399_216,
            4_251_033,
            3_218_943,
            3_218_943,
            1_077_180,
            0,
        ),
    ]
    assert [item.final_live_spools for item in measurements] == [0, 0, 0]
    assert [item.final_live_spool_bytes for item in measurements] == [
        0,
        0,
        0,
    ]
    assert [item.spool_replay_passes for item in measurements] == [0, 0, 5]
    assert [item.spool_replayed_rows for item in measurements] == [0, 0, 21_000]
    assert [item.checksum_manifest_digest for item in measurements] == [
        "bb6ac6c6dac4642ca8f56a44d9d2b3710bb34c73a40869b51cb864250cf1d079",
        "4a375515fed875822ca8672e8b73490bd3eea410c9d4a92bde29b2b9a5ca7741",
        "dc172e4b05e1905eeb7fbc5d8915ff9a8a46ff63a3c1b10e99325ba4b014f2a7",
    ]


def test_arch6f_copy_failure_leaves_unconsumed_spools_for_final_cleanup():
    prepared = build_staged_rows(
        _observations(4_200),
        repository_name="arch6c-fixture",
        stage_id="stage-alpha",
    )
    spools = {
        family: rows
        for family, rows in prepared.family_rows.items()
        if isinstance(rows, RowSpool)
    }
    calls = 0

    def fail_third_copy(_connection, _table, rows, *, expected_stage_id):
        nonlocal calls
        assert expected_stage_id == "stage-alpha"
        calls += 1
        if calls == 3:
            raise ValueError("synthetic copy failure")
        tuple(rows)

    try:
        with (
            patch(
                "repomap_kg.storage._staged_ingestion_stages.copy_stage_rows",
                fail_third_copy,
            ),
            pytest.raises(ValueError, match="synthetic copy failure"),
        ):
            _copy_families(object(), prepared, "stage-alpha")

        assert not spools["files"].path.exists()
        assert not spools["raw_observations"].path.exists()
        assert spools["canonical_nodes"].path.exists()
        assert spools["canonical_evidence"].path.exists()
        assert spools["canonical_node_evidence"].path.exists()
    finally:
        prepared.close()

    assert all(not spool.path.exists() for spool in spools.values())
