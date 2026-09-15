"""REPOMAP-CI0A ADR 0053 Linux host-admission signal and reserve override."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from repomap_test_support.resource_admission import (
    HostSignals,
    MemoryPressure,
    decide_host_admission,
    read_memory_pressure_reading,
    read_proc_meminfo_reading,
)
from repomap_test_support.resource_hygiene_policy import (
    GIB,
    HygieneConfig,
    HygieneConfigError,
    HygieneProfile,
    load_hygiene_config,
)


MEMINFO = """MemTotal:       16384000 kB
MemFree:         2048000 kB
MemAvailable:   12288000 kB
Buffers:          131072 kB
"""


def write_meminfo(tmp_path, text):
    path = tmp_path / "meminfo"
    path.write_text(text, encoding="utf-8")
    return path


def test_proc_meminfo_reports_degraded_with_exact_free_percentage(tmp_path):
    pressure, free_percent = read_proc_meminfo_reading(write_meminfo(tmp_path, MEMINFO))

    assert pressure is MemoryPressure.DEGRADED
    assert free_percent == 75


@pytest.mark.parametrize(
    "text",
    [
        "MemTotal:       16384000 kB\n",
        "MemAvailable:   12288000 kB\n",
        "MemTotal:              0 kB\nMemAvailable:          0 kB\n",
        "MemTotal:       1024 kB\nMemAvailable:   2048 kB\n",
        "MemTotal: not-a-number\nMemAvailable: 12288000 kB\n",
    ],
)
def test_unusable_meminfo_fails_closed_as_unavailable(tmp_path, text):
    assert read_proc_meminfo_reading(write_meminfo(tmp_path, text)) == (
        MemoryPressure.UNAVAILABLE,
        None,
    )


def test_absent_meminfo_is_unavailable(tmp_path):
    assert read_proc_meminfo_reading(tmp_path / "absent") == (
        MemoryPressure.UNAVAILABLE,
        None,
    )


def test_missing_macos_tool_falls_back_to_proc_meminfo(monkeypatch, tmp_path):
    def refuse(*args, **kwargs):
        raise OSError("memory_pressure is macOS-only")

    monkeypatch.setattr("subprocess.run", refuse)
    monkeypatch.setattr(
        "repomap_test_support.resource_admission.read_proc_meminfo_reading",
        lambda: read_proc_meminfo_reading(write_meminfo(tmp_path, MEMINFO)),
    )

    assert read_memory_pressure_reading() == (MemoryPressure.DEGRADED, 75)


def test_failing_macos_tool_falls_back_to_proc_meminfo(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        "repomap_test_support.resource_admission.read_proc_meminfo_reading",
        lambda: read_proc_meminfo_reading(write_meminfo(tmp_path, MEMINFO)),
    )

    assert read_memory_pressure_reading() == (MemoryPressure.DEGRADED, 75)


def hosted_runner_signals(
    *,
    free_disk_bytes: int = 45 * GIB,
    free_disk_percent: int = 60,
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


def test_hosted_runner_is_refused_without_the_reserve_override():
    decision = decide_host_admission(
        HygieneProfile.HEAVY, HygieneConfig(), hosted_runner_signals()
    )

    assert decision.admitted is False
    assert decision.reason == "free_disk_reserve"


def test_hosted_runner_is_admitted_degraded_with_the_reserve_override():
    config = HygieneConfig(profile_free_disk_reserve_bytes=40 * GIB)

    decision = decide_host_admission(
        HygieneProfile.HEAVY, config, hosted_runner_signals()
    )

    assert decision.admitted is True
    assert decision.degraded_signals == ("memory_pressure_degraded",)


def test_override_below_the_profile_quota_is_refused():
    config = HygieneConfig(profile_free_disk_reserve_bytes=31 * GIB)

    decision = decide_host_admission(
        HygieneProfile.HEAVY, config, hosted_runner_signals()
    )

    assert decision.admitted is False
    assert decision.reason == "free_disk_reserve_override_invalid"


def test_override_cannot_launder_away_the_degradation_attestation():
    config = HygieneConfig(profile_free_disk_reserve_bytes=40 * GIB)

    decision = decide_host_admission(
        HygieneProfile.HEAVY,
        config,
        hosted_runner_signals(operator_attested_pressure_degradation=False),
    )

    assert decision.admitted is False
    assert decision.reason == "pressure_degradation_attestation_missing"


def test_override_cannot_launder_away_the_exclusive_attestation():
    config = HygieneConfig(profile_free_disk_reserve_bytes=40 * GIB)

    decision = decide_host_admission(
        HygieneProfile.HEAVY,
        config,
        hosted_runner_signals(operator_attested_exclusive=False),
    )

    assert decision.admitted is False
    assert decision.reason == "exclusive_attestation_missing"


def test_override_below_the_architectural_floor_is_rejected_at_construction():
    with pytest.raises(HygieneConfigError):
        HygieneConfig(profile_free_disk_reserve_bytes=9 * GIB)


def test_unset_override_preserves_every_profile_reserve():
    for profile, insufficient, gates in (
        (HygieneProfile.INTEGRATION, 39 * GIB, 0),
        (HygieneProfile.BUILD, 59 * GIB, 0),
        (HygieneProfile.HEAVY, 99 * GIB, 1),
        (HygieneProfile.QUALIFICATION, 149 * GIB, 1),
    ):
        decision = decide_host_admission(
            profile,
            HygieneConfig(),
            hosted_runner_signals(
                free_disk_bytes=insufficient, declared_complete_gates=gates
            ),
        )

        assert decision.reason == "free_disk_reserve", profile


def test_reserve_override_loads_from_the_command_line_layer(tmp_path):
    config = load_hygiene_config(
        cli_overrides={"PROFILE_FREE_DISK_RESERVE_BYTES": 40 * GIB},
        environ={},
        local_path=tmp_path / "absent.toml",
    )

    assert config.profile_free_disk_reserve_bytes == 40 * GIB


def test_reserve_override_loads_from_the_environment_layer(tmp_path):
    config = load_hygiene_config(
        cli_overrides={},
        environ={
            "REPOMAP_TEST_HYGIENE_PROFILE_FREE_DISK_RESERVE_BYTES": str(40 * GIB)
        },
        local_path=tmp_path / "absent.toml",
    )

    assert config.profile_free_disk_reserve_bytes == 40 * GIB


def test_loader_rejects_a_reserve_override_below_the_architectural_floor(tmp_path):
    with pytest.raises(HygieneConfigError):
        load_hygiene_config(
            cli_overrides={"PROFILE_FREE_DISK_RESERVE_BYTES": 9 * GIB},
            environ={},
            local_path=tmp_path / "absent.toml",
        )


def test_reserve_override_defaults_to_absent_and_changes_the_digest(tmp_path):
    default = load_hygiene_config(
        cli_overrides={}, environ={}, local_path=tmp_path / "absent.toml"
    )

    assert default.profile_free_disk_reserve_bytes is None
    assert default.digest != HygieneConfig(
        profile_free_disk_reserve_bytes=40 * GIB
    ).digest
