"""TEST-HYGIENE3A-FIX1 degraded-pressure authority regressions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from repomap_test_support.resource_admission import (
    HostSignals,
    MemoryPressure,
    decide_host_admission,
    read_memory_pressure_reading,
)
from repomap_test_support.resource_hygiene_policy import GIB, HygieneConfig, HygieneProfile


def test_tool_free_percentage_is_explicitly_degraded(monkeypatch):
    result = SimpleNamespace(
        returncode=0,
        stdout="System-wide memory free percentage: 94%",
        stderr="",
    )
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: result)

    pressure, free_percent = read_memory_pressure_reading()

    assert pressure is MemoryPressure.DEGRADED
    assert free_percent == 94


def test_degraded_qualification_requires_separate_attestation():
    signals = HostSignals(
        free_disk_bytes=200 * GIB,
        free_disk_percent=50,
        memory_pressure=MemoryPressure.DEGRADED,
        docker_responsive=True,
        live_mutating_runs=0,
        operator_attested_exclusive=True,
        campaign_plan_id="TEST-CAMPAIGN1",
        declared_complete_gates=1,
        memory_free_percent=94,
    )

    decision = decide_host_admission(
        HygieneProfile.QUALIFICATION,
        HygieneConfig(),
        signals,
    )

    assert decision.reason == "pressure_degradation_attestation_missing"


def test_attested_degraded_qualification_preserves_degraded_state():
    signals = HostSignals(
        free_disk_bytes=200 * GIB,
        free_disk_percent=50,
        memory_pressure=MemoryPressure.DEGRADED,
        docker_responsive=True,
        live_mutating_runs=0,
        operator_attested_exclusive=True,
        operator_attested_pressure_degradation=True,
        campaign_plan_id="TEST-CAMPAIGN1",
        declared_complete_gates=1,
        memory_free_percent=94,
    )

    decision = decide_host_admission(
        HygieneProfile.QUALIFICATION,
        HygieneConfig(),
        signals,
    )

    assert decision.admitted is True
    assert decision.degraded_signals == ("memory_pressure_degraded",)


def test_zero_degraded_free_percentage_fails_closed():
    signals = HostSignals(
        free_disk_bytes=200 * GIB,
        free_disk_percent=50,
        memory_pressure=MemoryPressure.DEGRADED,
        docker_responsive=True,
        live_mutating_runs=0,
        operator_attested_exclusive=True,
        operator_attested_pressure_degradation=True,
        campaign_plan_id="TEST-CAMPAIGN1",
        declared_complete_gates=1,
        memory_free_percent=0,
    )

    decision = decide_host_admission(
        HygieneProfile.QUALIFICATION,
        HygieneConfig(),
        signals,
    )

    assert decision.reason == "degraded_memory_percentage_invalid"


def test_integration_records_degraded_pressure_without_attestation():
    signals = HostSignals(
        free_disk_bytes=100 * GIB,
        free_disk_percent=50,
        memory_pressure=MemoryPressure.DEGRADED,
        docker_responsive=True,
        live_mutating_runs=0,
        operator_attested_exclusive=False,
        memory_free_percent=75,
    )

    decision = decide_host_admission(
        HygieneProfile.INTEGRATION,
        HygieneConfig(),
        signals,
    )

    assert decision.admitted is True
    assert decision.degraded_signals == ("memory_pressure_degraded",)


@pytest.mark.parametrize(
    ("profile", "declared"),
    [
        (HygieneProfile.ORDINARY, 1),
        (HygieneProfile.INTEGRATION, 1),
        (HygieneProfile.BUILD, 1),
        (HygieneProfile.HEAVY, 2),
    ],
)
def test_direct_host_admission_enforces_profile_gate_maximum(profile, declared):
    signals = HostSignals(
        free_disk_bytes=200 * GIB,
        free_disk_percent=50,
        memory_pressure=MemoryPressure.NORMAL,
        docker_responsive=True,
        live_mutating_runs=0,
        operator_attested_exclusive=True,
        declared_complete_gates=declared,
        buildkit_image_present=True,
    )

    decision = decide_host_admission(profile, HygieneConfig(), signals)

    assert decision.admitted is False
    assert decision.reason == "complete_gate_count_invalid"
