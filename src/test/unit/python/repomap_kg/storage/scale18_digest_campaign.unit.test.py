from __future__ import annotations

import threading
import time

import pytest

from repomap_kg.observations.raw import RawObservation
from repomap_test_support.scale18_digest_campaign import (
    SCALE18_BANDS,
    SCALE18_PROFILES,
    Scale18DigestCampaignError,
    _ArtifactPeak,
    _DigestSampler,
    _PreparedSpoolAuthority,
    _check_digest_deadline,
    _require_free_space,
    build_scale18_workload,
    derive_scale18_observations,
    derive_scale18_workload,
)


def test_scale18_campaign_has_seven_profiles_and_five_geometric_bands() -> None:
    assert SCALE18_PROFILES == (
        "file_raw_heavy",
        "canonical_node_heavy",
        "canonical_edge_heavy",
        "evidence_link_heavy",
        "payload_heavy",
        "duplicate_identity_heavy",
        "mixed",
    )
    assert len(SCALE18_BANDS) >= 5
    assert SCALE18_BANDS[-2:] == (4_096, 8_192)
    assert all(
        right >= left * 2
        for left, right in zip(SCALE18_BANDS, SCALE18_BANDS[1:])
    )


def test_scale18_workloads_are_public_safe_and_deterministic() -> None:
    first = build_scale18_workload("evidence_link_heavy", SCALE18_BANDS[0])
    second = build_scale18_workload("evidence_link_heavy", SCALE18_BANDS[0])

    assert first.profile == "evidence_link_heavy"
    assert first.work_items == SCALE18_BANDS[0]
    assert first.observations == second.observations
    assert first.normalized_bytes == second.normalized_bytes


def test_scale18_derivation_repeats_exactly_and_accounts_artifacts() -> None:
    workload = build_scale18_workload("mixed", SCALE18_BANDS[0])
    rss_samples = iter((100, 110, 120, 130, 140, 150))

    first = derive_scale18_workload(
        workload,
        rss_reader=lambda: next(rss_samples, 150),
    )
    second = derive_scale18_workload(
        workload,
        rss_reader=lambda: 150,
    )

    assert first.family_counts == second.family_counts
    assert first.structural_digest == second.structural_digest
    assert set(first.family_counts) == {
        "files",
        "raw_observations",
        "canonical_nodes",
        "canonical_edges",
        "canonical_evidence",
        "canonical_node_evidence",
        "canonical_edge_evidence",
    }
    assert first.logical_artifact_bytes > 0
    assert first.spool_artifact_bytes >= 0
    assert first.digest_sampled_maximum_rss_bytes >= (
        first.pre_digest_rss_bytes
    )
    assert first.incremental_digest_rss_bytes >= 0
    assert first.temporary_artifact_peak_bytes == (
        first.spool_artifact_bytes + first.external_sort_artifact_peak_bytes
    )


def test_scale18_releases_the_input_owner_before_digest_sampling() -> None:
    released: list[bool] = []

    class _OwnedObservations:
        def __iter__(self):
            yield RawObservation(
                kind="file",
                source_id="source.py",
                path="source.py",
                confidence="extracted",
                extractor="scale18-test",
                extractor_version="1",
                metadata={"language": "python", "role": "source"},
            )

        def __del__(self) -> None:
            released.append(True)

    ownership_checks: list[bool] = []
    derive_scale18_observations(
        profile="ownership",
        work_items=1,
        observations=_OwnedObservations(),
        rss_reader=lambda: 100,
        ownership_observer=lambda: ownership_checks.append(bool(released)),
    )

    assert ownership_checks == [True]


def test_temporary_artifact_limit_includes_prepared_spools_and_live_runs() -> None:
    artifacts = _ArtifactPeak(
        base_bytes=70,
        limit_bytes=100,
        free_space_reader=None,
        free_space_floor_bytes=None,
    )

    artifacts.observe(29, 2)
    with pytest.raises(
        Scale18DigestCampaignError,
        match="temporary artifact limit reached",
    ):
        artifacts.observe(30, 3)


def test_temporary_artifact_growth_preserves_live_free_space_floor() -> None:
    free_bytes = [26]
    artifacts = _ArtifactPeak(
        base_bytes=0,
        limit_bytes=100,
        free_space_reader=lambda: free_bytes[0],
        free_space_floor_bytes=20,
    )

    artifacts.observe(5, 1)
    free_bytes[0] = 25
    with pytest.raises(
        Scale18DigestCampaignError,
        match="free-space floor reached",
    ):
        artifacts.observe(10, 1)


def test_prepared_spool_authority_rejects_aggregate_artifact_ceiling() -> None:
    artifacts = _PreparedSpoolAuthority(
        limit_bytes=100,
        free_space_reader=None,
        free_space_floor_bytes=None,
    )

    artifacts.observe("files", 60)
    artifacts.observe("raw_observations", 39)
    with pytest.raises(
        Scale18DigestCampaignError,
        match="temporary artifact limit reached",
    ):
        artifacts.observe("raw_observations", 40)

    assert artifacts.current_bytes == 99


def test_prepared_spool_authority_rejects_free_space_floor_equality() -> None:
    artifacts = _PreparedSpoolAuthority(
        limit_bytes=None,
        free_space_reader=lambda: 25,
        free_space_floor_bytes=20,
    )

    with pytest.raises(
        Scale18DigestCampaignError,
        match="free-space floor reached",
    ):
        artifacts.observe("files", 5)

    assert artifacts.current_bytes == 0


def test_free_space_preflight_requires_strictly_more_than_floor() -> None:
    with pytest.raises(
        Scale18DigestCampaignError,
        match="free-space floor reached",
    ):
        _require_free_space(lambda: 20, 20)


def test_digest_deadline_rejects_exact_ceiling() -> None:
    with pytest.raises(TimeoutError, match="duration limit"):
        _check_digest_deadline(lambda: 1_800.0, 1_800.0)


def test_digest_sampler_observes_without_hash_chunk_callbacks_and_settles() -> None:
    sampled_peak = threading.Event()
    samples = iter((100, 200, 150))

    def reader() -> int:
        value = next(samples, 150)
        if value == 200:
            sampled_peak.set()
        return value

    sampler = _DigestSampler(
        reader,
        time.monotonic,
        100,
        cadence_seconds=0.001,
    )
    sampler.start()
    assert sampled_peak.wait(timeout=1.0)

    assert sampler.finish() == 200
    assert sampler.settled is True
    assert sampler._thread is not None
    assert not sampler._thread.is_alive()


def test_digest_sampler_surfaces_reader_failure_after_settlement() -> None:
    reader_called = threading.Event()

    def reader() -> int:
        reader_called.set()
        raise RuntimeError("reader failed")

    sampler = _DigestSampler(
        reader,
        time.monotonic,
        100,
        cadence_seconds=0.001,
    )
    sampler.start()
    assert reader_called.wait(timeout=1.0)

    with pytest.raises(RuntimeError, match="reader failed"):
        sampler.finish()
    assert sampler.settled is True
    assert sampler._thread is not None
    assert not sampler._thread.is_alive()


def test_digest_sampler_cancel_settles_without_a_final_sample() -> None:
    reader_calls = 0

    def reader() -> int:
        nonlocal reader_calls
        reader_calls += 1
        return 100

    sampler = _DigestSampler(
        reader,
        time.monotonic,
        100,
        cadence_seconds=1.0,
    )
    sampler.start()
    sampler.cancel()

    assert sampler.settled is True
    assert sampler._thread is not None
    assert not sampler._thread.is_alive()
    assert reader_calls == 0
