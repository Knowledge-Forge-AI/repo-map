#!/usr/bin/env python3
"""Hosted native D12 qualification prepare, seal, and early system-hold seam."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
for _rel in ("", "src/main/python", "tools", "src/test/support/python"):
    if (_p := str((_ROOT / _rel).resolve())) not in sys.path:
        sys.path.insert(0, _p)

from ci.d12_hosted_evidence import (
    EXPECTED_HOST_ARCH, EXPECTED_PLATFORM, EXPECTED_RUNNER_ARCH, EXPECTED_RUNNER_OS,
    EXPECTED_SDK_DOCKERFILE_SHA256, EXPECTED_SDK_HELPER_SHA256, EXPECTED_SDK_IMAGE_TAG,
    HostedD12EvidenceError, SDK_BUILD_INTENT_SCHEMA, SEALED_EVIDENCE_SCHEMA,
    SYSTEM_HOLD_REFUSAL_SCHEMA, validate_expected_candidate_record, validate_sealed_d12_evidence,
)
from ci.d12_hosted_reports import load_safe_json_report, project_canonical_boundary_counts
from ci.d12_hosted_state import load_prepare_or_refusal_state, write_prepare_refusal_state
from repomap_kg.runtime.release import DYNAMIC_PACKAGE_MANIFEST, PSYCOPG_LIBPQ_VERSION
from repomap_test_support import d12_core_image
import test_sandbox
import test_sandbox_images
from tools.system.candidate_image import require_release_prerequisites_resolved
from tools.system.config import SystemTestError

REPO_ROOT = _ROOT
_REDACT_RE = re.compile(r"(/" + r"Users/[^\s\"']+|/home/[^\s\"']+|ghp_[A-Za-z0-9_]+|PRIVATE_KEY[^\s\"']*)")


class HostedQualificationError(RuntimeError):
    """Raised when hosted D12 prepare, seal, or system-hold refuses execution."""


def _default_runner(repo_root: Path) -> Callable[..., subprocess.CompletedProcess[str]]:
    def _run(args: list[str], *pos: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        opts: dict[str, Any] = {"cwd": repo_root, "capture_output": True, "text": True, "check": False, **kwargs}
        return subprocess.run(args, *pos, **opts)
    return _run


def _default_uname() -> tuple[str, str]:
    return (os.uname().sysname, os.uname().machine)


def _default_snapshot(run_cmd: Callable[..., subprocess.CompletedProcess[str]]) -> dict[str, list[str]]:
    queries = {
        "containers": ["docker", "ps", "-aq", "--no-trunc"], "images": ["docker", "images", "-q", "--no-trunc"],
        "volumes": ["docker", "volume", "ls", "-q"], "networks": ["docker", "network", "ls", "--format", "{{.Name}}"],
    }
    snap: dict[str, list[str]] = {}
    for key, cmd in queries.items():
        if (res := run_cmd(cmd)).returncode != 0:
            raise HostedQualificationError(f"docker snapshot failed for {key}: {res.stderr.strip()}")
        snap[key] = sorted({line.strip() for line in res.stdout.splitlines() if line.strip()})
    return snap


def _rev_parse(run_cmd: Callable[..., subprocess.CompletedProcess[str]], rev: str) -> str:
    if (res := run_cmd(["git", "rev-parse", rev])).returncode != 0 or len(val := res.stdout.strip()) != 40:
        raise HostedQualificationError(f"git rev-parse {rev} failed: {res.stderr.strip()}")
    return val


def _redact_val(val: Any) -> Any:
    return _REDACT_RE.sub("<redacted>", val) if isinstance(val, str) else val


def _as_map(val: object) -> Mapping[str, Any]:
    return val if isinstance(val, Mapping) else {}


def prepare_hosted_d12(
    repo_root: Path, *, expected_json: Path, state_dir: Path, report_dir: Path,
    github_env: Path | None = None, env: Mapping[str, str] | None = None,
    event_payload: Mapping[str, object] | None = None,
    run_cmd: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    uname_fn: Callable[[], tuple[str, str]] | None = None,
    snapshot_fn: Callable[..., dict[str, list[str]]] | None = None,
    ensure_sdk_fn: Callable[..., str] | None = None,
    frozen_identity_fn: Callable[[Path, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    state_dir.mkdir(parents=True, exist_ok=True)
    environ, runner = dict(os.environ if env is None else env), run_cmd or _default_runner(repo_root)
    uname, snap = uname_fn or _default_uname, snapshot_fn or _default_snapshot
    frozen_fn, stage = frozen_identity_fn or d12_core_image.frozen_identity, "pr_admission"
    reached: dict[str, Any] = {}
    try:
        if (attempt_raw := environ.get("GITHUB_RUN_ATTEMPT", "")) != "1":
            raise HostedQualificationError(f"run_attempt must be 1 for d12-native-amd64; got {attempt_raw!r}")
        if (event_name := environ.get("GITHUB_EVENT_NAME", "")) != "pull_request":
            raise HostedQualificationError(f"event_name must be pull_request; got {event_name!r}")
        if event_payload is None:
            if not (event_path := Path(environ.get("GITHUB_EVENT_PATH", ""))).is_file():
                raise HostedQualificationError("GITHUB_EVENT_PATH is missing")
            event_payload = json.loads(event_path.read_text(encoding="utf-8"))
        if not isinstance(event_payload, Mapping) or not isinstance(pr := event_payload.get("pull_request"), Mapping):
            raise HostedQualificationError("event payload missing pull_request mapping")
        base_b, head_b, repo = _as_map(pr.get("base")), _as_map(pr.get("head")), environ.get("GITHUB_REPOSITORY", "")
        base_repo = str(_as_map(base_b.get("repo")).get("full_name", ""))
        head_repo = str(_as_map(head_b.get("repo")).get("full_name", ""))
        if not repo or base_repo != repo or head_repo != repo:
            raise HostedQualificationError(f"same-repository PR required; got repo={repo!r}, head={head_repo!r}")
        base_ref, head_ref = str(base_b.get("ref", "")), str(head_b.get("ref", ""))
        if base_ref != "main" or head_ref != "staging":
            raise HostedQualificationError(f"PR must target staging -> main; got {head_ref!r} -> {base_ref!r}")
        event_base_sha, event_head_sha = str(base_b.get("sha", "")), str(head_b.get("sha", ""))
        stage = "git_binding"
        head_commit_sha, candidate_tree = _rev_parse(runner, "HEAD"), _rev_parse(runner, "HEAD^{tree}")
        candidate_base_parent, candidate_head_parent = _rev_parse(runner, "HEAD^1"), _rev_parse(runner, "HEAD^2")
        github_sha, candidate_sha = environ.get("GITHUB_SHA", "").strip(), environ.get("CANDIDATE_SHA", "").strip()
        env_tree = environ.get("CANDIDATE_TREE", "").strip()
        env_base = environ.get("CANDIDATE_BASE_PARENT", "").strip()
        env_head = environ.get("CANDIDATE_HEAD_PARENT", "").strip()
        if not (github_sha and candidate_sha and env_tree and env_base and env_head
                and candidate_sha == github_sha == head_commit_sha and env_tree == candidate_tree
                and env_base == candidate_base_parent == event_base_sha
                and env_head == candidate_head_parent == event_head_sha):
            raise HostedQualificationError("explicit merge commit, tree, or parent SHA binding mismatch")
        reached["pr_binding"] = {
            "event_name": event_name, "run_id": str(environ.get("GITHUB_RUN_ID", "")), "run_attempt": 1,
            "repository": repo, "base_repo": base_repo, "head_repo": head_repo, "base_ref": base_ref,
            "head_ref": head_ref, "candidate_sha": candidate_sha, "github_sha": github_sha,
            "head_commit_sha": head_commit_sha, "candidate_tree": candidate_tree,
            "candidate_base_parent": candidate_base_parent, "event_base_sha": event_base_sha,
            "candidate_head_parent": candidate_head_parent, "event_head_sha": event_head_sha,
        }
        stage = "expected_candidate"
        if not expected_json.is_file() or expected_json.is_symlink():
            raise HostedQualificationError(f"expected candidate file is missing or symlink: {expected_json}")
        expected_raw = expected_json.read_bytes()
        expected_record_sha256 = hashlib.sha256(expected_raw).hexdigest()
        try:
            expected_record = validate_expected_candidate_record(json.loads(expected_raw.decode("utf-8")))
        except (ValueError, HostedD12EvidenceError) as error:
            raise HostedQualificationError(f"invalid expected candidate record: {error}") from error
        stage = "d12_identity"
        observed_d12, exp_d12 = frozen_fn(repo_root, EXPECTED_PLATFORM), expected_record["d12_context"]
        for key in ("source_sha256", "recipe_sha256", "dockerfile_sha256", "context_file_count"):
            if observed_d12.get(key) != exp_d12.get(key):
                raise HostedQualificationError(f"frozen D12 {key} mismatch")
        stage = "sdk_identity"
        sdk_inputs = test_sandbox_images.sandbox_recipe_inputs(repo_root / "tools/test_sandbox/Dockerfile")
        observed_sdk_dockerfile = hashlib.sha256(sdk_inputs.get("Dockerfile", b"")).hexdigest()
        observed_sdk_helper = hashlib.sha256(sdk_inputs.get("apt_prerequisites.py", b"")).hexdigest()
        observed_sdk_recipe, exp_sdk = test_sandbox_images.sandbox_recipe(sdk_inputs), expected_record["sdk_sandbox"]
        if (observed_sdk_dockerfile != exp_sdk["sdk_dockerfile_sha256"]
                or observed_sdk_helper != exp_sdk["sdk_helper_sha256"]
                or observed_sdk_recipe != exp_sdk["sdk_recipe_sha256"]
                or observed_sdk_dockerfile != EXPECTED_SDK_DOCKERFILE_SHA256
                or observed_sdk_helper != EXPECTED_SDK_HELPER_SHA256):
            raise HostedQualificationError("frozen SDK sandbox recipe or input digest mismatch")
        reached["identity_binding"] = {
            "expected_candidate_sha256": expected_record_sha256,
            "d12_context": {**exp_d12, "matches_expected": True}, "sdk_sandbox": {**exp_sdk, "matches_expected": True},
        }
        stage = "native_environment"
        runner_os, runner_arch = environ.get("RUNNER_OS", ""), environ.get("RUNNER_ARCH", "")
        host_kernel, host_arch = uname()
        if (info_res := runner(["docker", "info", "--format", "{{json .}}"])).returncode != 0:
            raise HostedQualificationError("docker info failed on outer host")
        info_doc = json.loads(info_res.stdout)
        daemon_arch, daemon_os = str(info_doc.get("Architecture", "")), str(info_doc.get("OSType", "")).lower()
        if not (runner_os == EXPECTED_RUNNER_OS and runner_arch == EXPECTED_RUNNER_ARCH and host_kernel == "Linux"
                and host_arch == EXPECTED_HOST_ARCH and daemon_os == "linux" and daemon_arch == EXPECTED_HOST_ARCH):
            raise HostedQualificationError(f"native Linux x86_64 required: {host_arch!r}/{daemon_arch!r}")
        reached["native_environment"] = {
            "runner_os": runner_os, "runner_arch": runner_arch, "host_kernel": host_kernel,
            "host_arch": host_arch, "docker_daemon_arch": daemon_arch, "emulated": False,
        }
        stage = "report_dir"
        if report_dir.exists() or report_dir.is_symlink():
            raise HostedQualificationError(f"report_dir must not exist before run: {report_dir}")
        stage = "entry_baseline"
        entry_baseline = snap(runner)
        reached["entry_baseline"] = entry_baseline
        stage = "sdk_materialization"
        intent_payload = {
            "schema": SDK_BUILD_INTENT_SCHEMA, "platform": EXPECTED_PLATFORM, "image_tag": EXPECTED_SDK_IMAGE_TAG,
            "sdk_dockerfile_sha256": observed_sdk_dockerfile, "sdk_helper_sha256": observed_sdk_helper,
            "sdk_recipe_sha256": observed_sdk_recipe, "run_attempt": 1, "candidate_sha": candidate_sha,
        }
        intent_bytes = (json.dumps(intent_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        intent_receipt_sha256 = hashlib.sha256(intent_bytes).hexdigest()
        build_track: dict[str, Any] = {"attempts": 0, "intent_recorded": False, "inspected_arch": None}
        def _record_intent() -> None:
            if int(build_track["attempts"]) >= 1:
                raise HostedQualificationError("SDK image build retry refused: sdk_build_attempts exceeds 1")
            (state_dir / "sdk-build-intent.json").write_bytes(intent_bytes)
            build_track["intent_recorded"], build_track["attempts"] = True, int(build_track["attempts"]) + 1
            reached["sdk_materialization"] = {
                "image_tag": EXPECTED_SDK_IMAGE_TAG, "sdk_recipe_sha256": observed_sdk_recipe,
                "sdk_build_attempts": build_track["attempts"], "intent_recorded_before_build": True,
                "intent_receipt_sha256": intent_receipt_sha256, "sdk_cache_cold_built": True,
                "whole_job_image_parity_claimed": False, "entry_baseline": entry_baseline,
            }
        def _counted_sdk_runner(command: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if command[:2] == ["docker", "build"]:
                _record_intent()
            res = runner(command, *args, **kwargs)
            if command[:3] == ["docker", "image", "inspect"] and res.returncode == 0 and "{" in res.stdout:
                inspected = json.loads(res.stdout.strip())
                raw_arch = inspected.get("Architecture") if isinstance(inspected, Mapping) else None
                if not isinstance(raw_arch, str) or raw_arch not in ("amd64", "x86_64"):
                    raise HostedQualificationError(f"SDK image architecture must be native amd64: {raw_arch!r}")
                build_track["inspected_arch"] = "amd64"
            return res
        if ensure_sdk_fn is None:
            sdk_image_id = test_sandbox.ensure_sandbox_image(
                dockerfile=repo_root / "tools/test_sandbox/Dockerfile", runner=_counted_sdk_runner
            )
        else:
            sdk_image_id = ensure_sdk_fn(repo_root, runner=_counted_sdk_runner)
        if not isinstance(sdk_image_id, str) or test_sandbox.EXACT_ID.fullmatch(sdk_image_id) is None:
            raise HostedQualificationError(f"SDK setup must return exact sha256 image ID; got {sdk_image_id!r}")
        if build_track["inspected_arch"] is None:
            insp = _counted_sdk_runner(["docker", "image", "inspect", "--format", "{{json .}}", EXPECTED_SDK_IMAGE_TAG])
            if insp.returncode != 0 or build_track["inspected_arch"] != "amd64":
                raise HostedQualificationError("SDK image inspect failed or missing native amd64 architecture")
        post_sdk_baseline = snap(runner)
        reached["post_sdk_baseline"] = post_sdk_baseline
        e_imgs, p_imgs = set(entry_baseline.get("images", [])), set(post_sdk_baseline.get("images", []))
        att_count, intent_rec = int(build_track["attempts"]), bool(build_track["intent_recorded"])
        reached["sdk_materialization"] = {
            "image_tag": EXPECTED_SDK_IMAGE_TAG, "sdk_image_id": sdk_image_id,
            "sdk_architecture": str(build_track["inspected_arch"]), "sdk_recipe_sha256": observed_sdk_recipe,
            "sdk_build_attempts": att_count, "intent_recorded_before_build": intent_rec,
            "intent_receipt_sha256": intent_receipt_sha256 if intent_rec else None,
            "sdk_cache_cold_built": bool(att_count == 1), "whole_job_image_parity_claimed": False,
            "added_sdk_images": sorted(p_imgs - e_imgs), "removed_sdk_images": sorted(e_imgs - p_imgs),
            "entry_baseline": entry_baseline, "post_sdk_baseline": post_sdk_baseline,
        }
    except Exception as error:
        write_prepare_refusal_state(state_dir, stage=stage, reason=str(error), reached=reached, redact_fn=_redact_val)
        if isinstance(error, HostedQualificationError):
            raise
        raise HostedQualificationError(f"prepare failed at {stage}: {error}") from error
    state = {k: reached[k] for k in ("pr_binding", "identity_binding", "native_environment", "sdk_materialization")}
    (state_dir / "prepare-state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if github_env is not None:
        with github_env.open("a", encoding="utf-8") as handle:
            handle.write(f"D12_EXPECTED_SOURCE_SHA256={exp_d12['source_sha256']}\n")
    return state


def seal_hosted_d12(
    repo_root: Path, *, state_dir: Path, report_dir: Path, output_json: Path,
    runner_exit_code: int | None = None,
    run_cmd: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    snapshot_fn: Callable[..., dict[str, list[str]]] | None = None,
) -> tuple[dict[str, Any], int]:
    state_dir.mkdir(parents=True, exist_ok=True)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    runner, snap = run_cmd or _default_runner(repo_root), snapshot_fn or _default_snapshot
    seal_errors: list[str] = []
    state, state_err, refusal_doc = load_prepare_or_refusal_state(state_dir, redact_fn=_redact_val)
    if refusal_doc is not None:
        st, rsn = refusal_doc.get("stage", "unknown"), refusal_doc.get("reason", "refused")
        seal_errors.append(f"prepare refused at {st}: {rsn}")
    elif state_err is not None:
        seal_errors.append(state_err)
    if runner_exit_code is None:
        exit_file = state_dir / "runner-exit-code.txt"
        try:
            runner_exit_code = int(exit_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as exc:
            seal_errors.append("runner-exit-code.txt is missing" if not exit_file.is_file()
                               else f"invalid runner-exit-code.txt: {exc}")
            runner_exit_code = 1
    try:
        exit_snapshot, snapshot_ok = snap(runner), True
    except Exception as exc:
        seal_errors.append(f"exit docker snapshot failed: {exc}")
        exit_snapshot, snapshot_ok = {}, False
    sdk_mat = _as_map(state.get("sdk_materialization"))
    post_sdk = _as_map(sdk_mat.get("post_sdk_baseline"))
    deltas = {
        f"{k}_{s}": sorted((set(exit_snapshot.get(k, [])) - set(post_sdk.get(k, []))) if s == "added"
                           else (set(post_sdk.get(k, [])) - set(exit_snapshot.get(k, []))))
        for k in ("containers", "images", "volumes", "networks") for s in ("added", "removed")
    }
    clean_outer = snapshot_ok and bool(post_sdk) and not any(deltas.values())
    inner_dir = report_dir / "d12-core-image/linux-amd64"
    inner_reports: dict[str, Any] = {}
    report_provenance: dict[str, Any] = {}
    for name in ("freeze", "exploration", "cleanup"):
        doc, prov, r_err = load_safe_json_report(inner_dir / f"{name}.json", redact_fn=_redact_val)
        inner_reports[name], report_provenance[name] = doc, dict(prov)
        if r_err is not None:
            seal_errors.append(r_err)
    counts, _ = project_canonical_boundary_counts(inner_reports.get("freeze"), inner_reports.get("cleanup"))
    expl = _as_map(inner_reports.get("exploration"))
    refusals = expl.get("refusals") if isinstance(expl.get("refusals"), list) else None
    if seal_errors or not clean_outer:
        result, qualified, rc = "failed", False, 1
    elif refusals:
        result, qualified, rc = "refused", False, 1
    else:
        result, qualified, rc = ("passed", True, 0) if runner_exit_code == 0 else ("failed", False, 1)
    cleanup_map = {**deltas, "clean_against_post_sdk_baseline": clean_outer}
    sealed: dict[str, Any] = {
        "schema": SEALED_EVIDENCE_SCHEMA, "platform": EXPECTED_PLATFORM,
        "result": result, "qualified": qualified, "runner_exit_code": runner_exit_code,
        "pr_binding": state.get("pr_binding", {}), "identity_binding": state.get("identity_binding", {}),
        "native_environment": state.get("native_environment", {}),
        "sdk_materialization": {**dict(sdk_mat), "post_sdk_cleanup": cleanup_map},
        "application_builds": dict(counts), "inner_reports": inner_reports,
        "report_provenance": report_provenance, "seal_errors": seal_errors, "validation_violations": [],
    }
    violations = validate_sealed_d12_evidence(sealed, require_positive_qualification=qualified)
    sealed["validation_violations"] = violations
    if violations or seal_errors:
        sealed["qualified"], rc = False, 1
        if sealed["result"] == "passed" or seal_errors or not clean_outer:
            sealed["result"] = "failed"
    output_json.write_text(json.dumps(sealed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return sealed, rc


def run_system_hold(
    repo_root: Path, *, candidate_sha: str, candidate_tree: str,
    candidate_base_parent: str, candidate_head_parent: str, output_json: Path,
    target_arch: str = "amd64", libpq_version: object = ..., package_manifest: object = ...,
    frozen_identity_fn: Callable[[Path, str], dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], int]:
    identity = (frozen_identity_fn or d12_core_image.frozen_identity)(repo_root, f"linux/{target_arch}")
    reasons: list[str] = []
    try:
        require_release_prerequisites_resolved(
            target_arch,
            libpq_version=PSYCOPG_LIBPQ_VERSION if libpq_version is ... else libpq_version,
            package_manifest=DYNAMIC_PACKAGE_MANIFEST if package_manifest is ... else package_manifest,
        )
        result, rc = "prerequisites_resolved", 0
    except (SystemTestError, RuntimeError, ValueError) as exc:
        reasons.append(str(exc))
        result, rc = "refused_release_prerequisites_unresolved", 1
    report: dict[str, Any] = {
        "schema": SYSTEM_HOLD_REFUSAL_SCHEMA, "gate_kind": "main-system", "target_arch": target_arch,
        "result": result, "qualified": False,
        "sdk_builds_started": 0, "application_candidate_builds_started": 0,
        "managed_system_candidate_image_build_count": 0,
        "candidate_sha": candidate_sha, "candidate_tree": candidate_tree,
        "candidate_base_parent": candidate_base_parent, "candidate_head_parent": candidate_head_parent,
        "d12_source_sha256": identity["source_sha256"], "d12_recipe_sha256": identity["recipe_sha256"],
        "d12_dockerfile_sha256": identity["dockerfile_sha256"], "reasons": reasons,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report, rc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="subcommand", required=True)
    prep, seal, hold = sub.add_parser("prepare"), sub.add_parser("seal"), sub.add_parser("system-hold")
    for flag in ("--repo-root", "--expected-json", "--state-dir", "--report-dir"):
        prep.add_argument(flag, type=Path, required=True)
    prep.add_argument("--github-env", type=Path, default=None)
    for flag in ("--repo-root", "--state-dir", "--report-dir", "--output-json"):
        seal.add_argument(flag, type=Path, required=True)
    for flag in ("--repo-root", "--output-json"):
        hold.add_argument(flag, type=Path, required=True)
    for flag in ("--candidate-sha", "--candidate-tree", "--candidate-base-parent", "--candidate-head-parent"):
        hold.add_argument(flag, required=True)
    hold.add_argument("--target-arch", default="amd64")
    args = parser.parse_args(argv)
    if args.subcommand == "prepare":
        try:
            prepare_hosted_d12(args.repo_root, expected_json=args.expected_json, state_dir=args.state_dir,
                               report_dir=args.report_dir, github_env=args.github_env)
            return 0
        except HostedQualificationError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if args.subcommand == "seal":
        return seal_hosted_d12(args.repo_root, state_dir=args.state_dir, report_dir=args.report_dir,
                               output_json=args.output_json)[1]
    return run_system_hold(args.repo_root, candidate_sha=args.candidate_sha, candidate_tree=args.candidate_tree,
                           candidate_base_parent=args.candidate_base_parent,
                           candidate_head_parent=args.candidate_head_parent,
                           output_json=args.output_json, target_arch=args.target_arch)[1]


if __name__ == "__main__":
    raise SystemExit(main())
