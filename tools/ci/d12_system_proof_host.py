"""Pure host-side candidate record and system admission proof verification for Route B."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import os
from pathlib import Path
import re
import subprocess
from typing import Any, TypeGuard

from ci.d12_system_grant import (
    DEFAULT_CANDIDATE_RELPATH,
    DEFAULT_GRANT_RELPATH,
    D12SystemGrantError,
    MAX_SYSTEM_GRANT_BYTES,
    load_and_validate_system_admission_proof,
    load_and_validate_system_build_grant,
    read_regular_json_object,
)
from repomap_test_support.d12_recipe import frozen_identity
import test_sandbox_images

SYSTEM_HOLD_REFUSAL_SCHEMA = "repomap-d12-system-hold-refusal-v1"
EXPECTED_CANDIDATE_SCHEMA = "repomap-d12-hosted-candidate-v1"
EXPECTED_PLATFORM = "linux/amd64"
EXPECTED_SDK_IMAGE_TAG = "repomap-test-sandbox:py313-go125-docker294-v1"
EXPECTED_SDK_DOCKERFILE_SHA256 = "f8a8be96ac78ff32b8f2b4f6372f3d9203750a56f75ff49e0af722f5f75e3786"
EXPECTED_SDK_HELPER_SHA256 = "df616a151d062b4ade001bbd029007b2f414aa22422de63c520895663b850c5f"

_HEX_40_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX_64_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_COMMIT_KEYS = ("commit", "commit_sha", "candidate_sha", "head_sha", "base_sha")


class HostedD12EvidenceError(ValueError):
    """Raised when hosted D12 candidate or evidence records violate contract bounds."""


def _is_strict_int(val: object) -> TypeGuard[int]:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_hex(val: object, length: int) -> bool:
    if not isinstance(val, str) or len(val) != length:
        return False
    if length not in (40, 64):
        return False
    return (_HEX_40_RE if length == 40 else _HEX_64_RE).match(val) is not None


def validate_expected_candidate_record(record: object) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise HostedD12EvidenceError("candidate record must be a mapping")
    if any("commit" in str(k) or str(k) in _FORBIDDEN_COMMIT_KEYS for k in record):
        raise HostedD12EvidenceError("self-referential commit field forbidden in expected candidate record")
    if record.get("schema") != EXPECTED_CANDIDATE_SCHEMA or record.get("platform") != EXPECTED_PLATFORM:
        raise HostedD12EvidenceError("invalid schema or platform")

    d12_ctx, sdk = record.get("d12_context"), record.get("sdk_sandbox")
    if not isinstance(d12_ctx, Mapping) or not isinstance(sdk, Mapping):
        raise HostedD12EvidenceError("missing or invalid d12_context or sdk_sandbox")

    source_sha = d12_ctx.get("source_sha256")
    recipe_sha = d12_ctx.get("recipe_sha256")
    dockerfile_sha = d12_ctx.get("dockerfile_sha256")
    for name, val in (
        ("source_sha256", source_sha),
        ("recipe_sha256", recipe_sha),
        ("dockerfile_sha256", dockerfile_sha),
    ):
        if not _is_hex(val, 64):
            raise HostedD12EvidenceError(f"invalid {name}: must be 64-hex lowercase")

    file_count = d12_ctx.get("context_file_count")
    if not _is_strict_int(file_count) or file_count <= 0:
        raise HostedD12EvidenceError("invalid context_file_count")

    if (
        sdk.get("image_tag") != EXPECTED_SDK_IMAGE_TAG
        or sdk.get("sdk_dockerfile_sha256") != EXPECTED_SDK_DOCKERFILE_SHA256
        or sdk.get("sdk_helper_sha256") != EXPECTED_SDK_HELPER_SHA256
        or not _is_hex(sdk.get("sdk_recipe_sha256"), 64)
    ):
        raise HostedD12EvidenceError("sdk_sandbox metadata mismatch")

    digests = [
        source_sha,
        recipe_sha,
        dockerfile_sha,
        sdk.get("sdk_dockerfile_sha256"),
        sdk.get("sdk_helper_sha256"),
        sdk.get("sdk_recipe_sha256"),
    ]
    if len(set(digests)) != len(digests):
        raise HostedD12EvidenceError("hash domains must be distinct")

    return {**dict(record), "d12_context": dict(d12_ctx), "sdk_sandbox": dict(sdk)}


def _default_uname() -> tuple[str, str]:
    u = os.uname()
    return u.sysname, u.machine


def _compute_live_sdk_recipe_sha256(repo_root: Path) -> str:
    dockerfile = (repo_root / "tools/test_sandbox/Dockerfile").read_bytes()
    helper = (repo_root / "tools/native_apt_prerequisites.py").read_bytes()
    return test_sandbox_images.sandbox_recipe(
        {"Dockerfile": dockerfile, "apt_prerequisites.py": helper}
    )


def _git_rev(
    repo_root: Path,
    rev: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    res = runner(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", rev],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    val = (res.stdout or "").strip().lower()
    if res.returncode != 0 or len(val) != 40 or any(c not in "0123456789abcdef" for c in val):
        raise D12SystemGrantError(f"git rev-parse {rev} failed")
    return val


def validate_host_system_event_and_git(
    repo_root: Path,
    *,
    grant: Mapping[str, Any],
    environ: Mapping[str, str],
    uname_fn: Callable[[], tuple[str, str]] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    eff_uname = _default_uname if uname_fn is None else uname_fn
    eff_runner = subprocess.run if runner is None else runner
    if environ.get("GITHUB_ACTIONS") != "true":
        raise D12SystemGrantError("GITHUB_ACTIONS must be 'true' for Route B system admission")
    if environ.get("GITHUB_EVENT_NAME") != "pull_request":
        raise D12SystemGrantError("GITHUB_EVENT_NAME must be 'pull_request'")
    if environ.get("GITHUB_REPOSITORY") != grant["repository"]:
        raise D12SystemGrantError(f"GITHUB_REPOSITORY mismatch: {environ.get('GITHUB_REPOSITORY')!r}")
    if environ.get("GITHUB_BASE_REF") != grant["base_ref"]:
        raise D12SystemGrantError(f"GITHUB_BASE_REF={environ.get('GITHUB_BASE_REF')!r} != {grant['base_ref']!r}")
    if environ.get("GITHUB_HEAD_REF") != grant["head_ref"]:
        raise D12SystemGrantError(f"GITHUB_HEAD_REF={environ.get('GITHUB_HEAD_REF')!r} != {grant['head_ref']!r}")
    if environ.get("GITHUB_RUN_NUMBER") != str(grant["workflow_ordinal"]):
        raise D12SystemGrantError(
            f"GITHUB_RUN_NUMBER={environ.get('GITHUB_RUN_NUMBER')!r} != {grant['workflow_ordinal']!r}"
        )
    if environ.get("GITHUB_RUN_ATTEMPT") != str(grant["workflow_attempt"]):
        raise D12SystemGrantError(
            f"GITHUB_RUN_ATTEMPT={environ.get('GITHUB_RUN_ATTEMPT')!r} != {grant['workflow_attempt']!r}"
        )
    run_id = str(environ.get("GITHUB_RUN_ID", "") or "").strip()
    if not run_id.isdigit():
        raise D12SystemGrantError("GITHUB_RUN_ID must be a digits-only string")
    wf_ref = str(environ.get("GITHUB_WORKFLOW_REF", "") or "").strip()
    wf_lhs, wf_sep, wf_rev = wf_ref.partition("@")
    exp_wf = f"{grant['repository']}/{grant['workflow_path']}"
    if wf_sep != "@" or not wf_rev.strip() or wf_lhs != exp_wf:
        raise D12SystemGrantError(
            f"GITHUB_WORKFLOW_REF {wf_ref!r} does not match {exp_wf!r}@<ref>"
        )
    kernel, machine = eff_uname()
    runner_os = str(environ.get("RUNNER_OS", "") or "").strip()
    runner_arch = str(environ.get("RUNNER_ARCH", "") or "").strip()
    if (runner_os, runner_arch, kernel, machine) != ("Linux", "X64", "Linux", "x86_64"):
        raise D12SystemGrantError(
            f"native Linux/X64/x86_64 host required, got {runner_os}/{runner_arch} {kernel}/{machine}"
        )
    event_path_raw = str(environ.get("GITHUB_EVENT_PATH", "") or "").strip()
    if not event_path_raw:
        raise D12SystemGrantError("GITHUB_EVENT_PATH is required")
    event, _eb, raw_event_sha256 = read_regular_json_object(
        Path(event_path_raw), label="GitHub event payload", max_bytes=256 * 1024
    )
    if event.get("action") != grant["event_action"]:
        raise D12SystemGrantError(
            f"GitHub event action {event.get('action')!r} != {grant['event_action']!r}"
        )
    pr = event.get("pull_request")
    if not isinstance(pr, Mapping):
        raise D12SystemGrantError("GitHub event pull_request object missing")
    ev_num, pr_num = event.get("number"), pr.get("number")
    if (
        not _is_strict_int(ev_num)
        or not _is_strict_int(pr_num)
        or ev_num != grant["pull_request"]
        or pr_num != grant["pull_request"]
    ):
        raise D12SystemGrantError(f"event/pull_request.number {ev_num!r}/{pr_num!r} != {grant['pull_request']!r}")
    if pr.get("draft") is not True:
        raise D12SystemGrantError("CLOE-CONFIG1 draft admission requires pull_request.draft is True")
    base_blk, head_blk = pr.get("base"), pr.get("head")
    if not isinstance(base_blk, Mapping) or not isinstance(head_blk, Mapping):
        raise D12SystemGrantError("pull_request base/head blocks missing")
    if base_blk.get("ref") != grant["base_ref"] or head_blk.get("ref") != grant["head_ref"]:
        raise D12SystemGrantError("pull_request base.ref/head.ref mismatch")
    base_repo, head_repo = base_blk.get("repo"), head_blk.get("repo")
    if not isinstance(base_repo, Mapping) or not isinstance(head_repo, Mapping):
        raise D12SystemGrantError("pull_request base.repo/head.repo missing")
    if (
        base_repo.get("full_name") != grant["repository"]
        or head_repo.get("full_name") != grant["repository"]
        or bool(base_repo.get("fork"))
        or bool(head_repo.get("fork"))
    ):
        raise D12SystemGrantError("fork or foreign repository pull request refused")
    base_sha, head_sha = base_blk.get("sha"), head_blk.get("sha")
    if grant["event_action"] != "opened" or "before" in event or "after" in event:
        raise D12SystemGrantError("opening payload must omit synchronize before/after fields")
    before_sha, after_sha = base_sha, head_sha
    for sha_label, sha_val in (
        ("pull_request.base.sha", base_sha),
        ("pull_request.head.sha", head_sha),
        ("event.before", before_sha),
        ("event.after", after_sha),
    ):
        if not _is_hex(sha_val, 40):
            raise D12SystemGrantError(f"{sha_label} must be a 40-hex lowercase string")
    if base_sha != grant["base"]:
        raise D12SystemGrantError(f"pull_request.base.sha {base_sha!r} != grant base {grant['base']!r}")
    if before_sha != grant["before"]:
        raise D12SystemGrantError(f"event before {before_sha!r} != grant before {grant['before']!r}")
    if after_sha != head_sha or after_sha == before_sha:
        raise D12SystemGrantError(
            "opening event head SHA must equal head.sha and advance past before"
        )
    head_commit = _git_rev(repo_root, "HEAD", runner=eff_runner)
    tree_sha = _git_rev(repo_root, "HEAD^{tree}", runner=eff_runner)
    base_parent = _git_rev(repo_root, "HEAD^1", runner=eff_runner)
    head_parent = _git_rev(repo_root, "HEAD^2", runner=eff_runner)
    third = eff_runner(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD^3"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if third.returncode == 0:
        raise D12SystemGrantError("HEAD must be a two-parent merge commit")
    gh_sha = environ.get("GITHUB_SHA")
    if not _is_hex(gh_sha, 40) or gh_sha != head_commit:
        raise D12SystemGrantError("GITHUB_SHA is required and must match git HEAD")
    if base_parent != base_sha or head_parent != after_sha:
        raise D12SystemGrantError("git HEAD^1/HEAD^2 do not match pull_request base.sha/after")
    if head_commit in {base_parent, head_parent}:
        raise D12SystemGrantError("merge commit HEAD must be distinct from parents")
    return {
        "after": after_sha,
        "raw_event_sha256": raw_event_sha256,
        "candidate_sha": head_commit,
        "candidate_tree": tree_sha,
        "candidate_base_parent": base_parent,
        "candidate_head_parent": head_parent,
        "run_id": run_id,
        "native_host": {
            "runner_os": runner_os,
            "runner_arch": runner_arch,
            "host_kernel": kernel,
            "host_arch": machine,
        },
    }


def verify_host_proof_against_live_environment(
    args: Any,
    *,
    raw_argv: list[str] | None = None,
    repo_root: Path,
    env: Mapping[str, str] | None = None,
    uname_fn: Callable[[], tuple[str, str]] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    frozen_identity_fn: Callable[..., dict[str, Any]] | None = None,
    grant_path: Path | None = None,
    expected_candidate_path: Path | None = None,
) -> dict[str, Any]:
    raw_proof_arg = getattr(args, "d12_system_proof_json", None)
    if raw_proof_arg is None and raw_argv:
        for idx, tok in enumerate(raw_argv):
            if tok == "--d12-system-proof-json" and idx + 1 < len(raw_argv):
                raw_proof_arg = raw_argv[idx + 1]
                break
            if tok.startswith("--d12-system-proof-json="):
                raw_proof_arg = tok.partition("=")[2]
                break
    if not isinstance(raw_proof_arg, str) or not raw_proof_arg.strip():
        raise D12SystemGrantError(
            "containerized system suite requires --d12-system-proof-json before sandbox image build"
        )
    environ = os.environ if env is None else env
    eff_uname = _default_uname if uname_fn is None else uname_fn
    eff_runner = subprocess.run if runner is None else runner
    eff_frozen = frozen_identity if frozen_identity_fn is None else frozen_identity_fn
    cand_file = expected_candidate_path or (repo_root / DEFAULT_CANDIDATE_RELPATH)
    grant_file = grant_path or (repo_root / DEFAULT_GRANT_RELPATH)
    cand_raw, _cb, cand_sha = read_regular_json_object(
        cand_file, label="expected candidate JSON", max_bytes=MAX_SYSTEM_GRANT_BYTES
    )
    try:
        expected_cand = validate_expected_candidate_record(cand_raw)
    except HostedD12EvidenceError as exc:
        raise D12SystemGrantError(f"invalid expected candidate JSON: {exc}") from exc
    frozen = eff_frozen(repo_root, "linux/amd64")
    grant, grant_sha = load_and_validate_system_build_grant(
        grant_file, expected_candidate=expected_cand, frozen_identity=frozen
    )
    live_sdk_sha = _compute_live_sdk_recipe_sha256(repo_root)
    if live_sdk_sha != grant["sdk_recipe_sha256"]:
        raise D12SystemGrantError("live SDK recipe SHA256 disagrees with system build grant")
    proof_path = Path(raw_proof_arg).expanduser()
    if not proof_path.is_absolute():
        proof_path = repo_root / proof_path
    proof, _pb, _ps = load_and_validate_system_admission_proof(
        proof_path,
        grant=grant,
        grant_sha256=grant_sha,
        expected_candidate_sha256=cand_sha,
        require_mode_0600=True,
        require_parent_mode_0700=True,
    )
    live = validate_host_system_event_and_git(
        repo_root, grant=grant, environ=environ, uname_fn=eff_uname, runner=eff_runner
    )
    for k in (
        "after",
        "raw_event_sha256",
        "candidate_sha",
        "candidate_tree",
        "candidate_base_parent",
        "candidate_head_parent",
        "run_id",
        "native_host",
    ):
        if proof.get(k) != live.get(k):
            raise D12SystemGrantError(f"system admission proof {k} disagrees with live host")
    for attr, expected_val in (
        ("candidate_sha", proof["candidate_sha"]),
        ("candidate_tree", proof["candidate_tree"]),
        ("candidate_base_parent", proof["candidate_base_parent"]),
        ("candidate_head_parent", proof["candidate_head_parent"]),
        ("approval_id", proof["approval_id"]),
        ("pr_number", str(proof["pull_request"])),
        ("repository", proof["repository"]),
    ):
        supplied = getattr(args, attr, None)
        if supplied is not None and str(supplied).strip() != expected_val:
            raise D12SystemGrantError(f"runner argument --{attr.replace('_', '-')} mismatch against proof")
    return proof
