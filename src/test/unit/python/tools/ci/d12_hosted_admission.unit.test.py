"""Unit tests for hosted native D12 explicit merge-parent bindings and single-call SDK adapter."""

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

from ci.d12_hosted_evidence import EXPECTED_SDK_IMAGE_TAG
from ci.d12_hosted_qualification import HostedQualificationError, prepare_hosted_d12
from ci.d12_hosted_state import PREPARE_REFUSAL_SCHEMA
from src.test.unit.python.tools.ci.d12_hosted_fixtures import (
    BASE_PARENT_SHA,
    CANDIDATE_SHA,
    CANDIDATE_TREE,
    HEAD_PARENT_SHA,
    SYNTHETIC_SDK_RECIPE_SHA256,
    make_fake_command_runner,
    make_frozen_identity,
    make_hosted_env,
    make_pr_event_payload,
    write_expected_candidate_file,
)

SDK_IMAGE_ID = "sha256:" + "01" * 32


def _make_harness(tmp_path: Path) -> dict[str, Any]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(make_pr_event_payload()), encoding="utf-8")
    expected_json = tmp_path / "d12_hosted_candidate.json"
    write_expected_candidate_file(expected_json)
    state_dir = tmp_path / "evidence"
    report_dir = tmp_path / "report"
    github_env = tmp_path / "github.env"
    base_runner = make_fake_command_runner(sdk_image_id=SDK_IMAGE_ID)
    docker_commands: list[list[str]] = []
    snap_calls: list[int] = []
    sdk_calls: list[dict[str, Any]] = []
    snapshots = [
        {"containers": [], "images": [], "volumes": [], "networks": ["bridge"]},
        {"containers": [], "images": [SDK_IMAGE_ID], "volumes": [], "networks": ["bridge"]},
    ]

    def _runner(args: list[str], *pos: Any, **kw: Any) -> subprocess.CompletedProcess[str]:
        if args and args[0] == "docker":
            docker_commands.append(list(args))
        return base_runner(args, *pos, **kw)

    def _snapshot(_run: Any = None) -> dict[str, list[str]]:
        idx = min(len(snap_calls), len(snapshots) - 1)
        snap_calls.append(idx)
        return dict(snapshots[idx])

    def _ensure_sdk(repo_root: Path, *, runner: Any) -> str:
        sdk_calls.append({"repo_root": repo_root, "runner": runner})
        runner(["docker", "build", "-t", EXPECTED_SDK_IMAGE_TAG, "."], timeout=1800.0)
        return SDK_IMAGE_ID

    return {
        "event_path": event_path,
        "expected_json": expected_json,
        "state_dir": state_dir,
        "report_dir": report_dir,
        "github_env": github_env,
        "run_cmd": _runner,
        "snapshot_fn": _snapshot,
        "ensure_sdk_fn": _ensure_sdk,
        "docker_commands": docker_commands,
        "snap_calls": snap_calls,
        "sdk_calls": sdk_calls,
    }


def _invoke_prepare(
    harness: dict[str, Any],
    *,
    env: dict[str, str],
    ensure_sdk_fn: Any = None,
    run_cmd: Any = None,
) -> dict[str, Any]:
    return prepare_hosted_d12(
        REPO_ROOT,
        expected_json=harness["expected_json"],
        state_dir=harness["state_dir"],
        report_dir=harness["report_dir"],
        github_env=harness["github_env"],
        env=env,
        run_cmd=run_cmd or harness["run_cmd"],
        uname_fn=lambda: ("Linux", "x86_64"),
        snapshot_fn=harness["snapshot_fn"],
        ensure_sdk_fn=ensure_sdk_fn or harness["ensure_sdk_fn"],
        frozen_identity_fn=lambda _r, _p: make_frozen_identity(),
    )


def test_prepare_hosted_d12_accepts_complete_explicit_merge_parent_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _make_harness(tmp_path)
    monkeypatch.setattr("test_sandbox_images.sandbox_recipe", lambda _inputs: SYNTHETIC_SDK_RECIPE_SHA256)
    env = make_hosted_env(harness["event_path"])
    state = _invoke_prepare(harness, env=env)
    binding = state["pr_binding"]
    assert binding["candidate_sha"] == CANDIDATE_SHA
    assert binding["candidate_tree"] == CANDIDATE_TREE
    assert binding["candidate_base_parent"] == BASE_PARENT_SHA
    assert binding["candidate_head_parent"] == HEAD_PARENT_SHA
    assert len(harness["sdk_calls"]) == 1
    assert state["sdk_materialization"]["sdk_build_attempts"] == 1


@pytest.mark.parametrize(
    "missing_keys",
    [
        ("CANDIDATE_BASE_PARENT",),
        ("CANDIDATE_HEAD_PARENT",),
        ("CANDIDATE_BASE_PARENT", "CANDIDATE_HEAD_PARENT"),
        ("GITHUB_SHA",),
        ("CANDIDATE_SHA",),
        ("CANDIDATE_TREE",),
    ],
)
def test_prepare_hosted_d12_refuses_missing_explicit_git_bindings_before_docker_or_sdk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_keys: tuple[str, ...],
) -> None:
    case_dir = tmp_path / ("missing-" + "-".join(missing_keys).lower())
    harness = _make_harness(case_dir)
    monkeypatch.setattr("test_sandbox_images.sandbox_recipe", lambda _inputs: SYNTHETIC_SDK_RECIPE_SHA256)
    env = make_hosted_env(harness["event_path"])
    for key in missing_keys:
        env.pop(key, None)

    with pytest.raises(HostedQualificationError, match="binding mismatch"):
        _invoke_prepare(harness, env=env)

    assert harness["docker_commands"] == []
    assert harness["snap_calls"] == []
    assert harness["sdk_calls"] == []
    assert not (harness["state_dir"] / "sdk-build-intent.json").exists()
    assert not (harness["state_dir"] / "prepare-state.json").exists()
    refusal = json.loads((harness["state_dir"] / "prepare-refusal.json").read_text(encoding="utf-8"))
    assert refusal["schema"] == PREPARE_REFUSAL_SCHEMA
    assert refusal["stage"] == "git_binding"
    assert refusal["reached"] == {}


@pytest.mark.parametrize(
    ("binding_key", "blank_value"),
    [
        ("CANDIDATE_BASE_PARENT", ""),
        ("CANDIDATE_BASE_PARENT", "   \t\n  "),
        ("CANDIDATE_HEAD_PARENT", ""),
        ("CANDIDATE_HEAD_PARENT", "   \t\n  "),
        ("GITHUB_SHA", "   "),
        ("CANDIDATE_SHA", ""),
        ("CANDIDATE_TREE", "  "),
    ],
)
def test_prepare_hosted_d12_refuses_blank_explicit_git_bindings_before_docker_or_sdk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding_key: str,
    blank_value: str,
) -> None:
    case_dir = tmp_path / f"blank-{binding_key.lower()}-{len(blank_value)}"
    harness = _make_harness(case_dir)
    monkeypatch.setattr("test_sandbox_images.sandbox_recipe", lambda _inputs: SYNTHETIC_SDK_RECIPE_SHA256)
    env = make_hosted_env(harness["event_path"])
    env[binding_key] = blank_value

    with pytest.raises(HostedQualificationError, match="binding mismatch"):
        _invoke_prepare(harness, env=env)

    assert harness["docker_commands"] == []
    assert harness["snap_calls"] == []
    assert harness["sdk_calls"] == []
    refusal = json.loads((harness["state_dir"] / "prepare-refusal.json").read_text(encoding="utf-8"))
    assert refusal["stage"] == "git_binding"
    assert refusal["reached"] == {}


@pytest.mark.parametrize(
    ("binding_key", "wrong_value"),
    [
        ("CANDIDATE_BASE_PARENT", "9" * 40),
        ("CANDIDATE_HEAD_PARENT", "8" * 40),
        ("CANDIDATE_TREE", "7" * 40),
        ("CANDIDATE_SHA", "6" * 40),
    ],
)
def test_prepare_hosted_d12_refuses_mismatched_explicit_git_bindings_before_docker_or_sdk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    binding_key: str,
    wrong_value: str,
) -> None:
    case_dir = tmp_path / f"mismatch-{binding_key.lower()}"
    harness = _make_harness(case_dir)
    monkeypatch.setattr("test_sandbox_images.sandbox_recipe", lambda _inputs: SYNTHETIC_SDK_RECIPE_SHA256)
    env = make_hosted_env(harness["event_path"])
    env[binding_key] = wrong_value

    with pytest.raises(HostedQualificationError, match="binding mismatch"):
        _invoke_prepare(harness, env=env)

    assert harness["docker_commands"] == []
    assert harness["snap_calls"] == []
    assert harness["sdk_calls"] == []


def test_prepare_hosted_d12_does_not_retry_ensure_sdk_adapter_on_internal_type_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _make_harness(tmp_path)
    monkeypatch.setattr("test_sandbox_images.sandbox_recipe", lambda _inputs: SYNTHETIC_SDK_RECIPE_SHA256)
    invocations: list[bool] = []

    def _failing_adapter(_repo_root: Path, *, runner: Any = None) -> str:
        invocations.append(runner is not None)
        if runner is not None:
            runner(["docker", "build", "-t", EXPECTED_SDK_IMAGE_TAG, "."], timeout=1800.0)
        raise TypeError("internal adapter failure after first counted build")

    with pytest.raises(HostedQualificationError, match="sdk_materialization"):
        _invoke_prepare(harness, env=make_hosted_env(harness["event_path"]), ensure_sdk_fn=_failing_adapter)

    assert invocations == [True]
    build_cmds = [cmd for cmd in harness["docker_commands"] if cmd[:2] == ["docker", "build"]]
    assert len(build_cmds) == 1
    assert not (harness["state_dir"] / "prepare-state.json").exists()
    refusal = json.loads((harness["state_dir"] / "prepare-refusal.json").read_text(encoding="utf-8"))
    assert refusal["stage"] == "sdk_materialization"
    assert refusal["reached"]["sdk_materialization"]["sdk_build_attempts"] == 1


def test_prepare_hosted_d12_refuses_positional_only_ensure_sdk_adapter_without_uncounted_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _make_harness(tmp_path)
    monkeypatch.setattr("test_sandbox_images.sandbox_recipe", lambda _inputs: SYNTHETIC_SDK_RECIPE_SHA256)
    body_executions: list[Path] = []

    def _legacy_positional_adapter(repo_root: Path) -> str:
        body_executions.append(repo_root)
        return SDK_IMAGE_ID

    with pytest.raises(HostedQualificationError, match="sdk_materialization"):
        _invoke_prepare(
            harness,
            env=make_hosted_env(harness["event_path"]),
            ensure_sdk_fn=_legacy_positional_adapter,
        )

    assert body_executions == []
    assert not (harness["state_dir"] / "sdk-build-intent.json").exists()
    assert not (harness["state_dir"] / "prepare-state.json").exists()
    refusal = json.loads((harness["state_dir"] / "prepare-refusal.json").read_text(encoding="utf-8"))
    assert refusal["stage"] == "sdk_materialization"
