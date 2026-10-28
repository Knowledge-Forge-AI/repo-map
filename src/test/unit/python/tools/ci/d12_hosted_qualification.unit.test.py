"""Unit tests for hosted native D12 prepare, seal, and early system-hold seam."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[6]
for _rel in ("", "src/main/python", "tools", "src/test/support/python"):
    _p = str((REPO_ROOT / _rel).resolve())
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ci.d12_hosted_evidence import (
    EXPECTED_SDK_IMAGE_TAG, SEALED_EVIDENCE_SCHEMA, SYSTEM_HOLD_REFUSAL_SCHEMA,
    validate_sealed_d12_evidence, validate_system_hold_refusal,
)
from ci.d12_hosted_qualification import (
    HostedQualificationError,
    prepare_hosted_d12,
    run_system_hold,
    seal_hosted_d12,
)
from repomap_kg.runtime import python_payload as payload
from repomap_kg.runtime.release import PRODUCT_MINIMUM_LIBPQ_VERSION
from src.test.unit.python.tools.ci.d12_hosted_fixtures import (
    BASE_PARENT_SHA, CANDIDATE_SHA, CANDIDATE_TREE, HEAD_PARENT_SHA,
    SYNTHETIC_D12_SOURCE_SHA256, SYNTHETIC_SDK_RECIPE_SHA256,
    make_fake_command_runner, make_frozen_identity, make_hosted_env,
    make_pr_event_payload, make_valid_amd64_packages, write_expected_candidate_file, write_inner_reports,
)

SDK_IMAGE_ID = "sha256:" + "01" * 32


def _setup_prepare_context(tmp_path: Path, *, cold_build: bool = True) -> dict[str, Any]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(make_pr_event_payload()), encoding="utf-8")
    expected_json = tmp_path / "d12_hosted_candidate.json"
    write_expected_candidate_file(expected_json)
    state_dir = tmp_path / "evidence"
    report_dir = tmp_path / "report"
    github_env = tmp_path / "github.env"
    entry_images: list[str] = [] if cold_build else [SDK_IMAGE_ID]
    snapshots = [
        {"containers": [], "images": list(entry_images), "volumes": [], "networks": ["bridge"]},
        {"containers": [], "images": [SDK_IMAGE_ID], "volumes": [], "networks": ["bridge"]},
        {"containers": [], "images": [SDK_IMAGE_ID], "volumes": [], "networks": ["bridge"]},
    ]
    snap_idx = {"i": 0}

    def _snapshot(_runner: Any = None) -> dict[str, list[str]]:
        idx = min(snap_idx["i"], len(snapshots) - 1)
        snap_idx["i"] += 1
        return dict(snapshots[idx])

    intent_seen_before_sdk: list[bool] = []

    def _ensure_sdk(_repo_root: Path, *, runner: Any = None, **_kwargs: Any) -> str:
        intent_file = state_dir / "sdk-build-intent.json"
        if cold_build and runner is not None:
            runner(["docker", "build", "-t", EXPECTED_SDK_IMAGE_TAG, "."], timeout=1800.0)
        intent_seen_before_sdk.append(intent_file.is_file())
        return SDK_IMAGE_ID

    return {
        "event_path": event_path, "expected_json": expected_json, "state_dir": state_dir,
        "report_dir": report_dir, "github_env": github_env, "snapshot_fn": _snapshot,
        "ensure_sdk_fn": _ensure_sdk, "intent_seen": intent_seen_before_sdk,
        "snapshots": snapshots, "snap_calls": snap_idx,
    }


def test_prepare_and_seal_partial_refusal_records_intent_baselines_and_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _setup_prepare_context(tmp_path)
    monkeypatch.setattr("test_sandbox_images.sandbox_recipe", lambda _inputs: SYNTHETIC_SDK_RECIPE_SHA256)
    state = prepare_hosted_d12(
        REPO_ROOT, expected_json=ctx["expected_json"], state_dir=ctx["state_dir"],
        report_dir=ctx["report_dir"], github_env=ctx["github_env"], env=make_hosted_env(ctx["event_path"]),
        run_cmd=make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID), uname_fn=lambda: ("Linux", "x86_64"),
        snapshot_fn=ctx["snapshot_fn"], ensure_sdk_fn=ctx["ensure_sdk_fn"],
        frozen_identity_fn=lambda _r, _p: make_frozen_identity(),
    )
    assert ctx["intent_seen"] == [True]
    sdk_mat = state["sdk_materialization"]
    assert sdk_mat["sdk_build_attempts"] == 1
    assert sdk_mat["sdk_image_id"] == SDK_IMAGE_ID
    assert sdk_mat["sdk_architecture"] == "amd64"
    assert sdk_mat["sdk_recipe_sha256"] == SYNTHETIC_SDK_RECIPE_SHA256
    assert sdk_mat["whole_job_image_parity_claimed"] is False
    assert sdk_mat["added_sdk_images"] == [SDK_IMAGE_ID]
    assert sdk_mat["removed_sdk_images"] == []
    assert f"D12_EXPECTED_SOURCE_SHA256={SYNTHETIC_D12_SOURCE_SHA256}" in ctx["github_env"].read_text(encoding="utf-8")

    write_inner_reports(ctx["report_dir"], positive=False)
    (ctx["state_dir"] / "runner-exit-code.txt").write_text("1\n", encoding="utf-8")
    sealed_out = ctx["state_dir"] / "d12-native-amd64-sealed-evidence.json"
    sealed, rc = seal_hosted_d12(
        REPO_ROOT, state_dir=ctx["state_dir"], report_dir=ctx["report_dir"],
        output_json=sealed_out, run_cmd=make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID),
        snapshot_fn=ctx["snapshot_fn"],
    )
    assert rc == 1
    assert sealed["schema"] == SEALED_EVIDENCE_SCHEMA
    assert sealed["result"] == "refused"
    assert sealed["qualified"] is False
    assert sealed["validation_violations"] == []
    assert sealed["seal_errors"] == []
    assert validate_sealed_d12_evidence(sealed) == []


def test_prepare_warm_sdk_hit_records_zero_attempts_and_no_intent_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _setup_prepare_context(tmp_path / "warm", cold_build=False)
    monkeypatch.setattr("test_sandbox_images.sandbox_recipe", lambda _inputs: SYNTHETIC_SDK_RECIPE_SHA256)
    state = prepare_hosted_d12(
        REPO_ROOT, expected_json=ctx["expected_json"], state_dir=ctx["state_dir"],
        report_dir=ctx["report_dir"], env=make_hosted_env(ctx["event_path"]),
        run_cmd=make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID), uname_fn=lambda: ("Linux", "x86_64"),
        snapshot_fn=ctx["snapshot_fn"], ensure_sdk_fn=ctx["ensure_sdk_fn"],
        frozen_identity_fn=lambda _r, _p: make_frozen_identity(),
    )
    assert ctx["intent_seen"] == [False]
    sdk_mat = state["sdk_materialization"]
    assert sdk_mat["sdk_build_attempts"] == 0
    assert sdk_mat["intent_recorded_before_build"] is False
    assert sdk_mat["intent_receipt_sha256"] is None
    assert sdk_mat["sdk_cache_cold_built"] is False
    assert sdk_mat["added_sdk_images"] == []
    assert sdk_mat["removed_sdk_images"] == []


def test_seal_positive_exploration_passes_only_when_clean_and_zero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _setup_prepare_context(tmp_path)
    monkeypatch.setattr("test_sandbox_images.sandbox_recipe", lambda _inputs: SYNTHETIC_SDK_RECIPE_SHA256)
    prepare_hosted_d12(
        REPO_ROOT, expected_json=ctx["expected_json"], state_dir=ctx["state_dir"],
        report_dir=ctx["report_dir"], env=make_hosted_env(ctx["event_path"]),
        run_cmd=make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID), uname_fn=lambda: ("Linux", "x86_64"),
        snapshot_fn=ctx["snapshot_fn"], ensure_sdk_fn=ctx["ensure_sdk_fn"],
        frozen_identity_fn=lambda _r, _p: make_frozen_identity(),
    )
    write_inner_reports(ctx["report_dir"], positive=True)
    (ctx["state_dir"] / "runner-exit-code.txt").write_text("0\n", encoding="utf-8")
    sealed_out = ctx["state_dir"] / "d12-native-amd64-sealed-evidence.json"
    assert payload.PYTHON_PAYLOAD_EXCLUSIONS["amd64"] == payload.build_31216_exclusion(  # actual ADR 0103 default
        "amd64", payload.AMD64_31216_NATIVE_BASELINE_IMPORTS)
    sealed, rc = seal_hosted_d12(
        REPO_ROOT, state_dir=ctx["state_dir"], report_dir=ctx["report_dir"],
        output_json=sealed_out, run_cmd=make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID),
        snapshot_fn=ctx["snapshot_fn"],
    )
    assert rc == 0
    assert sealed["result"] == "passed"
    assert sealed["qualified"] is True
    assert sealed["validation_violations"] == []
    assert sealed["seal_errors"] == []
    assert sealed["application_builds"]["managed_system_candidate_image_build_count"] == 0
    assert validate_sealed_d12_evidence(sealed, require_positive_qualification=True) == []
    monkeypatch.setattr(payload, "PYTHON_PAYLOAD_EXCLUSIONS", {**payload.PYTHON_PAYLOAD_EXCLUSIONS, "amd64": None})
    assert any("invalid trim contract or config" in v
               for v in validate_sealed_d12_evidence(sealed, require_positive_qualification=True))


def test_seal_fails_when_outer_docker_snapshot_has_added_or_removed_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("test_sandbox_images.sandbox_recipe", lambda _inputs: SYNTHETIC_SDK_RECIPE_SHA256)
    for label, exit_snap in (
        ("added", {"containers": ["leaked"], "images": [SDK_IMAGE_ID], "volumes": [], "networks": ["bridge"]}),
        ("removed", {"containers": [], "images": [], "volumes": [], "networks": ["bridge"]}),
    ):
        ctx = _setup_prepare_context(tmp_path / label)
        ctx["snapshots"][2] = exit_snap
        prepare_hosted_d12(
            REPO_ROOT, expected_json=ctx["expected_json"], state_dir=ctx["state_dir"],
            report_dir=ctx["report_dir"], env=make_hosted_env(ctx["event_path"]),
            run_cmd=make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID), uname_fn=lambda: ("Linux", "x86_64"),
            snapshot_fn=ctx["snapshot_fn"], ensure_sdk_fn=ctx["ensure_sdk_fn"],
            frozen_identity_fn=lambda _r, _p: make_frozen_identity(),
        )
        write_inner_reports(ctx["report_dir"], positive=True)
        (ctx["state_dir"] / "runner-exit-code.txt").write_text("0\n", encoding="utf-8")
        sealed_out = ctx["state_dir"] / "d12-native-amd64-sealed-evidence.json"
        sealed, rc = seal_hosted_d12(
            REPO_ROOT, state_dir=ctx["state_dir"], report_dir=ctx["report_dir"],
            output_json=sealed_out, run_cmd=make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID),
            snapshot_fn=ctx["snapshot_fn"],
        )
        assert rc == 1
        assert sealed["result"] == "failed"
        assert sealed["qualified"] is False
        cleanup_blk = sealed["sdk_materialization"]["post_sdk_cleanup"]
        assert cleanup_blk["clean_against_post_sdk_baseline"] is False
        if label == "removed":
            assert cleanup_blk["images_removed"] == [SDK_IMAGE_ID]


def test_seal_is_failsafe_and_preserves_prepare_refusal_reason_and_partial_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("test_sandbox_images.sandbox_recipe", lambda _inputs: SYNTHETIC_SDK_RECIPE_SHA256)
    early_ctx = _setup_prepare_context(tmp_path / "early")
    with pytest.raises(HostedQualificationError, match="run_attempt"):
        prepare_hosted_d12(
            REPO_ROOT, expected_json=early_ctx["expected_json"], state_dir=early_ctx["state_dir"],
            report_dir=early_ctx["report_dir"], env=make_hosted_env(early_ctx["event_path"], run_attempt="2"),
            run_cmd=make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID), uname_fn=lambda: ("Linux", "x86_64"),
            snapshot_fn=early_ctx["snapshot_fn"], ensure_sdk_fn=early_ctx["ensure_sdk_fn"],
            frozen_identity_fn=lambda _r, _p: make_frozen_identity(),
        )
    assert early_ctx["snap_calls"]["i"] == 0
    assert (early_ctx["state_dir"] / "prepare-refusal.json").is_file()
    early_out = early_ctx["state_dir"] / "d12-native-amd64-sealed-evidence.json"
    early_sealed, early_rc = seal_hosted_d12(
        REPO_ROOT, state_dir=early_ctx["state_dir"], report_dir=early_ctx["report_dir"],
        output_json=early_out, run_cmd=make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID),
        snapshot_fn=early_ctx["snapshot_fn"],
    )
    assert early_rc == 1
    assert early_out.is_file()
    assert early_sealed["qualified"] is False
    assert any("prepare refused at pr_admission" in e and "run_attempt" in e for e in early_sealed["seal_errors"])
    assert early_sealed["validation_violations"]

    part_ctx = _setup_prepare_context(tmp_path / "partial")
    prepare_hosted_d12(
        REPO_ROOT, expected_json=part_ctx["expected_json"], state_dir=part_ctx["state_dir"],
        report_dir=part_ctx["report_dir"], env=make_hosted_env(part_ctx["event_path"]),
        run_cmd=make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID), uname_fn=lambda: ("Linux", "x86_64"),
        snapshot_fn=part_ctx["snapshot_fn"], ensure_sdk_fn=part_ctx["ensure_sdk_fn"],
        frozen_identity_fn=lambda _r, _p: make_frozen_identity(),
    )
    write_inner_reports(part_ctx["report_dir"], positive=True)
    inner_dir = part_ctx["report_dir"] / "d12-core-image/linux-amd64"
    (inner_dir / "exploration.json").write_text("{truncated", encoding="utf-8")
    (inner_dir / "cleanup.json").unlink()
    part_out = part_ctx["state_dir"] / "d12-native-amd64-sealed-evidence.json"
    part_sealed, part_rc = seal_hosted_d12(
        REPO_ROOT, state_dir=part_ctx["state_dir"], report_dir=part_ctx["report_dir"],
        output_json=part_out, run_cmd=make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID),
        snapshot_fn=part_ctx["snapshot_fn"],
    )
    assert part_rc == 1
    assert part_sealed["inner_reports"]["freeze"] is not None
    assert part_sealed["inner_reports"]["exploration"] is None
    assert part_sealed["report_provenance"]["exploration"]["status"] == "malformed_json"
    assert part_sealed["report_provenance"]["cleanup"]["status"] == "missing"
    assert part_sealed["application_builds"]["application_builds"] is None
    assert part_sealed["validation_violations"]


def test_prepare_refuses_invalid_bindings_missing_arch_and_mismatched_sdk_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _setup_prepare_context(tmp_path)
    monkeypatch.setattr("test_sandbox_images.sandbox_recipe", lambda _inputs: SYNTHETIC_SDK_RECIPE_SHA256)

    for missing_key in ("GITHUB_SHA", "CANDIDATE_SHA", "CANDIDATE_TREE"):
        bad_env = {k: v for k, v in make_hosted_env(ctx["event_path"]).items() if k != missing_key}
        with pytest.raises(HostedQualificationError, match="binding|CANDIDATE|SHA|tree"):
            prepare_hosted_d12(
                REPO_ROOT, expected_json=ctx["expected_json"], state_dir=ctx["state_dir"],
                report_dir=ctx["report_dir"], env=bad_env,
                run_cmd=make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID),
                uname_fn=lambda: ("Linux", "x86_64"), snapshot_fn=ctx["snapshot_fn"],
                ensure_sdk_fn=ctx["ensure_sdk_fn"], frozen_identity_fn=lambda _r, _p: make_frozen_identity(),
            )

    no_arch_ctx = _setup_prepare_context(tmp_path / "no_arch")
    with pytest.raises(HostedQualificationError, match="architecture|amd64"):
        prepare_hosted_d12(
            REPO_ROOT, expected_json=no_arch_ctx["expected_json"], state_dir=no_arch_ctx["state_dir"],
            report_dir=no_arch_ctx["report_dir"], env=make_hosted_env(no_arch_ctx["event_path"]),
            run_cmd=make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID, sdk_arch=None),
            uname_fn=lambda: ("Linux", "x86_64"), snapshot_fn=no_arch_ctx["snapshot_fn"],
            ensure_sdk_fn=no_arch_ctx["ensure_sdk_fn"],
            frozen_identity_fn=lambda _r, _p: make_frozen_identity(),
        )
    assert no_arch_ctx["snap_calls"]["i"] == 1
    refusal_doc = json.loads((no_arch_ctx["state_dir"] / "prepare-refusal.json").read_text(encoding="utf-8"))
    assert refusal_doc["stage"] == "sdk_materialization"
    assert refusal_doc["reached"]["pr_binding"]["run_attempt"] == 1


def test_system_hold_and_hermetic_child_interpreter_cli_entrypoints(tmp_path: Path) -> None:
    out_json = tmp_path / "system-hold-refusal.json"
    report, rc = run_system_hold(
        REPO_ROOT, candidate_sha=CANDIDATE_SHA, candidate_tree=CANDIDATE_TREE,
        candidate_base_parent=BASE_PARENT_SHA, candidate_head_parent=HEAD_PARENT_SHA,
        output_json=out_json, target_arch="amd64", frozen_identity_fn=lambda _r, _p: make_frozen_identity(),
    )
    assert rc == 1
    assert report["schema"] == SYSTEM_HOLD_REFUSAL_SCHEMA
    assert validate_system_hold_refusal(report) == []

    ok_report, ok_rc = run_system_hold(
        REPO_ROOT, candidate_sha=CANDIDATE_SHA, candidate_tree=CANDIDATE_TREE,
        candidate_base_parent=BASE_PARENT_SHA, candidate_head_parent=HEAD_PARENT_SHA,
        output_json=tmp_path / "ok-hold.json", target_arch="amd64",
        libpq_version=PRODUCT_MINIMUM_LIBPQ_VERSION, package_manifest={"amd64": make_valid_amd64_packages()},
        frozen_identity_fn=lambda _r, _p: make_frozen_identity(),
    )
    assert ok_rc == 0 and ok_report["result"] == "prerequisites_resolved"

    script = str(REPO_ROOT / "tools/ci/d12_hosted_qualification.py")
    child_hold_out = tmp_path / "child-system-hold.json"
    hold_proc = subprocess.run(
        [
            sys.executable, "-I", "-S", "-B", script, "system-hold",
            "--repo-root", str(REPO_ROOT), "--candidate-sha", CANDIDATE_SHA,
            "--candidate-tree", CANDIDATE_TREE, "--candidate-base-parent", BASE_PARENT_SHA,
            "--candidate-head-parent", HEAD_PARENT_SHA, "--output-json", str(child_hold_out),
        ],
        check=False, capture_output=True, text=True,
    )
    assert hold_proc.returncode == 1
    assert validate_system_hold_refusal(json.loads(child_hold_out.read_text(encoding="utf-8"))) == []

    child_ctx = _setup_prepare_context(tmp_path / "child_cli")
    child_env = {**make_hosted_env(child_ctx["event_path"], run_attempt="2"), "PATH": "/usr/bin:/bin"}
    prep_proc = subprocess.run(
        [
            sys.executable, "-I", "-S", "-B", script, "prepare",
            "--repo-root", str(REPO_ROOT), "--expected-json", str(child_ctx["expected_json"]),
            "--state-dir", str(child_ctx["state_dir"]), "--report-dir", str(child_ctx["report_dir"]),
        ],
        check=False, capture_output=True, text=True, env=child_env,
    )
    assert prep_proc.returncode == 1
    assert (child_ctx["state_dir"] / "prepare-refusal.json").is_file()

    child_seal_out = child_ctx["state_dir"] / "child-sealed.json"
    seal_proc = subprocess.run(
        [
            sys.executable, "-I", "-S", "-B", script, "seal",
            "--repo-root", str(REPO_ROOT), "--state-dir", str(child_ctx["state_dir"]),
            "--report-dir", str(child_ctx["report_dir"]), "--output-json", str(child_seal_out),
        ],
        check=False, capture_output=True, text=True, env={"PATH": "/nonexistent"},
    )
    assert seal_proc.returncode == 1
    child_sealed = json.loads(child_seal_out.read_text(encoding="utf-8"))
    assert any("prepare refused at pr_admission" in err for err in child_sealed["seal_errors"])


def test_default_sdk_adapter_forwards_kwargs_verifies_arch_and_records_removed_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("test_sandbox_images.sandbox_recipe", lambda _inputs: SYNTHETIC_SDK_RECIPE_SHA256)
    base_git = make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID)
    labels = {"org.repomap.test.sandbox.image": "true", "org.repomap.test.sandbox.recipe": SYNTHETIC_SDK_RECIPE_SHA256}
    inspect_doc = json.dumps({"Id": SDK_IMAGE_ID, "Architecture": "amd64", "Config": {"Labels": labels}})
    stale_id = "sha256:" + "99" * 32

    cold_ctx = _setup_prepare_context(tmp_path / "cold")
    cold_ctx["snapshots"][0]["images"] = [stale_id]
    cold_ctx["snapshots"][1]["images"] = [SDK_IMAGE_ID]
    inspect_calls, build_seen_intent, build_timeouts = {"n": 0}, [], []

    def _cold_runner(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if cmd[:3] == ["docker", "image", "inspect"]:
            inspect_calls["n"] += 1
            if inspect_calls["n"] == 1:
                return subprocess.CompletedProcess(cmd, 1, "", f"Error: No such image: {EXPECTED_SDK_IMAGE_TAG}\n")
            return subprocess.CompletedProcess(cmd, 0, inspect_doc, "")
        if cmd[:2] == ["docker", "build"]:
            build_seen_intent.append((cold_ctx["state_dir"] / "sdk-build-intent.json").is_file())
            build_timeouts.append(kwargs.get("timeout"))
            return subprocess.CompletedProcess(cmd, 0, "built\n", "")
        if cmd[:3] == ["docker", "image", "ls"]:
            return subprocess.CompletedProcess(cmd, 0, f"{SDK_IMAGE_ID}\n", "")
        if cmd[:3] == ["docker", "container", "ls"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return base_git(cmd, **kwargs)

    cold_state = prepare_hosted_d12(
        REPO_ROOT, expected_json=cold_ctx["expected_json"], state_dir=cold_ctx["state_dir"],
        report_dir=cold_ctx["report_dir"], env=make_hosted_env(cold_ctx["event_path"]),
        run_cmd=_cold_runner, uname_fn=lambda: ("Linux", "x86_64"),
        snapshot_fn=cold_ctx["snapshot_fn"], frozen_identity_fn=lambda _r, _p: make_frozen_identity(),
    )
    assert build_seen_intent == [True] and build_timeouts == [1800.0]
    sdk_mat = cold_state["sdk_materialization"]
    assert sdk_mat["sdk_build_attempts"] == 1
    assert sdk_mat["sdk_image_id"] == SDK_IMAGE_ID
    assert sdk_mat["sdk_architecture"] == "amd64"
    assert sdk_mat["added_sdk_images"] == [SDK_IMAGE_ID]
    assert sdk_mat["removed_sdk_images"] == [stale_id]
