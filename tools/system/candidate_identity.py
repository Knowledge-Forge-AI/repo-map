"""Candidate tree identity, target architecture, and Route B session binding helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import re
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
from repomap_kg.runtime.release import DebPackage, POSTGRES_RELEASE_IMAGE, PlatformPackages
from repomap_kg.runtime.release_manifest import (
    D12_CANDIDATE_LIBPQ_VERSION,
    D12_CANDIDATE_PACKAGE_MANIFEST,
)
from tools.system.config import SystemTestConfig, SystemTestError

CTX_IDENTITY_KEYS: tuple[str, str, str, str] = (
    "source_sha256",
    "recipe_sha256",
    "dockerfile_sha256",
    "context_file_count",
)


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


def write_exclusive_0600_json(path: Path, payload: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise SystemTestError(f"one-use D12 system build intent already exists: {path}") from exc
    except OSError as exc:
        msg = "must not be a symlink" if exc.errno == errno.ELOOP else f"cannot create ({exc})"
        raise SystemTestError(f"D12 system build intent {msg}: {path}") from exc
    for t_fd, sync_only in ((fd, False), (os.open(path.parent, os.O_RDONLY), True)):
        try:
            if not sync_only:
                os.fchmod(t_fd, 0o600)
                os.write(t_fd, raw)
            os.fsync(t_fd)
        finally:
            os.close(t_fd)
    return hashlib.sha256(raw).hexdigest()


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


def normalize_candidate_manifest(manifest: Mapping[str, Any]) -> PlatformPackages:
    try:
        return PlatformPackages(
            str(manifest["postgres_config_digest"]),
            (str(manifest["pgdg_source"][0]), str(manifest["pgdg_source"][1])),
            (str(manifest["pgdg_keyring"][0]), str(manifest["pgdg_keyring"][1])),
            tuple(str(x) for x in manifest["key_fingerprints"]),
            str(manifest["libpq_path"]),
            str(manifest["libpq_sha256"]),
            str(manifest["libpq5_version"]),
            tuple(DebPackage(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in manifest["builder"]),
            tuple(DebPackage(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in manifest["closure"]),
            tuple(str(x) for x in manifest["lib_dynload"]),
        )
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise SystemTestError(f"malformed preflight candidate manifest: {exc}") from exc


def verify_preflight_matches_manifest(
    preflight: Mapping[str, Any],
    *,
    proof: Mapping[str, Any],
    libpq_version: int = D12_CANDIDATE_LIBPQ_VERSION,
    amd64_packages: PlatformPackages | None = None,
) -> None:
    pkg = D12_CANDIDATE_PACKAGE_MANIFEST["amd64"] if amd64_packages is None else amd64_packages
    if "build" in preflight or "image_cleanup" in preflight:
        raise SystemTestError("D12 same-daemon preflight is zero-build exploration and must not claim build/image")
    if preflight.get("result") != "observed" or preflight.get("refusals") or preflight.get("failures"):
        raise SystemTestError(f"D12 same-daemon preflight exploration failed: {preflight.get('result')!r}")
    avail = preflight.get("availability")
    if not isinstance(avail, Mapping) or avail.get("execution") != "native":
        raise SystemTestError(f"D12 same-daemon preflight requires native execution: {avail!r}")
    bases = preflight.get("bases")
    pg_base = bases.get(POSTGRES_RELEASE_IMAGE) if isinstance(bases, Mapping) else None
    pg_base_id = pg_base.get("id") if isinstance(pg_base, Mapping) else None
    if not isinstance(pg_base_id, str) or not pg_base_id.startswith("sha256:"):
        raise SystemTestError(f"D12 same-daemon preflight missing verified PostgreSQL base image ID: {bases!r}")
    cleanup = preflight.get("cleanup")
    if (
        not isinstance(cleanup, Mapping) or cleanup.get("server") != "removed"
        or cleanup.get("containers") != "baseline_verified"
        or not isinstance(cleanup.get("zero_build"), Mapping)
        or any(v != 0 for v in cleanup["zero_build"].values())
    ):
        raise SystemTestError(f"D12 same-daemon preflight cleanup/zero-build custody failed: {cleanup!r}")
    ident, d12_ctx, rel_man = preflight.get("identity"), proof.get("d12_context"), proof.get("release_manifest")
    if not isinstance(ident, Mapping) or not isinstance(d12_ctx, Mapping) or not isinstance(rel_man, Mapping):
        raise SystemTestError("D12 same-daemon preflight missing identity, d12_context, or release_manifest")
    if any(ident.get(k) != d12_ctx.get(k) for k in CTX_IDENTITY_KEYS):
        raise SystemTestError(f"D12 same-daemon preflight identity mismatch against d12_context: {ident!r}")
    if (
        rel_man.get("libpq_version") != libpq_version or rel_man.get("libpq5_version") != pkg.libpq5_version
        or rel_man.get("libpq_sha256") != pkg.libpq_sha256
        or rel_man.get("postgres_config_digest") != pkg.postgres_config_digest
    ):
        raise SystemTestError("D12 same-daemon preflight proof.release_manifest mismatch against release_manifest")
    steps = preflight.get("steps")
    if not isinstance(steps, Mapping) or not isinstance(steps.get("candidate"), Mapping):
        raise SystemTestError("D12 same-daemon preflight missing steps.candidate")
    cand_step, rt_step = steps["candidate"], steps.get("libpq_runtime")
    if cand_step.get("valid") is not True or cand_step.get("written_to_source") is not False:
        raise SystemTestError("D12 same-daemon preflight steps.candidate is not a valid unwritten manifest")
    if normalize_candidate_manifest(cand_step.get("manifest") or {}) != pkg or (
        cand_step.get("libpq_version") != libpq_version
    ):
        raise SystemTestError("D12 same-daemon preflight candidate manifest mismatch against release_manifest")
    if not isinstance(rt_step, Mapping) or rt_step.get("api") != libpq_version:
        raise SystemTestError("D12 same-daemon preflight libpq_runtime.api mismatch")
    lib_blk = rt_step.get("library")
    if (
        not isinstance(lib_blk, Mapping) or lib_blk.get("path") != pkg.libpq_path
        or lib_blk.get("sha256") != pkg.libpq_sha256 or lib_blk.get("package") != "libpq5"
        or lib_blk.get("version") != pkg.libpq5_version or lib_blk.get("architecture") not in (None, "amd64")
    ):
        raise SystemTestError("D12 same-daemon preflight libpq_runtime.library mismatch")
    if not isinstance(srv_inv := preflight.get("server_inventory"), Mapping):
        raise SystemTestError("D12 same-daemon preflight missing server_inventory")
    srv_libs = {
        (f.get("resolved"), f.get("sha256")) for f in (srv_inv.get("files") or ())
        if isinstance(f, Mapping) and f.get("role") == "libpq" and f.get("owner") == "libpq5"
    }
    srv_vers = [
        tuple(map(int, m)) for r in (srv_inv.get("packages") or ())
        if isinstance(r, (list, tuple)) and len(r) >= 2 and r[0] == "libpq5"
        for m in re.findall(r"^(\d+)\.(\d+)", str(r[1]))
    ]
    if srv_libs != {(pkg.libpq_path, pkg.libpq_sha256)} or [divmod(libpq_version, 10000)] != srv_vers:
        raise SystemTestError("D12 same-daemon preflight server_inventory libpq5 oracle mismatch")


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
