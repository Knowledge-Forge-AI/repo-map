"""Public-safe SCALE18 structural-digest campaign support."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import gc
import time

from repomap_kg.observations.raw import RawObservation
from repomap_kg.storage.row_spool import RowSpool
from repomap_kg.storage.staged_rows import build_staged_rows
from repomap_kg.storage.structural_digest import digest_prepared_stage_rows
from repomap_test_support.scale18_digest_fixtures import (
    Scale18DigestCampaignError,
    _observations,
    _DigestSampler,
    _ArtifactPeak,
    _PreparedSpoolAuthority,
    _check_digest_deadline,
    _read_rss,
    _require_free_space,
)


SCALE18_PROFILES = (
    "file_raw_heavy",
    "canonical_node_heavy",
    "canonical_edge_heavy",
    "evidence_link_heavy",
    "payload_heavy",
    "duplicate_identity_heavy",
    "mixed",
)
SCALE18_BANDS = (32, 128, 512, 2_048, 4_096, 8_192)
_MAX_SIZE = SCALE18_BANDS[-1]
_DIGEST_SAMPLE_CADENCE_SECONDS = 0.05
_DIGEST_TIMEOUT_SECONDS = 30 * 60


@dataclass(frozen=True)
class Scale18Workload:
    """Regenerable workload metadata without retained source observations."""

    profile: str
    work_items: int
    normalized_bytes: int

    @property
    def observations(self) -> tuple[RawObservation, ...]:
        """Regenerate the deterministic observations for one derivation."""

        return tuple(_observations(self.profile, self.work_items))


@dataclass(frozen=True)
class Scale18DerivationResult:
    """Path-free public-safe evidence for one complete digest derivation."""

    profile: str
    work_items: int
    family_counts: dict[str, int]
    structural_digest: str
    logical_artifact_bytes: int
    spool_artifact_bytes: int
    external_sort_artifact_peak_bytes: int
    external_sort_run_count_maximum: int
    temporary_artifact_peak_bytes: int
    pre_digest_rss_bytes: int
    digest_sampled_maximum_rss_bytes: int
    incremental_digest_rss_bytes: int
    preparation_elapsed_seconds: float
    digest_elapsed_seconds: float

    def to_payload(self) -> dict[str, object]:
        """Return bounded evidence without paths, process IDs, or source rows."""

        return {
            "schema_version": 1,
            "profile": self.profile,
            "work_items": self.work_items,
            "family_counts": dict(self.family_counts),
            "structural_digest": self.structural_digest,
            "logical_artifact_bytes": self.logical_artifact_bytes,
            "spool_artifact_bytes": self.spool_artifact_bytes,
            "external_sort_artifact_peak_bytes": (
                self.external_sort_artifact_peak_bytes
            ),
            "external_sort_run_count_maximum": (
                self.external_sort_run_count_maximum
            ),
            "temporary_artifact_peak_bytes": self.temporary_artifact_peak_bytes,
            "pre_digest_rss_bytes": self.pre_digest_rss_bytes,
            "digest_sampled_maximum_rss_bytes": (
                self.digest_sampled_maximum_rss_bytes
            ),
            "incremental_digest_rss_bytes": self.incremental_digest_rss_bytes,
            "preparation_elapsed_seconds": self.preparation_elapsed_seconds,
            "digest_elapsed_seconds": self.digest_elapsed_seconds,
            "digest_maximum_authority": "continuous_50ms_sampled",
            "maximum_authority": "sampled",
        }


def build_scale18_workload(profile: str, size: int) -> Scale18Workload:
    """Build deterministic metadata for one synthetic workload."""

    if profile not in SCALE18_PROFILES:
        raise Scale18DigestCampaignError("SCALE18 profile is invalid")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or not 1 <= size <= _MAX_SIZE
    ):
        raise Scale18DigestCampaignError("SCALE18 profile size is invalid")
    normalized_bytes = sum(
        len(observation.to_json_line().encode("utf-8"))
        for observation in _observations(profile, size)
    )
    return Scale18Workload(profile, size, normalized_bytes)


def derive_scale18_workload(
    workload: Scale18Workload,
    *,
    rss_reader: Callable[[], int | None],
    clock: Callable[[], float] = time.monotonic,
    artifact_limit_bytes: int | None = None,
    free_space_reader: Callable[[], int] | None = None,
    free_space_floor_bytes: int | None = None,
) -> Scale18DerivationResult:
    """Prepare, release source ownership, and derive one exact digest."""

    if not isinstance(workload, Scale18Workload) or not callable(rss_reader):
        raise Scale18DigestCampaignError("SCALE18 derivation input is invalid")
    return derive_scale18_observations(
        profile=workload.profile,
        work_items=workload.work_items,
        observations=_observations(workload.profile, workload.work_items),
        rss_reader=rss_reader,
        clock=clock,
        artifact_limit_bytes=artifact_limit_bytes,
        free_space_reader=free_space_reader,
        free_space_floor_bytes=free_space_floor_bytes,
    )


def derive_scale18_observations(
    *,
    profile: str,
    work_items: int,
    observations: Iterable[RawObservation],
    rss_reader: Callable[[], int | None],
    clock: Callable[[], float] = time.monotonic,
    ownership_observer: Callable[[], None] | None = None,
    artifact_limit_bytes: int | None = None,
    free_space_reader: Callable[[], int] | None = None,
    free_space_floor_bytes: int | None = None,
) -> Scale18DerivationResult:
    """Prepare an observation stream and derive one exact digest."""

    if (
        not isinstance(profile, str)
        or not profile
        or isinstance(work_items, bool)
        or not isinstance(work_items, int)
        or work_items < 0
        or not callable(rss_reader)
        or (ownership_observer is not None and not callable(ownership_observer))
        or (
            artifact_limit_bytes is not None
            and (
                isinstance(artifact_limit_bytes, bool)
                or not isinstance(artifact_limit_bytes, int)
                or artifact_limit_bytes < 1
            )
        )
        or ((free_space_reader is None) != (free_space_floor_bytes is None))
        or (free_space_reader is not None and not callable(free_space_reader))
        or (
            free_space_floor_bytes is not None
            and (
                isinstance(free_space_floor_bytes, bool)
                or not isinstance(free_space_floor_bytes, int)
                or free_space_floor_bytes < 1
            )
        )
    ):
        raise Scale18DigestCampaignError("SCALE18 derivation input is invalid")
    source_observations = tuple(observations)
    del observations
    prepared_artifacts = _PreparedSpoolAuthority(
        limit_bytes=artifact_limit_bytes,
        free_space_reader=free_space_reader,
        free_space_floor_bytes=free_space_floor_bytes,
    )
    preparation_started = clock()
    prepared = build_staged_rows(
        source_observations,
        repository_name="scale18-public-fixture",
        stage_id="scale18-campaign",
        spool_artifact_observer=prepared_artifacts.observe,
    )
    try:
        preparation_elapsed = clock() - preparation_started
        del source_observations
        gc.collect()
        if ownership_observer is not None:
            ownership_observer()
        pre_digest_rss = _read_rss(rss_reader)
        measured_spool_bytes = sum(
            rows.byte_count
            for rows in prepared.family_rows.values()
            if isinstance(rows, RowSpool)
        )
        spool_bytes = prepared_artifacts.current_bytes
        if measured_spool_bytes != spool_bytes:
            raise Scale18DigestCampaignError(
                "SCALE18 prepared artifact accounting is invalid"
            )
        _require_free_space(free_space_reader, free_space_floor_bytes)
        external_artifacts = _ArtifactPeak(
            base_bytes=spool_bytes,
            limit_bytes=artifact_limit_bytes,
            free_space_reader=free_space_reader,
            free_space_floor_bytes=free_space_floor_bytes,
        )
        sampler = _DigestSampler(
            rss_reader,
            clock,
            pre_digest_rss,
        )
        digest_started = clock()
        deadline = digest_started + _DIGEST_TIMEOUT_SECONDS

        def cancellation_check() -> None:
            _check_digest_deadline(clock, deadline)

        sampler.start()
        try:
            structural_digest = digest_prepared_stage_rows(
                prepared,
                cancellation_check=cancellation_check,
                chunk_observer=sampler.observe,
                artifact_observer=external_artifacts.observe,
            )
        except BaseException:
            sampler.cancel()
            raise
        digest_elapsed = clock() - digest_started
        digest_maximum = sampler.finish()
        return Scale18DerivationResult(
            profile,
            work_items,
            dict(prepared.row_counts),
            structural_digest,
            sum(prepared.normalized_byte_counts.values()),
            spool_bytes,
            external_artifacts.maximum_bytes,
            external_artifacts.maximum_run_count,
            spool_bytes + external_artifacts.maximum_bytes,
            pre_digest_rss,
            digest_maximum,
            max(0, digest_maximum - pre_digest_rss),
            preparation_elapsed,
            digest_elapsed,
        )
    finally:
        prepared.close()
