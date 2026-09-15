"""Resource policy, worker lifecycle, and bounded report helpers for SCALE18."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import Enum
import subprocess
from typing import Protocol

from repomap_test_support.scale18_digest_campaign import (
    SCALE18_BANDS,
    SCALE18_PROFILES,
)


_RSS_HARD_LIMIT_BYTES = 6 * 1024**3
_RSS_TARGET_BYTES = int(4.5 * 1024**3)
_INCREMENTAL_DIGEST_TARGET_BYTES = int(1.5 * 1024**3)
_HEADROOM_TARGET_BYTES = int(1.5 * 1024**3)
_ARTIFACT_HARD_LIMIT_BYTES = 16 * 1024**3
_FREE_SPACE_HARD_LIMIT_BYTES = 20 * 1024**3
_CI_SAFE_ARTIFACT_HARD_LIMIT_BYTES = 64 * 1024**2
_CI_SAFE_FREE_SPACE_HARD_LIMIT_BYTES = 10 * 1024**3
_CI_SAFE_MAX_PROFILE_SIZE = 2_048
_DERIVATION_TIMEOUT_SECONDS = 60 * 60
_RSS_CADENCE_SECONDS = 0.1
_RSS_READER_LOSS_LIMIT = 10
_TERMINATION_GRACE_SECONDS = 5.0
_REPEAT_MAXIMUM_KEYS: tuple[tuple[str, str], ...] = (
    ("spool_artifact_bytes", "spool_artifact_bytes"),
    ("external_sort_artifact_peak_bytes", "external_sort_artifact_peak_bytes"),
    ("external_sort_run_count_maximum", "external_sort_run_count_maximum"),
    ("temporary_artifact_peak_bytes", "temporary_artifact_peak_bytes"),
    ("maximum_observed_rss_bytes", "total_sampled_maximum_rss_bytes"),
    (
        "maximum_incremental_digest_rss_bytes",
        "conservative_incremental_digest_rss_bytes",
    ),
)


class Scale18CampaignError(RuntimeError):
    pass


class _WorkerResourcePolicy(Enum):
    """Closed resource envelopes accepted by the private worker CLI."""

    FULL_CAMPAIGN = "full_campaign"
    CI_SAFE_QUALIFICATION = "ci_safe_qualification"

    @property
    def rss_limit_bytes(self) -> int:
        return _RSS_HARD_LIMIT_BYTES

    @property
    def artifact_limit_bytes(self) -> int:
        if self is _WorkerResourcePolicy.FULL_CAMPAIGN:
            return _ARTIFACT_HARD_LIMIT_BYTES
        return _CI_SAFE_ARTIFACT_HARD_LIMIT_BYTES

    @property
    def free_space_floor_bytes(self) -> int:
        if self is _WorkerResourcePolicy.FULL_CAMPAIGN:
            return _FREE_SPACE_HARD_LIMIT_BYTES
        return _CI_SAFE_FREE_SPACE_HARD_LIMIT_BYTES

    @property
    def maximum_profile_size(self) -> int | None:
        if self is _WorkerResourcePolicy.FULL_CAMPAIGN:
            return None
        return _CI_SAFE_MAX_PROFILE_SIZE


_Report = dict[str, object]
_RequireFreeSpace = Callable[[_WorkerResourcePolicy], None]
_RequireCaseLimits = Callable[[_Report, _WorkerResourcePolicy], None]
_TargetAcceptance = Callable[[_Report], bool]
_DoublingComparisons = Callable[[Sequence[_Report]], tuple[_Report, ...]]


class _TerminableProcess(Protocol):
    def poll(self) -> int | None:
        ...

    def terminate(self) -> None:
        ...

    def kill(self) -> None:
        ...


class _RunWorker(Protocol):
    def __call__(
        self,
        arguments: Sequence[str],
        *,
        policy: _WorkerResourcePolicy,
    ) -> dict[str, object]:
        ...


class _WorkerTermination:
    """Own one bounded terminate, kill, and reason transition."""

    def __init__(
        self,
        process: _TerminableProcess,
        *,
        clock: Callable[[], float],
        grace_seconds: float,
    ) -> None:
        self._process = process
        self._clock = clock
        self._grace_seconds = grace_seconds
        self._requested_at: float | None = None
        self._kill_sent = False
        self.reason: str | None = None

    def request(self, reason: str) -> None:
        if self.reason is not None:
            return
        self.reason = reason
        self._requested_at = self._clock()
        if self._process.poll() is None:
            self._process.terminate()

    def enforce(self) -> None:
        if (
            self.reason is None
            or self._requested_at is None
            or self._kill_sent
            or self._process.poll() is not None
            or self._clock() - self._requested_at < self._grace_seconds
        ):
            return
        self._process.kill()
        self._kill_sent = True


class _GuardedRssReader:
    """Apply duration and persistent-reader-loss stops around RSS reads."""

    def __init__(
        self,
        process: _TerminableProcess,
        termination: _WorkerTermination,
        *,
        reader: Callable[[], int | None],
        clock: Callable[[], float],
        duration_limit_seconds: float,
        reader_loss_limit: int,
    ) -> None:
        self._process = process
        self._termination = termination
        self._reader = reader
        self._clock = clock
        self._started = clock()
        self._duration_limit_seconds = duration_limit_seconds
        self._reader_loss_limit = reader_loss_limit
        self._consecutive_missing = 0

    def __call__(self) -> int | None:
        live = self._process.poll() is None
        if live and self._clock() - self._started >= self._duration_limit_seconds:
            self._termination.request("derivation_duration_limit")
        try:
            rss_bytes = self._reader()
        except (OSError, subprocess.SubprocessError):
            rss_bytes = None
        if live:
            self._consecutive_missing = (
                self._consecutive_missing + 1 if rss_bytes is None else 0
            )
            if self._consecutive_missing >= self._reader_loss_limit:
                self._termination.request("rss_reader_unavailable")
        self._termination.enforce()
        return rss_bytes


def run_profile_campaign(
    *,
    run_worker: _RunWorker,
    require_free_space: _RequireFreeSpace,
    require_case_limits: _RequireCaseLimits,
    target_acceptance: _TargetAcceptance,
    doubling_comparisons: _DoublingComparisons,
) -> _Report:
    """Run all seven profiles and five bands sequentially."""

    policy = _WorkerResourcePolicy.FULL_CAMPAIGN
    require_free_space(policy)
    cases: list[dict[str, object]] = []
    for profile in SCALE18_PROFILES:
        for size in SCALE18_BANDS:
            payload = run_worker(
                ("_worker-profile", "--profile", profile, "--size", str(size)),
                policy=policy,
            )
            require_case_limits(payload, policy)
            cases.append(payload)
    largest = [case for case in cases if case["work_items"] == SCALE18_BANDS[-1]]
    largest_accepted = all(target_acceptance(case) for case in largest)
    doubling = doubling_comparisons(cases)
    doubling_accepted = all(comparison["accepted"] for comparison in doubling)
    return {
        "schema_version": 1,
        "campaign": "geometric_profiles",
        "profiles": list(SCALE18_PROFILES),
        "bands": list(SCALE18_BANDS),
        "concurrency": 1,
        "cases": cases,
        "largest_band_target_accepted": largest_accepted,
        "doubling_comparisons": doubling,
        "doubling_readiness_accepted": doubling_accepted,
        "campaign_readiness_accepted": largest_accepted and doubling_accepted,
        "maximum_authority": "sampled",
    }


def run_repository_repeats(
    root: object,
    label: str,
    *,
    run_worker: _RunWorker,
    require_free_space: _RequireFreeSpace,
    require_case_limits: _RequireCaseLimits,
) -> _Report:
    """Run two unchanged static derivations of one caller-verified root."""

    policy = _WorkerResourcePolicy.FULL_CAMPAIGN
    require_free_space(policy)
    first = run_worker(
        ("_worker-repository", "--root", str(root), "--label", label),
        policy=policy,
    )
    second = run_worker(
        ("_worker-repository", "--root", str(root), "--label", label),
        policy=policy,
    )
    for payload in (first, second):
        require_case_limits(payload, policy)
    equal = (
        first["source_generation"] == second["source_generation"]
        and first["family_counts"] == second["family_counts"]
        and first["structural_digest"] == second["structural_digest"]
        and first["logical_artifact_bytes"] == second["logical_artifact_bytes"]
    )
    if not equal:
        raise Scale18CampaignError("repository repeat evidence is not exact")
    return {
        "schema_version": 1,
        "campaign": "repository_repeat",
        "source_category": label,
        "repeat_count": 2,
        "exact_repeat": True,
        "source_generation_equal": True,
        "family_counts": first["family_counts"],
        "structural_digest_equal": True,
        "logical_artifact_bytes": first["logical_artifact_bytes"],
        **_repeat_maxima(first, second),
        "maximum_authority": "sampled",
    }


def _repeat_maxima(first: _Report, second: _Report) -> dict[str, int]:
    return {
        output_key: max(_pair_ints(first, second, source_key))
        for output_key, source_key in _REPEAT_MAXIMUM_KEYS
    }


def doubling_comparisons(
    cases: Sequence[dict[str, object]],
    *,
    profiles: Sequence[str] = SCALE18_PROFILES,
    bands: Sequence[int] = SCALE18_BANDS,
) -> tuple[dict[str, object], ...]:
    """Compare the largest adjacent geometric workload bands."""

    if len(bands) < 2 or bands[-1] != bands[-2] * 2:
        raise Scale18CampaignError(
            "campaign top workload bands do not form a doubling pair"
        )
    lower_size, upper_size = bands[-2:]
    by_key: dict[tuple[str, int], dict[str, object]] = {}
    for case in cases:
        profile = case.get("profile")
        work_items = case.get("work_items")
        if (
            not isinstance(profile, str)
            or isinstance(work_items, bool)
            or not isinstance(work_items, int)
        ):
            raise Scale18CampaignError("campaign doubling evidence is invalid")
        key = (profile, work_items)
        if key in by_key:
            raise Scale18CampaignError("campaign doubling evidence is invalid")
        by_key[key] = case
    comparisons: list[dict[str, object]] = []
    for profile in profiles:
        try:
            lower = by_key[(profile, lower_size)]
            upper = by_key[(profile, upper_size)]
        except KeyError as error:
            raise Scale18CampaignError(
                "campaign doubling evidence is incomplete"
            ) from error
        lower_maximum = required_total_sampled_rss(lower)
        upper_maximum = required_total_sampled_rss(upper)
        lower_increment, upper_increment = _pair_ints(
            lower, upper, "incremental_digest_rss_bytes"
        )
        lower_conservative, upper_conservative = _pair_ints(
            lower, upper, "conservative_incremental_digest_rss_bytes"
        )
        lower_baseline, upper_baseline = _pair_ints(
            lower, upper, "pre_digest_rss_bytes"
        )
        lower_process_baseline, upper_process_baseline = _pair_ints(
            lower, upper, "process_baseline_rss_bytes"
        )
        lower_digest_maximum, upper_digest_maximum = _pair_ints(
            lower, upper, "digest_sampled_maximum_rss_bytes"
        )
        growth_percent = percentage_growth(lower_maximum, upper_maximum)
        direct_target_met = upper_maximum * 4 <= lower_maximum * 5
        fixed_baseline_dominates = (
            lower_process_baseline >= lower_increment
            and upper_process_baseline >= upper_increment
        )
        baseline_stable = (
            upper_process_baseline * 4 <= lower_process_baseline * 5
            and lower_process_baseline * 4 <= upper_process_baseline * 5
        )
        digest_target_met = upper_digest_maximum * 4 <= lower_digest_maximum * 5
        fixed_baseline_exception = (
            not direct_target_met
            and fixed_baseline_dominates
            and baseline_stable
            and upper_increment <= _INCREMENTAL_DIGEST_TARGET_BYTES
            and digest_target_met
        )
        comparisons.append(
            {
                "profile": profile,
                "lower_work_items": lower_size,
                "upper_work_items": upper_size,
                "total_rss_growth_percent": growth_percent,
                "lower_incremental_digest_rss_bytes": lower_increment,
                "upper_incremental_digest_rss_bytes": upper_increment,
                "lower_conservative_incremental_digest_rss_bytes": lower_conservative,
                "upper_conservative_incremental_digest_rss_bytes": upper_conservative,
                "lower_digest_sampled_maximum_rss_bytes": lower_digest_maximum,
                "upper_digest_sampled_maximum_rss_bytes": upper_digest_maximum,
                "digest_phase_maximum_growth_percent": percentage_growth(
                    lower_digest_maximum,
                    upper_digest_maximum,
                ),
                "digest_phase_working_set_target_met": digest_target_met,
                "lower_process_baseline_rss_bytes": lower_process_baseline,
                "upper_process_baseline_rss_bytes": upper_process_baseline,
                "process_baseline_growth_percent": percentage_growth(
                    lower_process_baseline,
                    upper_process_baseline,
                ),
                "lower_pre_digest_rss_bytes": lower_baseline,
                "upper_pre_digest_rss_bytes": upper_baseline,
                "pre_digest_rss_growth_percent": percentage_growth(
                    lower_baseline,
                    upper_baseline,
                ),
                "fixed_baseline_dominates": fixed_baseline_dominates,
                "baseline_stable": baseline_stable,
                "direct_target_met": direct_target_met,
                "fixed_baseline_exception": fixed_baseline_exception,
                "accepted": direct_target_met or fixed_baseline_exception,
            }
        )
    return tuple(comparisons)


def required_total_sampled_rss(payload: dict[str, object]) -> int:
    return required_int(payload, "total_sampled_maximum_rss_bytes")

def percentage_growth(lower: int, upper: int) -> float:
    if lower <= 0 or upper < 0:
        raise Scale18CampaignError("campaign RSS growth evidence is invalid")
    return round((upper - lower) * 100.0 / lower, 1)


def required_int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise Scale18CampaignError("campaign numeric evidence is invalid")
    return value


def _pair_ints(first: _Report, second: _Report, key: str) -> tuple[int, int]:
    return required_int(first, key), required_int(second, key)
