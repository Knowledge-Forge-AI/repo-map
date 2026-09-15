"""TEST-HYGIENE3A host-signal and profile-admission contracts."""

from __future__ import annotations

import pytest

from repomap_test_support.resource_admission import (
    HostSignals,
    MemoryPressure,
    decide_host_admission,
    read_memory_pressure,
    read_memory_pressure_reading,
)
from repomap_test_support.resource_hygiene_policy import GIB, HygieneConfig, HygieneProfile


def _signals(
    *,
    free_disk_bytes: int = 200 * GIB,
    free_disk_percent: int = 50,
    memory_pressure: MemoryPressure = MemoryPressure.NORMAL,
    docker_responsive: bool | None = True,
    live_mutating_runs: int = 0,
    operator_attested_exclusive: bool = False,
    operator_attested_pressure_degradation: bool = False,
    campaign_plan_id: str | None = None,
    declared_complete_gates: int = 0,
    buildkit_image_present: bool | None = True,
    memory_free_percent: int | None = 50,
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


def test_integration_requires_docker_and_refuses_critical_pressure():
    config = HygieneConfig()
    assert decide_host_admission(
        HygieneProfile.INTEGRATION,
        config,
        _signals(docker_responsive=False),
    ).admitted is False
    decision = decide_host_admission(
        HygieneProfile.INTEGRATION,
        config,
        _signals(memory_pressure=MemoryPressure.CRITICAL),
    )
    assert (decision.admitted, decision.reason) == (False, "memory_pressure_critical")


@pytest.mark.parametrize(
    ("profile", "existing"),
    [(HygieneProfile.INTEGRATION, 2), (HygieneProfile.BUILD, 1)],
)
def test_profile_concurrency_limit_includes_requesting_run(profile, existing):
    decision = decide_host_admission(
        profile,
        HygieneConfig(),
        _signals(live_mutating_runs=existing),
    )
    assert (decision.admitted, decision.reason) == (False, "concurrency_limit")


def test_unavailable_pressure_is_recorded_not_silently_normalized():
    decision = decide_host_admission(
        HygieneProfile.INTEGRATION,
        HygieneConfig(),
        _signals(memory_pressure=MemoryPressure.UNAVAILABLE),
    )
    assert decision.admitted is True
    assert decision.degraded_signals == ("memory_pressure_unavailable",)


@pytest.mark.parametrize("profile", [HygieneProfile.HEAVY, HygieneProfile.QUALIFICATION])
def test_exclusive_profiles_require_normal_pressure_and_attestation(profile):
    campaign_plan_id = "TEST-CAMPAIGN1" if profile is HygieneProfile.QUALIFICATION else None
    declared_complete_gates = 1 if profile is HygieneProfile.QUALIFICATION else 0
    decision = decide_host_admission(profile, HygieneConfig(), _signals(
        campaign_plan_id=campaign_plan_id, declared_complete_gates=declared_complete_gates,
    ))
    assert (decision.admitted, decision.reason) == (
        False,
        "exclusive_attestation_missing",
    )
    assert decide_host_admission(
        profile,
        HygieneConfig(),
        _signals(
            operator_attested_exclusive=True, campaign_plan_id=campaign_plan_id,
            declared_complete_gates=declared_complete_gates,
        ),
    ).admitted is True


@pytest.mark.parametrize(
    "changes",
    [
        {"free_disk_bytes": True},
        {"free_disk_percent": 1.5},
        {"live_mutating_runs": -1},
        {"docker_responsive": 1},
        {"operator_attested_exclusive": 0},
    ],
)
def test_malformed_host_signal_values_fail_closed(changes):
    decision = decide_host_admission(
        HygieneProfile.INTEGRATION,
        HygieneConfig(),
        _signals(**changes),
    )
    assert (decision.admitted, decision.reason) == (
        False,
        "invalid_host_signals",
    )


def test_memory_pressure_is_unavailable_only_when_both_layers_are_silent(monkeypatch):
    def unavailable(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("subprocess.run", unavailable)
    monkeypatch.setattr(
        "repomap_test_support.resource_admission.read_proc_meminfo_reading",
        lambda: (MemoryPressure.UNAVAILABLE, None),
    )

    assert read_memory_pressure() is MemoryPressure.UNAVAILABLE


def test_free_percentage_without_pressure_level_is_degraded(monkeypatch):
    class Result:
        returncode = 0
        stdout = "System-wide memory free percentage: 94%"
        stderr = ""

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Result())
    assert read_memory_pressure_reading() == (MemoryPressure.DEGRADED, 94)
