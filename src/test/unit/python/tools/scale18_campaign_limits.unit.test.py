from __future__ import annotations

from types import SimpleNamespace

import pytest

from scale15_terminal_contracts import FINAL_FAMILY_CODES
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

def _disk_space_worker_wrapper(tmp_path_factory, free_bytes: int):
    wrapper = tmp_path_factory.mktemp("scale18-worker-wrapper") / "worker.py"
    wrapper.write_text(
        "\n".join(
            (
                "from types import SimpleNamespace",
                "import scale18_digest_campaign as campaign",
                "campaign.shutil.disk_usage = (",
                f"    lambda _path: SimpleNamespace(free={free_bytes})",
                ")",
                "raise SystemExit(campaign.main())",
                "",
            )
        ),
        encoding="utf-8",
    )
    return wrapper

def test_worker_termination_escalates_once_after_a_bounded_grace() -> None:
    clock = _Clock()
    process = _Process(ignore_terminate=True)
    termination = _WorkerTermination(
        process,
        clock=clock,
        grace_seconds=0.2,
    )

    termination.request("rss_hard_limit")
    termination.request("derivation_duration_limit")
    clock.value = 0.19
    termination.enforce()
    assert process.terminate_count == 1
    assert process.kill_count == 0
    assert termination.reason == "rss_hard_limit"

    clock.value = 0.2
    termination.enforce()
    termination.enforce()
    assert process.kill_count == 1
    assert process.poll() == -9

def test_worker_termination_retains_reason_when_child_already_exited() -> None:
    clock = _Clock()
    process = _Process()
    process.returncode = 0
    termination = _WorkerTermination(
        process,
        clock=clock,
        grace_seconds=0.2,
    )

    termination.request("rss_hard_limit")

    assert termination.reason == "rss_hard_limit"
    assert process.terminate_count == 0
    assert process.kill_count == 0

def test_persistent_live_rss_reader_loss_terminates_and_escalates() -> None:
    clock = _Clock()
    process = _Process(ignore_terminate=True)
    termination = _WorkerTermination(
        process,
        clock=clock,
        grace_seconds=0.2,
    )
    guarded = _GuardedRssReader(
        process,
        termination,
        reader=lambda: None,
        clock=clock,
        duration_limit_seconds=60.0,
        reader_loss_limit=3,
    )

    assert guarded() is None
    assert guarded() is None
    assert guarded() is None
    assert termination.reason == "rss_reader_unavailable"
    assert process.terminate_count == 1

    clock.value = 0.2
    assert guarded() is None
    assert process.kill_count == 1

def test_parent_samples_make_incremental_rss_conservative() -> None:
    payload: dict[str, object] = {
        "pre_digest_rss_bytes": 100,
        "digest_sampled_maximum_rss_bytes": 120,
        "incremental_digest_rss_bytes": 20,
    }
    rss_payload: dict[str, object] = {
        "maximum_observed_bytes": 180,
    }

    _attach_process_rss_evidence(payload, rss_payload)

    assert payload["process_rss"] == rss_payload
    assert payload["total_sampled_maximum_rss_bytes"] == 180
    assert payload["conservative_incremental_digest_rss_bytes"] == 80

@pytest.mark.parametrize(
    "arguments",
    (
        ("_worker-profile", "--profile", "mixed", "--size", "512"),
        (
            "_worker-repository",
            "--root",
            "public-go-fixture",
            "--label",
            "explicit_public_repository",
        ),
    ),
)
def test_ci_safe_policy_crosses_small_worker_boundary_below_twenty_gib(
    arguments,
    monkeypatch,
) -> None:
    launched = ()

    def launch(command, **_kwargs):
        nonlocal launched
        launched = command
        raise RuntimeError("launch captured")

    monkeypatch.setattr(
        campaign.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=15 * 1024**3),
    )
    monkeypatch.setattr(campaign.subprocess, "Popen", launch)

    with pytest.raises(RuntimeError, match="launch captured"):
        campaign._run_worker(
            arguments,
            policy=campaign._WorkerResourcePolicy.CI_SAFE_QUALIFICATION,
        )

    policy_index = launched.index("--resource-policy")
    assert launched[policy_index + 1] == "ci_safe_qualification"

def test_worker_resource_policy_records_all_dimensions() -> None:
    full = campaign._WorkerResourcePolicy.FULL_CAMPAIGN
    ci_safe = campaign._WorkerResourcePolicy.CI_SAFE_QUALIFICATION

    assert full.rss_limit_bytes == 6 * 1024**3
    assert ci_safe.rss_limit_bytes == full.rss_limit_bytes
    assert full.maximum_profile_size is None
    assert ci_safe.maximum_profile_size == 2_048

@pytest.mark.parametrize(
    "policy",
    tuple(campaign._WorkerResourcePolicy),
)
def test_profile_worker_enforces_selected_policy(
    policy,
    monkeypatch,
) -> None:
    captured = {}

    def derive(_workload, **kwargs):
        captured.update(kwargs)
        raise RuntimeError("limits captured")

    monkeypatch.setattr(campaign, "_current_process_rss", lambda: 1)
    monkeypatch.setattr(campaign, "build_scale18_workload", lambda *_args: object())
    monkeypatch.setattr(campaign, "derive_scale18_workload", derive)

    with pytest.raises(RuntimeError, match="limits captured"):
        campaign._worker_profile("mixed", 512, policy)

    assert captured["artifact_limit_bytes"] == policy.artifact_limit_bytes
    assert captured["free_space_floor_bytes"] == policy.free_space_floor_bytes

@pytest.mark.parametrize(
    "policy",
    tuple(campaign._WorkerResourcePolicy),
)
def test_repository_worker_enforces_selected_policy(
    policy,
    monkeypatch,
) -> None:
    captured = {}

    def derive(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("limits captured")

    monkeypatch.setattr(campaign, "_current_process_rss", lambda: 1)
    monkeypatch.setattr(campaign, "discover_observations", lambda _root: ())
    monkeypatch.setattr(campaign, "source_generation", lambda _observations: "sg1")
    monkeypatch.setattr(campaign, "derive_scale18_observations", derive)

    with pytest.raises(RuntimeError, match="limits captured"):
        campaign._worker_repository(
            campaign.Path("public-go-fixture"),
            "explicit_public_repository",
            policy,
        )

    assert captured["artifact_limit_bytes"] == policy.artifact_limit_bytes
    assert captured["free_space_floor_bytes"] == policy.free_space_floor_bytes

def test_top_band_doubling_comparison_accepts_direct_rss_target() -> None:
    comparisons = campaign._doubling_comparisons(
        (
            _campaign_case("mixed", 4_096, maximum=100, baseline=80, increment=10),
            _campaign_case("mixed", 8_192, maximum=125, baseline=80, increment=15),
        ),
        profiles=("mixed",),
        bands=(4_096, 8_192),
    )

    assert comparisons[0]["total_rss_growth_percent"] == 25.0
    assert comparisons[0]["direct_target_met"] is True
    assert comparisons[0]["accepted"] is True

def test_top_band_doubling_exception_requires_stable_digest_working_set() -> None:
    accepted = campaign._doubling_comparisons(
        (
            _campaign_case("mixed", 4_096, maximum=150, baseline=100, increment=10),
            _campaign_case("mixed", 8_192, maximum=190, baseline=100, increment=15),
        ),
        profiles=("mixed",),
        bands=(4_096, 8_192),
    )[0]
    rejected = campaign._doubling_comparisons(
        (
            _campaign_case("mixed", 4_096, maximum=150, baseline=100, increment=10),
            _campaign_case("mixed", 8_192, maximum=200, baseline=100, increment=50),
        ),
        profiles=("mixed",),
        bands=(4_096, 8_192),
    )[0]

    assert accepted["fixed_baseline_exception"] is True
    assert accepted["digest_phase_working_set_target_met"] is True
    assert accepted["accepted"] is True
    assert rejected["digest_phase_working_set_target_met"] is False
    assert rejected["accepted"] is False

def test_doubling_target_uses_unrounded_growth_ratio() -> None:
    comparison = campaign._doubling_comparisons(
        (
            _campaign_case(
                "mixed",
                4_096,
                maximum=10_000,
                baseline=100,
                increment=10,
            ),
            _campaign_case(
                "mixed",
                8_192,
                maximum=12_504,
                baseline=100,
                increment=20,
                process_baseline=800,
            ),
        ),
        profiles=("mixed",),
        bands=(4_096, 8_192),
    )[0]

    assert comparison["total_rss_growth_percent"] == 25.0
    assert comparison["direct_target_met"] is False
    assert comparison["accepted"] is False

def test_largest_band_target_accepts_exact_readiness_boundaries() -> None:
    payload = {
        "pre_digest_rss_bytes": campaign._RSS_TARGET_BYTES,
        "incremental_digest_rss_bytes": 0,
        "conservative_incremental_digest_rss_bytes": (
            campaign._INCREMENTAL_DIGEST_TARGET_BYTES
        ),
        "process_rss": {
            "maximum_observed_bytes": campaign._RSS_TARGET_BYTES
        },
        "total_sampled_maximum_rss_bytes": campaign._RSS_TARGET_BYTES,
    }

    assert campaign._target_acceptance(payload) is True

def test_ci_safe_digest_subprocess_doubling_is_bounded_and_cleans(
    tmp_path,
    tmp_path_factory,
    monkeypatch,
) -> None:
    policy = campaign._WorkerResourcePolicy.CI_SAFE_QUALIFICATION
    simulated_free_bytes = 15 * 1024**3
    worker = _disk_space_worker_wrapper(tmp_path_factory, simulated_free_bytes)
    assert tmp_path not in worker.parents
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(campaign, "__file__", str(worker))
    monkeypatch.setattr(
        campaign.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=simulated_free_bytes),
    )
    before = set(tmp_path.iterdir())

    lower = campaign._run_worker(
        ("_worker-profile", "--profile", "mixed", "--size", "512"),
        policy=policy,
    )
    upper = campaign._run_worker(
        ("_worker-profile", "--profile", "mixed", "--size", "1024"),
        policy=policy,
    )
    comparison = campaign._doubling_comparisons(
        (lower, upper),
        profiles=("mixed",),
        bands=(512, 1024),
    )[0]
    after = set(tmp_path.iterdir())

    for payload in (lower, upper):
        campaign._require_case_limits(payload, policy)
        family_counts = payload["family_counts"]
        assert isinstance(family_counts, dict)
        assert tuple(family_counts) == FINAL_FAMILY_CODES
        assert campaign._required_total_sampled_rss(payload) < 512 * 1024**2
        assert (
            campaign._required_int(
                payload,
                "conservative_incremental_digest_rss_bytes",
            )
            < 256 * 1024**2
        )
        assert (
            campaign._required_int(
                payload,
                "temporary_artifact_peak_bytes",
            )
            < 64 * 1024**2
        )
    assert comparison["accepted"] is True
    assert before == after

