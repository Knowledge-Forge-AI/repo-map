"""Candidate tree identity, target architecture, and Route B session binding helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
from typing import Any

from ci.d12_hosted_evidence import HostedD12EvidenceError, validate_expected_candidate_record
from ci.d12_system_grant import (
    DEFAULT_CANDIDATE_RELPATH,
    DEFAULT_GRANT_RELPATH,
    D12SystemGrantError,
    load_and_validate_system_admission_proof,
    load_and_validate_system_build_grant,
)
from tools.system.config import SystemTestConfig, SystemTestError
from tools.system.d12_candidate_assessment import (
    CTX_IDENTITY_KEYS as CTX_IDENTITY_KEYS,
    normalize_candidate_manifest as normalize_candidate_manifest,
    verify_preflight_matches_manifest as verify_preflight_matches_manifest,
)
from tools.system.d12_system_reports import write_exclusive_0600_json as write_exclusive_0600_json



def get_current_tree_sha(repo_root: Path) -> str:
    """Materialize the exact non-ignored worktree tree without touching the real index."""
    obj_res = subprocess.run(
        ("git", "rev-parse", "--git-path", "objects"),
        cwd=repo_root, capture_output=True, text=True, check=False,
    )
    if obj_res.returncode != 0 or not obj_res.stdout.strip():
        raise SystemTestError(f"unable to locate repository object database: {obj_res.stderr.strip()}")
    repo_objs = Path(obj_res.stdout.strip())
    if not repo_objs.is_absolute():
        repo_objs = (repo_root / repo_objs).resolve()

    with tempfile.TemporaryDirectory(prefix="repomap-system-index-") as tmpdir:
        tmp_objs = Path(tmpdir) / "objects"
        tmp_objs.mkdir()
        env = {
            **os.environ,
            "GIT_INDEX_FILE": str(Path(tmpdir) / "index"),
            "GIT_OBJECT_DIRECTORY": str(tmp_objs),
        }
        alt = env.get("GIT_ALTERNATE_OBJECT_DIRECTORIES")
        env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = os.pathsep.join(v for v in (str(repo_objs), alt) if v)
        for cmd in (("git", "read-tree", "HEAD"), ("git", "add", "-A", "--", "."), ("git", "write-tree")):
            res = subprocess.run(cmd, cwd=repo_root, env=env, capture_output=True, text=True, check=False)
            if res.returncode != 0:
                raise SystemTestError(f"unable to determine candidate tree SHA: {res.stderr.strip()}")
        return res.stdout.strip()


def resolve_target_arch(machine: str | None = None) -> str:
    raw = (machine if machine is not None else platform.machine()).lower()
    return "arm64" if raw in ("arm64", "aarch64") else "amd64"


def compute_session_binding_digest(
    *,
    proof: Mapping[str, Any],
    grant: Mapping[str, Any],
    expected_candidate: Mapping[str, Any],
    frozen_identity: Mapping[str, Any],
    proof_sha256: str,
    grant_sha256: str,
    expected_candidate_sha256: str,
) -> str:
    doc = [
        dict(proof), dict(grant), dict(expected_candidate), dict(frozen_identity),
        proof_sha256, grant_sha256, expected_candidate_sha256,
    ]
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def verify_live_git_and_config_identity(
    *,
    repo_root: Path,
    config: SystemTestConfig,
    proof: Mapping[str, Any],
    tree_sha_fn: Callable[[Path], str] = get_current_tree_sha,
    run_git_fn: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    live_tree = tree_sha_fn(repo_root)
    if live_tree != config.candidate_tree_sha or proof["candidate_tree"] != live_tree:
        raise SystemTestError("inner D12 system proof candidate_tree disagrees with live checkout")
    for key, rev in (
        ("candidate_sha", "HEAD"), ("candidate_tree", "HEAD^{tree}"),
        ("candidate_base_parent", "HEAD^1"), ("candidate_head_parent", "HEAD^2"),
    ):
        res = run_git_fn(["git", "rev-parse", rev], cwd=repo_root, capture_output=True, text=True, check=False)
        if res.returncode != 0 or res.stdout.strip() != proof[key]:
            raise SystemTestError(f"inner D12 system proof {key} disagrees with live Git {rev}")
    if (
        config.candidate_commit_sha, config.candidate_base_parent, config.candidate_head_parent,
        str(config.pr_number), config.approval_id, config.repository,
    ) != (
        proof["candidate_sha"], proof["candidate_base_parent"], proof["candidate_head_parent"],
        str(proof["pull_request"]), proof["approval_id"], proof["repository"],
    ):
        raise SystemTestError("inner D12 system config identities disagree with validated proof")


def load_and_verify_session_authority(
    *,
    repo_root: Path,
    config: SystemTestConfig,
    proof_json_arg: object,
    target_arch_fn: Callable[[], str],
    tree_sha_fn: Callable[[Path], str],
    frozen_identity_fn: Callable[[Path, str], dict[str, Any]],
    run_git_fn: Callable[..., subprocess.CompletedProcess[str]],
    grant_path: Path | None,
    expected_candidate_path: Path | None,
) -> tuple[Path, dict[str, Any], str, dict[str, Any], str, dict[str, Any], str, dict[str, Any]]:
    if not isinstance(proof_json_arg, str) or not proof_json_arg.strip():
        raise SystemTestError("hosted D12 system gate requires --d12-system-proof-json inside the runner")
    if config.report_dir is None or target_arch_fn() != "amd64":
        raise SystemTestError("D12 system session requires a report_dir and target_arch='amd64'")
    cand_file = expected_candidate_path or (repo_root / DEFAULT_CANDIDATE_RELPATH)
    grant_file = grant_path or (repo_root / DEFAULT_GRANT_RELPATH)
    try:
        cand_bytes = cand_file.read_bytes()
        frozen = frozen_identity_fn(repo_root, "linux/amd64")
        cand_sha = hashlib.sha256(cand_bytes).hexdigest()
        expected_cand = validate_expected_candidate_record(json.loads(cand_bytes.decode("utf-8")))
        grant, grant_sha = load_and_validate_system_build_grant(
            grant_file, expected_candidate=expected_cand, frozen_identity=frozen
        )
        p_path = Path(proof_json_arg).expanduser()
        p_path = p_path if p_path.is_absolute() else (repo_root / p_path)
        proof, _raw, proof_sha = load_and_validate_system_admission_proof(
            p_path, grant=grant, grant_sha256=grant_sha, expected_candidate_sha256=cand_sha,
            require_mode_0600=True, require_parent_mode_0700=False,
        )
    except (OSError, ValueError, HostedD12EvidenceError, D12SystemGrantError) as exc:
        raise SystemTestError(f"inner D12 system proof/grant validation failed: {exc}") from exc
    verify_live_git_and_config_identity(
        repo_root=repo_root, config=config, proof=proof, tree_sha_fn=tree_sha_fn, run_git_fn=run_git_fn
    )
    return p_path, proof, proof_sha, grant, grant_sha, expected_cand, cand_sha, frozen
