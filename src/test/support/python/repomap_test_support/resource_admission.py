"""Injectable host-signal adapters and ADR 0048 profile admission decisions."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from repomap_test_support.resource_hygiene_policy import (
    GIB,
    MIN_FREE_DISK_BYTES,
    HygieneConfig,
    HygieneProfile,
)


class MemoryPressure(str, Enum):
    NORMAL = "normal"
    WARN = "warn"
    CRITICAL = "critical"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class HostSignals:
    free_disk_bytes: int
    free_disk_percent: int
    memory_pressure: MemoryPressure
    docker_responsive: bool | None
    live_mutating_runs: int
    operator_attested_exclusive: bool
    operator_attested_pressure_degradation: bool = False
    campaign_plan_id: str | None = None
    declared_complete_gates: int = 0
    buildkit_image_present: bool | None = None
    memory_free_percent: int | None = None


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    outcome: str
    reason: str
    degraded_signals: tuple[str, ...] = ()


def collect_host_signals(
    scratch_root: Path,
    *,
    profile: HygieneProfile,
    live_run_count: Callable[[], int] = lambda: 0,
    operator_attested_exclusive: bool = False,
    operator_attested_pressure_degradation: bool = False,
    campaign_plan_id: str | None = None,
    declared_complete_gates: int = 0,
) -> HostSignals:
    from test_sandbox import active_sandbox

    if active_sandbox():
        from test_sandbox_capacity import backing_space, validate_scratch_capacity

        free_bytes, free_percent = backing_space()
        validate_scratch_capacity()
    else:
        stats = os.statvfs(scratch_root)
        free_bytes = stats.f_bavail * stats.f_frsize
        total_bytes = stats.f_blocks * stats.f_frsize
        free_percent = free_bytes * 100 // total_bytes if total_bytes else 0
    pressure, memory_free_percent = read_memory_pressure_reading()
    docker = read_docker_responsive() if profile is not HygieneProfile.ORDINARY else None
    return HostSignals(
        free_bytes,
        free_percent,
        pressure,
        docker,
        live_run_count(),
        operator_attested_exclusive,
        operator_attested_pressure_degradation,
        campaign_plan_id,
        declared_complete_gates,
        memory_free_percent=memory_free_percent,
    )


def read_memory_pressure() -> MemoryPressure:
    return read_memory_pressure_reading()[0]


def read_memory_pressure_reading() -> tuple[MemoryPressure, int | None]:
    try:
        result = subprocess.run(
            ["memory_pressure", "-Q"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return read_proc_meminfo_reading()
    if result.returncode != 0:
        return read_proc_meminfo_reading()
    rendered = f"{result.stdout}\n{result.stderr}".lower()
    match = re.search(r"memory free percentage:\s*(\d{1,3})%", rendered)
    free_percent = int(match.group(1)) if match and int(match.group(1)) <= 100 else None
    if "critical" in rendered:
        return MemoryPressure.CRITICAL, free_percent
    if "warn" in rendered:
        return MemoryPressure.WARN, free_percent
    if "pressure level: normal" in rendered:
        return MemoryPressure.NORMAL, free_percent
    if free_percent is not None:
        return MemoryPressure.DEGRADED, free_percent
    return MemoryPressure.UNAVAILABLE, None


def read_proc_meminfo_reading(
    path: Path = Path("/proc/meminfo"),
) -> tuple[MemoryPressure, int | None]:
    """Report Linux memory as DEGRADED with an exact free percentage.

    ADR 0053 declines to map /proc/meminfo onto NORMAL: the reading is honest
    about free memory but carries no pressure level, so it stays behind the
    existing degradation attestation.
    """
    try:
        rendered = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return MemoryPressure.UNAVAILABLE, None
    fields: dict[str, int] = {}
    for name in ("MemTotal", "MemAvailable"):
        match = re.search(rf"^{name}:\s+(\d+)\s+kB$", rendered, re.MULTILINE)
        if match is None:
            return MemoryPressure.UNAVAILABLE, None
        fields[name] = int(match.group(1))
    if fields["MemTotal"] <= 0 or fields["MemAvailable"] > fields["MemTotal"]:
        return MemoryPressure.UNAVAILABLE, None
    free_percent = fields["MemAvailable"] * 100 // fields["MemTotal"]
    return MemoryPressure.DEGRADED, free_percent


def read_docker_responsive() -> bool:
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def decide_host_admission(
    profile: HygieneProfile,
    config: HygieneConfig,
    signals: HostSignals,
) -> AdmissionDecision:
    profile = HygieneProfile(profile)
    if (
        type(signals.free_disk_bytes) is not int
        or signals.free_disk_bytes < 0
        or type(signals.free_disk_percent) is not int
        or not 0 <= signals.free_disk_percent <= 100
        or not isinstance(signals.memory_pressure, MemoryPressure)
        or not (
            signals.docker_responsive is None
            or type(signals.docker_responsive) is bool
        )
        or type(signals.live_mutating_runs) is not int
        or signals.live_mutating_runs < 0
        or type(signals.operator_attested_exclusive) is not bool
        or type(signals.operator_attested_pressure_degradation) is not bool
        or not (
            signals.campaign_plan_id is None
            or (
                type(signals.campaign_plan_id) is str
                and re.fullmatch(r"[A-Z][A-Z0-9-]{2,127}", signals.campaign_plan_id)
            )
        )
        or type(signals.declared_complete_gates) is not int
        or not 0 <= signals.declared_complete_gates <= 2
        or not (
            signals.buildkit_image_present is None
            or type(signals.buildkit_image_present) is bool
        )
        or not (
            signals.memory_free_percent is None
            or (
                type(signals.memory_free_percent) is int
                and 0 <= signals.memory_free_percent <= 100
            )
        )
    ):
        return AdmissionDecision(False, "host_admission_refused", "invalid_host_signals")
    minimum_free = {
        HygieneProfile.ORDINARY: config.min_free_disk_bytes,
        HygieneProfile.INTEGRATION: 40 * GIB,
        HygieneProfile.BUILD: 60 * GIB,
        HygieneProfile.EXHAUSTIVE: MIN_FREE_DISK_BYTES,
        HygieneProfile.HEAVY: 100 * GIB,
        HygieneProfile.QUALIFICATION: 150 * GIB,
    }[profile]
    override = config.profile_free_disk_reserve_bytes
    if override is not None:
        if override < MIN_FREE_DISK_BYTES or override < profile.quota[0]:
            return AdmissionDecision(
                False, "host_admission_refused", "free_disk_reserve_override_invalid"
            )
        minimum_free = override
    maximum_complete_gates = {
        HygieneProfile.ORDINARY: 0,
        HygieneProfile.INTEGRATION: 0,
        HygieneProfile.BUILD: 0,
        HygieneProfile.EXHAUSTIVE: 1,
        HygieneProfile.HEAVY: 1,
        HygieneProfile.QUALIFICATION: 2,
    }[profile]
    if signals.declared_complete_gates > maximum_complete_gates:
        return AdmissionDecision(
            False, "host_admission_refused", "complete_gate_count_invalid"
        )
    if signals.free_disk_bytes < minimum_free or signals.free_disk_percent < config.min_free_disk_percent:
        return AdmissionDecision(False, "host_admission_refused", "free_disk_reserve")
    degraded: tuple[str, ...] = ()
    if signals.memory_pressure is MemoryPressure.UNAVAILABLE:
        degraded = ("memory_pressure_unavailable",)
    elif signals.memory_pressure is MemoryPressure.DEGRADED:
        degraded = ("memory_pressure_degraded",)
    if profile is HygieneProfile.ORDINARY:
        return AdmissionDecision(True, "admitted", "ordinary", degraded)
    if signals.docker_responsive is not True:
        return AdmissionDecision(False, "host_admission_refused", "docker_unresponsive", degraded)
    active_limit = 2 if profile is HygieneProfile.INTEGRATION else 1
    if signals.live_mutating_runs >= active_limit:
        return AdmissionDecision(False, "host_admission_refused", "concurrency_limit", degraded)
    if signals.memory_pressure is MemoryPressure.CRITICAL:
        return AdmissionDecision(False, "host_admission_refused", "memory_pressure_critical", degraded)
    if profile is HygieneProfile.BUILD and signals.buildkit_image_present is not True:
        return AdmissionDecision(False, "buildkit_admission_refused", "buildkit_image_absent", degraded)
    if profile in {
        HygieneProfile.EXHAUSTIVE,
        HygieneProfile.HEAVY,
        HygieneProfile.QUALIFICATION,
    }:
        if signals.memory_pressure is MemoryPressure.DEGRADED:
            if signals.memory_free_percent is None or signals.memory_free_percent == 0:
                return AdmissionDecision(
                    False,
                    "host_admission_refused",
                    "degraded_memory_percentage_invalid",
                    degraded,
                )
            if not signals.operator_attested_pressure_degradation:
                return AdmissionDecision(
                    False,
                    "host_admission_refused",
                    "pressure_degradation_attestation_missing",
                    degraded,
                )
        elif signals.memory_pressure is not MemoryPressure.NORMAL:
            return AdmissionDecision(False, "host_admission_refused", "memory_pressure_not_normal", degraded)
        if not signals.operator_attested_exclusive:
            return AdmissionDecision(False, "host_admission_refused", "exclusive_attestation_missing", degraded)
    if profile is HygieneProfile.QUALIFICATION:
        if signals.campaign_plan_id is None:
            return AdmissionDecision(
                False, "host_admission_refused", "campaign_plan_missing", degraded
            )
        if signals.declared_complete_gates not in {1, 2}:
            return AdmissionDecision(
                False, "host_admission_refused", "complete_gate_count_invalid", degraded
            )
    return AdmissionDecision(True, "admitted", profile.value, degraded)


__all__ = [
    "AdmissionDecision",
    "HostSignals",
    "MemoryPressure",
    "collect_host_signals",
    "decide_host_admission",
    "read_docker_responsive",
    "read_memory_pressure",
    "read_memory_pressure_reading",
    "read_proc_meminfo_reading",
]
