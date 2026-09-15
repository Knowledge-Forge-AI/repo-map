from __future__ import annotations

import os
import subprocess
import sys
import time
from types import SimpleNamespace
from typing import cast

import pytest

from process_rss_monitor import ProcessRssMonitor
import scale18_digest_campaign as campaign
from scale18_digest_campaign import (
    _GuardedRssReader,
    _WorkerTermination,
    _attach_process_rss_evidence,
)

def _campaign_case(
    profile: str, work_items: int, *, maximum: int, baseline: int,
    increment: int, process_baseline: int = 80,
) -> dict[str, object]:
    return {
        "profile": profile, "work_items": work_items,
        "pre_digest_rss_bytes": baseline,
        "digest_sampled_maximum_rss_bytes": baseline + increment,
        "incremental_digest_rss_bytes": increment,
        "process_baseline_rss_bytes": process_baseline,
        "conservative_incremental_digest_rss_bytes": max(increment, maximum - baseline),
        "process_rss": {"maximum_observed_bytes": maximum},
        "total_sampled_maximum_rss_bytes": max(maximum, baseline + increment),
    }

class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

class _Process:
    def __init__(self, *, ignore_terminate: bool = False) -> None:
        self.returncode: int | None = None
        self.ignore_terminate = ignore_terminate
        self.terminate_count = 0
        self.kill_count = 0

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminate_count += 1
        if not self.ignore_terminate:
            self.returncode = -15

    def kill(self) -> None:
        self.kill_count += 1
        self.returncode = -9

def test_derivation_duration_rejects_exact_ceiling() -> None:
    clock = _Clock()
    process = _Process()
    termination = _WorkerTermination(
        process,
        clock=clock,
        grace_seconds=0.2,
    )
    guarded = _GuardedRssReader(
        process,
        termination,
        reader=lambda: 100,
        clock=clock,
        duration_limit_seconds=60.0,
        reader_loss_limit=3,
    )

    clock.value = 60.0
    guarded()

    assert termination.reason == "derivation_duration_limit"
    assert process.terminate_count == 1

def test_internal_higher_sample_controls_total_and_hard_limit() -> None:
    payload: dict[str, object] = {
        "pre_digest_rss_bytes": 100,
        "digest_sampled_maximum_rss_bytes": campaign._RSS_HARD_LIMIT_BYTES,
        "incremental_digest_rss_bytes": 200,
        "temporary_artifact_peak_bytes": 0,
    }
    rss_payload: dict[str, object] = {
        "maximum_observed_bytes": campaign._RSS_HARD_LIMIT_BYTES - 1,
    }

    _attach_process_rss_evidence(payload, rss_payload)

    assert payload["process_rss"] == rss_payload
    assert (
        payload["total_sampled_maximum_rss_bytes"]
        == campaign._RSS_HARD_LIMIT_BYTES
    )
    with pytest.raises(campaign.Scale18CampaignError, match="RSS hard stop"):
        campaign._require_case_limits(
            payload,
            campaign._WorkerResourcePolicy.FULL_CAMPAIGN,
        )

def test_parent_rejects_non_policy_object() -> None:
    with pytest.raises(campaign.Scale18CampaignError, match="policy is invalid"):
        campaign._run_worker(
            ("_worker-profile", "--profile", "mixed", "--size", "512"),
            policy=cast(campaign._WorkerResourcePolicy, "ci_safe_qualification"),
        )

@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX signal escalation proof",
)
def test_owned_worker_that_ignores_terminate_is_killed_and_reaped() -> None:
    process = subprocess.Popen(
        (
            sys.executable,
            "-c",
            "import signal,time; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "print('ready', flush=True); time.sleep(60)",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    termination = _WorkerTermination(
        process,
        clock=time.monotonic,
        grace_seconds=0.05,
    )
    reader = _GuardedRssReader(
        process,
        termination,
        reader=lambda: 200,
        clock=time.monotonic,
        duration_limit_seconds=60.0,
        reader_loss_limit=3,
    )
    try:
        result = ProcessRssMonitor(
            limit_bytes=100,
            cadence_seconds=0.01,
            reader=reader,
            signal=lambda: termination.request("rss_hard_limit"),
        ).run(process)
        returncode = process.wait(timeout=2.0)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2.0)

    assert termination.reason == "rss_hard_limit"
    assert returncode < 0
    assert result.process_exited is True

@pytest.mark.parametrize(
    ("policy", "free_bytes", "accepted"),
    (
        (
            campaign._WorkerResourcePolicy.FULL_CAMPAIGN,
            campaign._FREE_SPACE_HARD_LIMIT_BYTES - 1,
            False,
        ),
        (
            campaign._WorkerResourcePolicy.FULL_CAMPAIGN,
            campaign._FREE_SPACE_HARD_LIMIT_BYTES,
            False,
        ),
        (
            campaign._WorkerResourcePolicy.FULL_CAMPAIGN,
            campaign._FREE_SPACE_HARD_LIMIT_BYTES + 1,
            True,
        ),
        (
            campaign._WorkerResourcePolicy.CI_SAFE_QUALIFICATION,
            campaign._CI_SAFE_FREE_SPACE_HARD_LIMIT_BYTES - 1,
            False,
        ),
        (
            campaign._WorkerResourcePolicy.CI_SAFE_QUALIFICATION,
            campaign._CI_SAFE_FREE_SPACE_HARD_LIMIT_BYTES,
            False,
        ),
        (
            campaign._WorkerResourcePolicy.CI_SAFE_QUALIFICATION,
            campaign._CI_SAFE_FREE_SPACE_HARD_LIMIT_BYTES + 1,
            True,
        ),
    ),
)
def test_worker_policy_preflight_has_strict_free_space_boundary(
    policy,
    free_bytes,
    accepted,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        campaign.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=free_bytes),
    )

    if accepted:
        campaign._require_free_space(policy)
    else:
        with pytest.raises(campaign.Scale18CampaignError, match="free-space"):
            campaign._require_free_space(policy)

def test_full_policy_rejects_small_worker_route_at_fifteen_gib(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        campaign.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=15 * 1024**3),
    )
    monkeypatch.setattr(
        campaign.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("worker must not launch"),
    )

    with pytest.raises(campaign.Scale18CampaignError, match="free-space"):
        campaign._run_worker(
            ("_worker-profile", "--profile", "mixed", "--size", "512"),
            policy=campaign._WorkerResourcePolicy.FULL_CAMPAIGN,
        )

@pytest.mark.parametrize(
    "free_bytes",
    (
        campaign._CI_SAFE_FREE_SPACE_HARD_LIMIT_BYTES - 1,
        campaign._CI_SAFE_FREE_SPACE_HARD_LIMIT_BYTES,
    ),
)
def test_ci_safe_worker_route_refuses_at_or_below_its_floor(
    free_bytes,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        campaign.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=free_bytes),
    )
    monkeypatch.setattr(
        campaign.subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("worker must not launch"),
    )

    with pytest.raises(campaign.Scale18CampaignError, match="free-space"):
        campaign._run_worker(
            ("_worker-profile", "--profile", "mixed", "--size", "512"),
            policy=campaign._WorkerResourcePolicy.CI_SAFE_QUALIFICATION,
        )

def test_ci_safe_worker_refuses_profile_above_explicit_band_ceiling(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        campaign,
        "build_scale18_workload",
        lambda *_args: pytest.fail("oversized workload must not be built"),
    )

    with pytest.raises(
        campaign.Scale18CampaignError,
        match="profile size exceeds resource policy",
    ):
        campaign._worker_profile(
            "mixed",
            campaign._CI_SAFE_MAX_PROFILE_SIZE * 2,
            campaign._WorkerResourcePolicy.CI_SAFE_QUALIFICATION,
        )

@pytest.mark.parametrize(
    "policy",
    tuple(campaign._WorkerResourcePolicy),
)
def test_case_limit_rejects_selected_artifact_ceiling(policy) -> None:
    payload = _campaign_case(
        "mixed",
        512,
        maximum=100,
        baseline=80,
        increment=10,
    )
    payload["temporary_artifact_peak_bytes"] = policy.artifact_limit_bytes

    with pytest.raises(campaign.Scale18CampaignError, match="artifact hard stop"):
        campaign._require_case_limits(payload, policy)

@pytest.mark.parametrize(
    "argv",
    (
        ("profile-campaign", "--resource-policy", "ci_safe_qualification"),
        (
            "repository-repeat",
            "--root",
            "public-repository",
            "--label",
            "explicit_public_repository",
            "--resource-policy",
            "ci_safe_qualification",
        ),
    ),
)
def test_public_campaign_commands_cannot_select_worker_policy(argv) -> None:
    with pytest.raises(SystemExit):
        campaign._parser().parse_args(argv)

def test_private_worker_rejects_unknown_policy_identity() -> None:
    with pytest.raises(SystemExit):
        campaign._parser().parse_args(
            (
                "_worker-profile",
                "--resource-policy",
                "arbitrary",
                "--profile",
                "mixed",
                "--size",
                "512",
            )
        )

def test_worker_launcher_rejects_embedded_resource_policy() -> None:
    with pytest.raises(campaign.Scale18CampaignError, match="launcher injects"):
        campaign._run_worker(
            (
                "_worker-profile",
                "--resource-policy=ci_safe_qualification",
                "--profile",
                "mixed",
                "--size",
                "512",
            ),
            policy=campaign._WorkerResourcePolicy.FULL_CAMPAIGN,
        )

def test_doubling_exception_rejects_workload_linear_baseline() -> None:
    comparison = campaign._doubling_comparisons(
        (
            _campaign_case(
                "mixed",
                4_096,
                maximum=100,
                baseline=80,
                increment=10,
            ),
            _campaign_case(
                "mixed",
                8_192,
                maximum=1_000,
                baseline=800,
                increment=15,
                process_baseline=800,
            ),
        ),
        profiles=("mixed",),
        bands=(4_096, 8_192),
    )[0]

    assert comparison["fixed_baseline_dominates"] is True
    assert comparison["baseline_stable"] is False
    assert comparison["fixed_baseline_exception"] is False
    assert comparison["accepted"] is False

