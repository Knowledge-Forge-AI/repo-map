#!/usr/bin/env python3
"""Run public-safe SCALE18 digest memory and repeatability campaigns."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
for import_root in (
    REPO_ROOT / "src" / "main" / "python",
    REPO_ROOT / "src" / "test" / "support" / "python",
):
    import_root_text = str(import_root)
    if import_root_text not in sys.path:
        sys.path.insert(0, import_root_text)

from process_rss_monitor import ProcessRssMonitor
from repomap_kg.graph.discovery import discover_observations
from repomap_kg.ops.generations import source_generation
from repomap_test_support.scale18_digest_campaign import (
    SCALE18_PROFILES,
    build_scale18_workload,
    derive_scale18_observations,
    derive_scale18_workload,
)
from scale12_resource_sampling import read_process_rss_bytes
from scale20_prelaunch_handoff import (
    PrelaunchHandoffError,
    decode_ordered_family_worker_payload,
    encode_ordered_family_worker_payload,
)
import scale18_digest_reporting as _reporting
from scale18_digest_reporting import (
    _DERIVATION_TIMEOUT_SECONDS,
    _RSS_CADENCE_SECONDS,
    _RSS_READER_LOSS_LIMIT,
    _TERMINATION_GRACE_SECONDS,
    Scale18CampaignError,
    _GuardedRssReader,
    _WorkerResourcePolicy,
    _WorkerTermination,
    doubling_comparisons as _doubling_comparisons,
    required_total_sampled_rss as _required_total_sampled_rss,
    run_profile_campaign as _run_profile_campaign,
    run_repository_repeats as _run_repository_repeats,
)

_ARTIFACT_HARD_LIMIT_BYTES = _reporting._ARTIFACT_HARD_LIMIT_BYTES
_CI_SAFE_ARTIFACT_HARD_LIMIT_BYTES = _reporting._CI_SAFE_ARTIFACT_HARD_LIMIT_BYTES
_CI_SAFE_FREE_SPACE_HARD_LIMIT_BYTES = _reporting._CI_SAFE_FREE_SPACE_HARD_LIMIT_BYTES
_CI_SAFE_MAX_PROFILE_SIZE = _reporting._CI_SAFE_MAX_PROFILE_SIZE
_FREE_SPACE_HARD_LIMIT_BYTES = _reporting._FREE_SPACE_HARD_LIMIT_BYTES
_HEADROOM_TARGET_BYTES = _reporting._HEADROOM_TARGET_BYTES
_INCREMENTAL_DIGEST_TARGET_BYTES = _reporting._INCREMENTAL_DIGEST_TARGET_BYTES
_RSS_HARD_LIMIT_BYTES = _reporting._RSS_HARD_LIMIT_BYTES
_RSS_TARGET_BYTES = _reporting._RSS_TARGET_BYTES
_required_int = _reporting.required_int


def _target_acceptance(payload: dict[str, object]) -> bool:
    """Return whether a case meets the memory and headroom targets."""

    maximum = _required_total_sampled_rss(payload)
    incremental = _required_int(
        payload,
        "conservative_incremental_digest_rss_bytes",
    )
    return (
        maximum <= _RSS_TARGET_BYTES
        and incremental <= _INCREMENTAL_DIGEST_TARGET_BYTES
        and _RSS_HARD_LIMIT_BYTES - maximum >= _HEADROOM_TARGET_BYTES
    )


def _attach_process_rss_evidence(
    payload: dict[str, object],
    rss_payload: dict[str, object],
) -> None:
    parent_maximum = _required_int(rss_payload, "maximum_observed_bytes")
    digest_maximum = _required_int(
        payload,
        "digest_sampled_maximum_rss_bytes",
    )
    total_maximum = max(parent_maximum, digest_maximum)
    pre_digest = _required_int(payload, "pre_digest_rss_bytes")
    encoder_increment = _required_int(payload, "incremental_digest_rss_bytes")
    payload["process_rss"] = rss_payload
    payload["total_sampled_maximum_rss_bytes"] = total_maximum
    payload["conservative_incremental_digest_rss_bytes"] = max(
        encoder_increment,
        max(0, total_maximum - pre_digest),
    )









def run_profile_campaign() -> dict[str, object]:
    """Run all seven profiles and five bands sequentially."""

    return _run_profile_campaign(
        run_worker=_run_worker,
        require_free_space=_require_free_space,
        require_case_limits=_require_case_limits,
        target_acceptance=_target_acceptance,
        doubling_comparisons=_doubling_comparisons,
    )


def run_repository_repeats(root: Path, label: str) -> dict[str, object]:
    """Run two unchanged static derivations of one caller-verified root."""

    return _run_repository_repeats(
        root,
        label,
        run_worker=_run_worker,
        require_free_space=_require_free_space,
        require_case_limits=_require_case_limits,
    )


def _run_worker(
    arguments: Sequence[str],
    *,
    policy: _WorkerResourcePolicy,
) -> dict[str, object]:
    if not isinstance(policy, _WorkerResourcePolicy):
        raise Scale18CampaignError("worker resource policy is invalid")
    if any(
        argument == "--resource-policy"
        or argument.startswith("--resource-policy=")
        for argument in arguments
    ):
        raise Scale18CampaignError("worker launcher injects resource policy")
    if not arguments or arguments[0] not in {
        "_worker-profile",
        "_worker-repository",
    }:
        raise Scale18CampaignError("campaign worker command is invalid")
    _require_free_space(policy)
    worker_arguments = (
        arguments[0],
        "--resource-policy",
        policy.value,
        *arguments[1:],
    )
    environment = dict(os.environ)
    python_paths = (
        REPO_ROOT / "src" / "main" / "python",
        REPO_ROOT / "src" / "test" / "support" / "python",
        REPO_ROOT / "tools",
    )
    inherited_pythonpath = environment.get("PYTHONPATH")
    pythonpath_entries = [*map(str, python_paths)]
    if inherited_pythonpath:
        pythonpath_entries.extend(inherited_pythonpath.split(os.pathsep))
    environment["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    process = subprocess.Popen(
        (sys.executable, str(Path(__file__).resolve()), *worker_arguments),
        cwd=REPO_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    termination = _WorkerTermination(
        process,
        clock=time.monotonic,
        grace_seconds=_TERMINATION_GRACE_SECONDS,
    )
    reader = _GuardedRssReader(
        process,
        termination,
        reader=lambda: read_process_rss_bytes(process.pid),
        clock=time.monotonic,
        duration_limit_seconds=_DERIVATION_TIMEOUT_SECONDS,
        reader_loss_limit=_RSS_READER_LOSS_LIMIT,
    )

    def signal() -> None:
        termination.request("rss_hard_limit")

    try:
        rss_result = ProcessRssMonitor(
            limit_bytes=policy.rss_limit_bytes,
            cadence_seconds=_RSS_CADENCE_SECONDS,
            reader=reader,
            signal=signal,
        ).run(process)
        stdout, stderr = process.communicate(timeout=10.0)
    except BaseException:
        _terminate_and_reap(process)
        raise
    if termination.reason is not None:
        raise Scale18CampaignError(
            f"campaign worker reached {termination.reason}"
        )
    if process.returncode != 0:
        category = "worker_failed" if stderr else "worker_failed_without_diagnostic"
        raise Scale18CampaignError(category)
    if len(stdout.encode("utf-8")) > 64 * 1024:
        raise Scale18CampaignError("campaign worker output is unbounded")
    try:
        payload = decode_ordered_family_worker_payload(stdout)
    except PrelaunchHandoffError as error:
        raise Scale18CampaignError("campaign worker output is invalid") from error
    _attach_process_rss_evidence(payload, rss_result.to_payload())
    return payload


def _worker_profile(
    profile: str,
    size: int,
    policy: _WorkerResourcePolicy,
) -> dict[str, object]:
    maximum_size = policy.maximum_profile_size
    if maximum_size is not None and size > maximum_size:
        raise Scale18CampaignError("profile size exceeds resource policy")
    process_baseline = _current_process_rss()
    workload = build_scale18_workload(profile, size)
    result = derive_scale18_workload(
        workload,
        rss_reader=lambda: read_process_rss_bytes(os.getpid()),
        artifact_limit_bytes=policy.artifact_limit_bytes,
        free_space_reader=lambda: shutil.disk_usage(
            tempfile.gettempdir()
        ).free,
        free_space_floor_bytes=policy.free_space_floor_bytes,
    )
    payload = result.to_payload()
    payload["process_baseline_rss_bytes"] = process_baseline
    return payload


def _worker_repository(
    root: Path,
    label: str,
    policy: _WorkerResourcePolicy,
) -> dict[str, object]:
    if label not in {"self_dogfood", "explicit_public_repository"}:
        raise Scale18CampaignError("repository source category is invalid")
    process_baseline = _current_process_rss()
    observations = tuple(discover_observations(root))
    generation = source_generation(observations)
    observation_stream = iter(observations)
    del observations
    result = derive_scale18_observations(
        profile=label,
        work_items=0,
        observations=observation_stream,
        rss_reader=lambda: read_process_rss_bytes(os.getpid()),
        artifact_limit_bytes=policy.artifact_limit_bytes,
        free_space_reader=lambda: shutil.disk_usage(
            tempfile.gettempdir()
        ).free,
        free_space_floor_bytes=policy.free_space_floor_bytes,
    )
    payload = result.to_payload()
    payload["process_baseline_rss_bytes"] = process_baseline
    payload["work_items"] = result.family_counts["files"]
    payload["source_generation"] = generation
    return payload


def _require_free_space(policy: _WorkerResourcePolicy) -> None:
    if shutil.disk_usage(tempfile.gettempdir()).free <= policy.free_space_floor_bytes:
        raise Scale18CampaignError("campaign free-space hard stop reached")


def _require_case_limits(
    payload: dict[str, object],
    policy: _WorkerResourcePolicy,
) -> None:
    maximum = _required_total_sampled_rss(payload)
    if maximum >= policy.rss_limit_bytes:
        raise Scale18CampaignError("campaign RSS hard stop reached")
    artifact_bytes = payload.get("temporary_artifact_peak_bytes")
    if (
        not isinstance(artifact_bytes, int)
        or artifact_bytes >= policy.artifact_limit_bytes
    ):
        raise Scale18CampaignError("campaign artifact hard stop reached")

def _current_process_rss() -> int:
    rss_bytes = read_process_rss_bytes(os.getpid())
    if (
        isinstance(rss_bytes, bool)
        or not isinstance(rss_bytes, int)
        or rss_bytes < 0
    ):
        raise Scale18CampaignError(
            "campaign process baseline RSS is unavailable"
        )
    return rss_bytes








def _terminate_and_reap(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        process.communicate(timeout=_TERMINATION_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=_TERMINATION_GRACE_SECONDS)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("profile-campaign")
    repository = subparsers.add_parser("repository-repeat")
    repository.add_argument("--root", type=Path, required=True)
    repository.add_argument(
        "--label",
        choices=("self_dogfood", "explicit_public_repository"),
        required=True,
    )
    worker_profile = subparsers.add_parser("_worker-profile")
    worker_profile.add_argument(
        "--resource-policy",
        choices=tuple(policy.value for policy in _WorkerResourcePolicy),
        required=True,
    )
    worker_profile.add_argument("--profile", choices=SCALE18_PROFILES, required=True)
    worker_profile.add_argument("--size", type=int, required=True)
    worker_repository = subparsers.add_parser("_worker-repository")
    worker_repository.add_argument(
        "--resource-policy",
        choices=tuple(policy.value for policy in _WorkerResourcePolicy),
        required=True,
    )
    worker_repository.add_argument("--root", type=Path, required=True)
    worker_repository.add_argument("--label", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one campaign command and emit one bounded JSON object."""

    arguments = _parser().parse_args(argv)
    if arguments.command == "profile-campaign":
        payload = run_profile_campaign()
    elif arguments.command == "repository-repeat":
        payload = run_repository_repeats(arguments.root, arguments.label)
    elif arguments.command == "_worker-profile":
        payload = _worker_profile(
            arguments.profile,
            arguments.size,
            _WorkerResourcePolicy(arguments.resource_policy),
        )
    else:
        payload = _worker_repository(
            arguments.root,
            arguments.label,
            _WorkerResourcePolicy(arguments.resource_policy),
        )
    if arguments.command.startswith("_worker-"):
        print(encode_ordered_family_worker_payload(payload))
    else:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
