"""REPOMAP-CI0B-FIX1 exhaustive profile: quota, reserve, and preserved gates."""

from __future__ import annotations

import pytest

from repomap_test_support.resource_admission import (
    HostSignals,
    MemoryPressure,
    decide_host_admission,
)
from repomap_test_support.resource_hygiene_policy import (
    GIB,
    MIN_FREE_DISK_BYTES,
    HygieneConfig,
    HygieneProfile,
)


def signals(
    *,
    free_disk_bytes: int = 10 * GIB,
    free_disk_percent: int = 50,
    memory_pressure: MemoryPressure = MemoryPressure.DEGRADED,
    docker_responsive: bool | None = True,
    live_mutating_runs: int = 0,
    operator_attested_exclusive: bool = True,
    operator_attested_pressure_degradation: bool = True,
    campaign_plan_id: str | None = None,
    declared_complete_gates: int = 1,
    buildkit_image_present: bool | None = None,
    memory_free_percent: int | None = 75,
) -> HostSignals:
    return HostSignals(
        free_disk_bytes=free_disk_bytes,
        free_disk_percent=free_disk_percent,
        memory_pressure=memory_pressure,
        docker_responsive=docker_responsive,
        live_mutating_runs=live_mutating_runs,
        operator_attested_exclusive=operator_attested_exclusive,
        operator_attested_pressure_degradation=operator_attested_pressure_degradation,
        campaign_plan_id=campaign_plan_id,
        declared_complete_gates=declared_complete_gates,
        buildkit_image_present=buildkit_image_present,
        memory_free_percent=memory_free_percent,
    )


def test_exhaustive_profile_exists_with_operator_selected_quota():
    assert HygieneProfile.EXHAUSTIVE.value == "exhaustive"
    assert HygieneProfile.EXHAUSTIVE.quota == (4 * GIB, 750_000)
    assert HygieneProfile.EXHAUSTIVE.quota[0] == 4_294_967_296


def test_exhaustive_declares_exactly_one_complete_gate():
    admitted = decide_host_admission(
        HygieneProfile.EXHAUSTIVE, HygieneConfig(), signals(declared_complete_gates=1)
    )
    refused = decide_host_admission(
        HygieneProfile.EXHAUSTIVE, HygieneConfig(), signals(declared_complete_gates=2)
    )

    assert admitted.admitted is True
    assert refused.admitted is False
    assert refused.reason == "complete_gate_count_invalid"


def test_exhaustive_host_reserve_is_the_ten_gib_architectural_floor():
    at_floor = decide_host_admission(
        HygieneProfile.EXHAUSTIVE, HygieneConfig(), signals(free_disk_bytes=10 * GIB)
    )
    below_floor = decide_host_admission(
        HygieneProfile.EXHAUSTIVE,
        HygieneConfig(),
        signals(free_disk_bytes=10 * GIB - 1),
    )

    assert MIN_FREE_DISK_BYTES == 10 * GIB
    assert at_floor.admitted is True
    assert below_floor.admitted is False
    assert below_floor.reason == "free_disk_reserve"


def test_exhaustive_reserve_is_independent_of_its_runaway_quota():
    """Free space above the 4 GiB quota is not sufficient; the floor governs."""
    above_quota_below_floor = decide_host_admission(
        HygieneProfile.EXHAUSTIVE, HygieneConfig(), signals(free_disk_bytes=8 * GIB)
    )
    well_above_floor = decide_host_admission(
        HygieneProfile.EXHAUSTIVE, HygieneConfig(), signals(free_disk_bytes=30 * GIB)
    )

    assert above_quota_below_floor.admitted is False
    assert above_quota_below_floor.reason == "free_disk_reserve"
    assert well_above_floor.admitted is True


def test_exhaustive_reserve_override_at_the_floor_is_accepted():
    config = HygieneConfig(profile_free_disk_reserve_bytes=10 * GIB)

    decision = decide_host_admission(
        HygieneProfile.EXHAUSTIVE, config, signals(free_disk_bytes=12 * GIB)
    )

    assert decision.admitted is True


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"docker_responsive": False}, "docker_unresponsive"),
        ({"docker_responsive": None}, "docker_unresponsive"),
        ({"live_mutating_runs": 1}, "concurrency_limit"),
        (
            {"memory_pressure": MemoryPressure.CRITICAL},
            "memory_pressure_critical",
        ),
        (
            {"operator_attested_pressure_degradation": False},
            "pressure_degradation_attestation_missing",
        ),
        ({"memory_free_percent": None}, "degraded_memory_percentage_invalid"),
        ({"operator_attested_exclusive": False}, "exclusive_attestation_missing"),
        (
            {
                "memory_pressure": MemoryPressure.WARN,
                "memory_free_percent": None,
            },
            "memory_pressure_not_normal",
        ),
    ],
)
def test_exhaustive_keeps_complete_run_safety_gates(overrides, reason):
    decision = decide_host_admission(
        HygieneProfile.EXHAUSTIVE, HygieneConfig(), signals(**overrides)
    )

    assert decision.admitted is False
    assert decision.reason == reason


def test_exhaustive_admission_records_the_degraded_linux_reading():
    decision = decide_host_admission(
        HygieneProfile.EXHAUSTIVE, HygieneConfig(), signals()
    )

    assert decision.outcome == "admitted"
    assert decision.reason == "exhaustive"
    assert decision.degraded_signals == ("memory_pressure_degraded",)


def test_exhaustive_requires_no_campaign_plan():
    decision = decide_host_admission(
        HygieneProfile.EXHAUSTIVE, HygieneConfig(), signals(campaign_plan_id=None)
    )

    assert decision.admitted is True


def test_heavy_and_qualification_admission_policy_is_unchanged():
    heavy_reserve = decide_host_admission(
        HygieneProfile.HEAVY, HygieneConfig(), signals(free_disk_bytes=99 * GIB)
    )
    heavy_admitted = decide_host_admission(
        HygieneProfile.HEAVY, HygieneConfig(), signals(free_disk_bytes=100 * GIB)
    )
    heavy_override_below_quota = decide_host_admission(
        HygieneProfile.HEAVY,
        HygieneConfig(profile_free_disk_reserve_bytes=32 * GIB - 1),
        signals(free_disk_bytes=100 * GIB),
    )
    qualification_reserve = decide_host_admission(
        HygieneProfile.QUALIFICATION,
        HygieneConfig(),
        signals(free_disk_bytes=149 * GIB, campaign_plan_id="REPOMAP-CI0B"),
    )

    assert HygieneProfile.HEAVY.quota == (32 * GIB, 750_000)
    assert HygieneProfile.QUALIFICATION.quota == (64 * GIB, 1_500_000)
    assert heavy_reserve.admitted is False
    assert heavy_reserve.reason == "free_disk_reserve"
    assert heavy_admitted.admitted is True
    assert heavy_override_below_quota.admitted is False
    assert heavy_override_below_quota.reason == "free_disk_reserve_override_invalid"
    assert qualification_reserve.admitted is False
    assert qualification_reserve.reason == "free_disk_reserve"


def test_configuration_digest_stays_deterministic_across_profiles():
    first = HygieneConfig(requested_profile=HygieneProfile.EXHAUSTIVE)
    second = HygieneConfig(requested_profile=HygieneProfile.EXHAUSTIVE)
    heavy = HygieneConfig(requested_profile=HygieneProfile.HEAVY)

    assert first.digest == second.digest
    assert first.digest != heavy.digest
