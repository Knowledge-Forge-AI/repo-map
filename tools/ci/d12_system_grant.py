"""Stdlib-only Route B one-use D12 system build grant and host admission proof contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, TypeGuard

from ci.d12_system_grant_io import (
    D12SystemGrantError as D12SystemGrantError,
    loads_strict_json_object as loads_strict_json_object,
    read_regular_json_object as read_regular_json_object,
)

from repomap_kg.runtime.release import PRODUCT_MINIMUM_LIBPQ_VERSION
from repomap_kg.runtime.release_manifest import D12_CANDIDATE_LIBPQ_VERSION, D12_CANDIDATE_PACKAGE_MANIFEST

SYSTEM_BUILD_GRANT_SCHEMA = "repomap-d12-system-build-grant-v1"
SYSTEM_ADMISSION_PROOF_SCHEMA = "repomap-d12-system-admission-proof-v1"
EXPECTED_PHASE_ID = "REPOMAP-CLOE-RUNTIME1"
EXPECTED_WORKFLOW_PATH = ".github/workflows/repomap-release-qualification.yml"
EXPECTED_SYSTEM_OWNER, EXPECTED_REPOSITORY = "main-system-gate", "Knowledge-Forge-AI/repo-map"
EXPECTED_BEFORE_SHA = "bec838a210f3ffea84986ae85986e4081b2e8291"
EXPECTED_BASE_SHA = "5ad00d162ad8a04430874275246a53227578c533"
EXPECTED_APPROVAL_SHA256 = "94d71498c0cccaea469394b9ab7b76677659daba16dd99eff5300acf90e4e831"
EXPECTED_LEDGER_BEFORE_SHA256 = "2129c892344ea4e276c0fcc01059fae7871493a36e27c1ae2bfdb51f35edc383"
SPENT_CI69_NONCE = "68920c8be2054bddaefba6ff1761b2e5"
SPENT_CI69_RESERVATION_SHA256 = "60d67477702e81125b5fba737c182965a78bcb6865c4e267adb0d064a71ac595"
SPENT_CI70_NONCE = "2ca8d5a3ad7645798437728db064e8d4"
SPENT_CI70_RESERVATION_SHA256 = "aba49e31a10db6bb6326e48f0fd681ede763e3be0fa86f37ddda1bae0df76a91"
SPENT_CI71_NONCE = "549ee11fd8a44b4f8723030412032fa3"
SPENT_CI71_RESERVATION_SHA256 = "159885801ce51461100eaf345163f02fb2b7ebc91eef71ff146acac66bc131be"
SPENT_CI72_NONCE = "1e9709f9ba0d46b28064fe7b0f9b3cbb"
SPENT_CI72_RESERVATION_SHA256 = "c0072c52ae05239180452e7b37b2d76ddf4ee78811facfa3cc00aa2ed2e3b692"
SPENT_CI85_NONCE = "e2833d583de847a7859fb5250d5f37c6"
SPENT_CI85_RESERVATION_SHA256 = "04c66536b5f655be479934d1086bec6895ac9015bdcf3da96c197a7f9d28bc4f"
SPENT_CI86_NONCE = "3777470657bc4361b42b3e4de8ba8586"
SPENT_CI86_RESERVATION_SHA256 = "dfa6d5670c156ce86a43fb45edf59d6f432bad71f11c139a09b2de864c6e5ba6"
SPENT_CI87_NONCE = "8f2ad7e4086946c9818c8ba1bad4c4f7"
SPENT_CI87_RESERVATION_SHA256 = "ac70c59663ff37177c5e072066d38d93d09caf7aca1aa8b0e90074dfaa849273"
SPENT_CI91_NONCE = "60454e3a42db44d697f22e2d9654c1ba"
SPENT_CI91_RESERVATION_SHA256 = "8e43691e6a1e36030ceee05dcee444cfcd2b97005ff535e61f3cfcd4b235badf"
SPENT_CI92_NONCE = "ba621a38a1f74b6296f9d29bb703aeac"
SPENT_CI92_RESERVATION_SHA256 = "d3beeb1e8c29d47d05730786772f2a2807fa89b934ca315d96737860f921436d"
DEFAULT_GRANT_RELPATH = Path("tools/ci/d12_system_build_grant.json")
DEFAULT_CANDIDATE_RELPATH = Path("tools/ci/d12_hosted_candidate.json")
MAX_SYSTEM_GRANT_BYTES = MAX_SYSTEM_PROOF_BYTES = 16384
_HEX32_RE = re.compile(r"[0-9a-f]{32}")
_HEX40_RE = re.compile(r"[0-9a-f]{40}")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
GRANT_TOP_LEVEL_KEYS = frozenset({
    "schema", "nonce", "reservation_sha256", "repository", "workflow_path",
    "pull_request", "event_action", "head_ref", "base_ref", "before", "base",
    "workflow_ordinal", "workflow_attempt", "platform", "owner",
    "maximum_total", "maximum_per_platform", "approval_sha256",
    "ledger_before_sha256", "sdk_recipe_sha256", "d12_context"})
D12_CONTEXT_KEYS = frozenset({
    "source_sha256", "recipe_sha256", "dockerfile_sha256", "context_file_count"})
PROOF_TOP_LEVEL_KEYS = frozenset({
    "schema", "nonce", "reservation_sha256", "grant_sha256",
    "expected_candidate_sha256", "raw_event_sha256", "repository", "workflow_path", "owner",
    "platform", "pull_request", "approval_id", "event_action", "head_ref",
    "base_ref", "before", "after", "base", "candidate_sha", "candidate_tree",
    "candidate_base_parent", "candidate_head_parent", "workflow_ordinal",
    "workflow_attempt", "run_id", "native_host", "sdk_recipe_sha256",
    "d12_context", "release_manifest"})


def _is_strict_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_hex32(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX32_RE.fullmatch(value))


def _is_hex40(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX40_RE.fullmatch(value))


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and bool(_HEX64_RE.fullmatch(value))


def _validate_d12_context(ctx: object, *, sdk_recipe_sha256: str) -> dict[str, Any]:
    if not isinstance(ctx, Mapping) or set(ctx.keys()) != D12_CONTEXT_KEYS:
        raise D12SystemGrantError("d12_context keys do not match closed schema")
    src, rec, df = ctx.get("source_sha256"), ctx.get("recipe_sha256"), ctx.get("dockerfile_sha256")
    cnt = ctx.get("context_file_count")
    if not (_is_hex64(src) and _is_hex64(rec) and _is_hex64(df)):
        raise D12SystemGrantError("d12_context digests must be 64 lowercase hex")
    if len({src, rec, df, sdk_recipe_sha256}) != 4:
        raise D12SystemGrantError("d12_context and sdk_recipe_sha256 digests must be distinct")
    if not _is_strict_int(cnt) or int(cnt) <= 0:
        raise D12SystemGrantError("d12_context.context_file_count must be positive int")
    return dict(ctx)


def validate_system_build_grant(
    record: Mapping[str, Any], *,
    expected_candidate: Mapping[str, Any] | None = None,
    frozen_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(record, Mapping) or set(record.keys()) != GRANT_TOP_LEVEL_KEYS:
        raise D12SystemGrantError("system build grant keys do not match closed schema")
    for key, expected in (
        ("schema", SYSTEM_BUILD_GRANT_SCHEMA), ("repository", EXPECTED_REPOSITORY),
        ("workflow_path", EXPECTED_WORKFLOW_PATH), ("event_action", "synchronize"),
        ("head_ref", "staging"), ("base_ref", "main"), ("platform", "linux/amd64"),
        ("owner", EXPECTED_SYSTEM_OWNER),
    ):
        if record.get(key) != expected:
            raise D12SystemGrantError(f"system build grant {key}={record.get(key)!r} != {expected!r}")
    for key, expected_int in (
        ("pull_request", 23), ("workflow_ordinal", 93), ("workflow_attempt", 1),
        ("maximum_total", 10), ("maximum_per_platform", 10),
    ):
        val = record.get(key)
        if not _is_strict_int(val) or val != expected_int:
            raise D12SystemGrantError(f"system build grant {key} must be strict int {expected_int}")
    if not _is_hex32(record.get("nonce")):
        raise D12SystemGrantError("system build grant nonce must be 32 lowercase hex")
    for sha_key in ("reservation_sha256", "approval_sha256", "ledger_before_sha256", "sdk_recipe_sha256"):
        if not _is_hex64(record.get(sha_key)):
            raise D12SystemGrantError(f"system build grant {sha_key} must be 64 lowercase hex")
    if record["nonce"] in (SPENT_CI69_NONCE, SPENT_CI70_NONCE, SPENT_CI71_NONCE, SPENT_CI72_NONCE, SPENT_CI85_NONCE, SPENT_CI86_NONCE, SPENT_CI87_NONCE, SPENT_CI91_NONCE, SPENT_CI92_NONCE) or record["reservation_sha256"] in (
        SPENT_CI69_RESERVATION_SHA256, SPENT_CI70_RESERVATION_SHA256, SPENT_CI71_RESERVATION_SHA256, SPENT_CI72_RESERVATION_SHA256, SPENT_CI85_RESERVATION_SHA256, SPENT_CI86_RESERVATION_SHA256, SPENT_CI87_RESERVATION_SHA256, SPENT_CI91_RESERVATION_SHA256, SPENT_CI92_RESERVATION_SHA256):
        raise D12SystemGrantError("system build grant reuses spent CI69/CI70/CI71/CI72/CI85/CI86/CI87/CI91/CI92 nonce or reservation")
    before, base = record.get("before"), record.get("base")
    if not (_is_hex40(before) and _is_hex40(base)) or before == base:
        raise D12SystemGrantError("system build grant synchronize before/base must be distinct 40-hex")
    for pin_k, pin_v in (
        ("before", EXPECTED_BEFORE_SHA), ("base", EXPECTED_BASE_SHA),
        ("approval_sha256", EXPECTED_APPROVAL_SHA256), ("ledger_before_sha256", EXPECTED_LEDGER_BEFORE_SHA256),
    ):
        if record.get(pin_k) != pin_v:
            raise D12SystemGrantError(f"system build grant {pin_k} does not match pinned CLOE-RUNTIME1 CI93 authority")
    sdk_sha = str(record["sdk_recipe_sha256"])
    d12_ctx = _validate_d12_context(record.get("d12_context"), sdk_recipe_sha256=sdk_sha)
    if expected_candidate is not None:
        exp_ctx, exp_sdk = expected_candidate.get("d12_context"), expected_candidate.get("sdk_sandbox")
        if not isinstance(exp_ctx, Mapping) or dict(d12_ctx) != dict(exp_ctx):
            raise D12SystemGrantError("system build grant d12_context disagrees with d12_hosted_candidate.json")
        if not isinstance(exp_sdk, Mapping) or sdk_sha != exp_sdk.get("sdk_recipe_sha256"):
            raise D12SystemGrantError("system build grant sdk_recipe_sha256 disagrees with d12_hosted_candidate.json")
    if frozen_identity is not None:
        for k in D12_CONTEXT_KEYS:
            if d12_ctx.get(k) != frozen_identity.get(k):
                raise D12SystemGrantError(f"system build grant d12_context.{k} disagrees with live repository")
    return dict(record)


def load_and_validate_system_build_grant(
    grant_path: Path, *,
    expected_candidate: Mapping[str, Any] | None = None,
    frozen_identity: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    parsed, _raw, sha = read_regular_json_object(
        grant_path, label="system build grant", max_bytes=MAX_SYSTEM_GRANT_BYTES
    )
    return validate_system_build_grant(
        parsed, expected_candidate=expected_candidate, frozen_identity=frozen_identity
    ), sha


def build_system_admission_proof(
    *, grant: Mapping[str, Any], grant_sha256: str, expected_candidate_sha256: str,
    raw_event_sha256: str, after: str, candidate_sha: str, candidate_tree: str,
    candidate_base_parent: str, candidate_head_parent: str, run_id: str,
    native_host: Mapping[str, str], libpq_version: int = D12_CANDIDATE_LIBPQ_VERSION,
    amd64_packages: Any = None,
) -> dict[str, Any]:
    pkg = D12_CANDIDATE_PACKAGE_MANIFEST["amd64"] if amd64_packages is None else amd64_packages
    pr_num = int(grant["pull_request"])
    proof: dict[str, Any] = {
        "schema": SYSTEM_ADMISSION_PROOF_SCHEMA, "nonce": str(grant["nonce"]),
        "reservation_sha256": str(grant["reservation_sha256"]), "grant_sha256": grant_sha256,
        "expected_candidate_sha256": expected_candidate_sha256, "raw_event_sha256": raw_event_sha256,
        "repository": str(grant["repository"]),
        "workflow_path": str(grant["workflow_path"]), "owner": str(grant["owner"]),
        "platform": str(grant["platform"]), "pull_request": pr_num, "approval_id": f"pr-{pr_num}",
        "event_action": str(grant["event_action"]), "head_ref": str(grant["head_ref"]),
        "base_ref": str(grant["base_ref"]), "before": str(grant["before"]), "after": after,
        "base": str(grant["base"]), "candidate_sha": candidate_sha, "candidate_tree": candidate_tree,
        "candidate_base_parent": candidate_base_parent, "candidate_head_parent": candidate_head_parent,
        "workflow_ordinal": int(grant["workflow_ordinal"]), "workflow_attempt": int(grant["workflow_attempt"]),
        "run_id": run_id, "native_host": dict(native_host),
        "sdk_recipe_sha256": str(grant["sdk_recipe_sha256"]), "d12_context": dict(grant["d12_context"]),
        "release_manifest": {
            "libpq_version": libpq_version, "libpq5_version": str(pkg.libpq5_version),
            "libpq_sha256": str(pkg.libpq_sha256), "postgres_config_digest": str(pkg.postgres_config_digest),
        },
    }
    return validate_system_admission_proof(
        proof, grant=grant, grant_sha256=grant_sha256, expected_candidate_sha256=expected_candidate_sha256
    )


def validate_system_admission_proof(
    record: Mapping[str, Any], *, grant: Mapping[str, Any] | None = None,
    grant_sha256: str | None = None, expected_candidate_sha256: str | None = None,
) -> dict[str, Any]:
    if not isinstance(record, Mapping) or set(record.keys()) != PROOF_TOP_LEVEL_KEYS:
        raise D12SystemGrantError("system admission proof keys do not match closed schema")
    for k, exp in (
        ("schema", SYSTEM_ADMISSION_PROOF_SCHEMA), ("repository", EXPECTED_REPOSITORY),
        ("workflow_path", EXPECTED_WORKFLOW_PATH), ("owner", EXPECTED_SYSTEM_OWNER),
        ("platform", "linux/amd64"), ("event_action", "synchronize"),
        ("head_ref", "staging"), ("base_ref", "main"), ("approval_id", "pr-23"),
    ):
        if record.get(k) != exp:
            raise D12SystemGrantError(f"system admission proof {k}={record.get(k)!r} != {exp!r}")
    for k, exp_int in (("pull_request", 23), ("workflow_ordinal", 93), ("workflow_attempt", 1)):
        val = record.get(k)
        if not _is_strict_int(val) or val != exp_int:
            raise D12SystemGrantError(f"system admission proof {k} must be strict int {exp_int}")
    if not _is_hex32(record.get("nonce")):
        raise D12SystemGrantError("system admission proof nonce must be 32 lowercase hex")
    for sha_k in (
        "reservation_sha256", "grant_sha256", "expected_candidate_sha256",
        "raw_event_sha256", "sdk_recipe_sha256",
    ):
        if not _is_hex64(record.get(sha_k)):
            raise D12SystemGrantError(f"system admission proof {sha_k} must be 64-hex")
    if record["nonce"] in (SPENT_CI69_NONCE, SPENT_CI70_NONCE, SPENT_CI71_NONCE, SPENT_CI72_NONCE, SPENT_CI85_NONCE, SPENT_CI86_NONCE, SPENT_CI87_NONCE, SPENT_CI91_NONCE, SPENT_CI92_NONCE) or record["reservation_sha256"] in (
        SPENT_CI69_RESERVATION_SHA256, SPENT_CI70_RESERVATION_SHA256, SPENT_CI71_RESERVATION_SHA256, SPENT_CI72_RESERVATION_SHA256, SPENT_CI85_RESERVATION_SHA256, SPENT_CI86_RESERVATION_SHA256, SPENT_CI87_RESERVATION_SHA256, SPENT_CI91_RESERVATION_SHA256, SPENT_CI92_RESERVATION_SHA256):
        raise D12SystemGrantError("system admission proof reuses spent CI69/CI70/CI71/CI72/CI85/CI86/CI87/CI91/CI92 nonce or reservation")
    for git_k in (
        "before", "after", "base", "candidate_sha", "candidate_tree",
        "candidate_base_parent", "candidate_head_parent",
    ):
        if not _is_hex40(record.get(git_k)):
            raise D12SystemGrantError(f"system admission proof {git_k} must be 40-hex")
    if record["before"] != EXPECTED_BEFORE_SHA or record["base"] != EXPECTED_BASE_SHA:
        raise D12SystemGrantError("system admission proof before/base does not match pinned CLOE-RUNTIME1 CI93 authority")
    if (
        record["after"] == record["before"]
        or record["candidate_base_parent"] != record["base"]
        or record["candidate_head_parent"] != record["after"]
        or record["candidate_sha"] in {record["base"], record["after"]}
    ):
        raise D12SystemGrantError("system admission proof Git parent/synchronize topology invalid")
    run_id = record.get("run_id")
    if not isinstance(run_id, str) or not run_id.isdigit():
        raise D12SystemGrantError("system admission proof run_id must be digits-only string")
    host = record.get("native_host")
    if not isinstance(host, Mapping) or dict(host) != {
        "runner_os": "Linux", "runner_arch": "X64", "host_kernel": "Linux", "host_arch": "x86_64",
    }:
        raise D12SystemGrantError("system admission proof native_host must be Linux/X64/x86_64")
    d12_ctx = _validate_d12_context(
        record.get("d12_context"), sdk_recipe_sha256=str(record["sdk_recipe_sha256"])
    )
    rel_man = record.get("release_manifest")
    if not isinstance(rel_man, Mapping) or set(rel_man.keys()) != {
        "libpq_version", "libpq5_version", "libpq_sha256", "postgres_config_digest",
    }:
        raise D12SystemGrantError("system admission proof release_manifest keys invalid")
    if (
        not _is_strict_int(rel_man.get("libpq_version"))
        or int(rel_man["libpq_version"]) < PRODUCT_MINIMUM_LIBPQ_VERSION
        or not _is_hex64(rel_man.get("libpq_sha256"))
        or not str(rel_man.get("postgres_config_digest", "")).startswith("sha256:")
    ):
        raise D12SystemGrantError("system admission proof release_manifest values invalid")
    if grant_sha256 is not None and record["grant_sha256"] != grant_sha256:
        raise D12SystemGrantError("system admission proof grant_sha256 mismatch")
    if (
        expected_candidate_sha256 is not None
        and record["expected_candidate_sha256"] != expected_candidate_sha256
    ):
        raise D12SystemGrantError("system admission proof expected_candidate_sha256 mismatch")
    if grant is not None:
        for shared_k in (
            "nonce", "reservation_sha256", "repository", "workflow_path",
            "pull_request", "event_action", "head_ref", "base_ref", "before",
            "base", "workflow_ordinal", "workflow_attempt", "platform", "owner",
            "sdk_recipe_sha256",
        ):
            if record.get(shared_k) != grant.get(shared_k):
                raise D12SystemGrantError(f"system admission proof {shared_k} disagrees with grant")
        if d12_ctx != dict(grant.get("d12_context") or {}):
            raise D12SystemGrantError("system admission proof d12_context disagrees with grant")
    return dict(record)


def write_system_admission_proof(proof_path: Path, payload: Mapping[str, Any]) -> str:
    validated = validate_system_admission_proof(payload)
    parent = proof_path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(parent, 0o700)
    raw = (json.dumps(validated, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(raw) > MAX_SYSTEM_PROOF_BYTES:
        raise D12SystemGrantError(f"system admission proof exceeds {MAX_SYSTEM_PROOF_BYTES} bytes")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(proof_path, flags, 0o600)
    except FileExistsError as exc:
        raise D12SystemGrantError(f"system admission proof already exists: {proof_path}") from exc
    except OSError as exc:
        raise D12SystemGrantError(f"cannot create system admission proof {proof_path}: {exc}") from exc
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    dir_fd = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    return hashlib.sha256(raw).hexdigest()


def load_and_validate_system_admission_proof(
    proof_path: Path, *, grant: Mapping[str, Any] | None = None,
    grant_sha256: str | None = None, expected_candidate_sha256: str | None = None,
    require_mode_0600: bool = True, require_parent_mode_0700: bool = False,
) -> tuple[dict[str, Any], bytes, str]:
    parsed, raw, sha = read_regular_json_object(
        proof_path, label="system admission proof", max_bytes=MAX_SYSTEM_PROOF_BYTES,
        require_mode_0600=require_mode_0600, require_parent_mode_0700=require_parent_mode_0700,
    )
    return validate_system_admission_proof(
        parsed, grant=grant, grant_sha256=grant_sha256, expected_candidate_sha256=expected_candidate_sha256
    ), raw, sha


def verify_host_system_proof_for_dispatch(
    args: Any, *, raw_argv: list[str] | None = None, repo_root: Path,
    env: Mapping[str, str] | None = None, uname_fn: Callable[[], tuple[str, str]] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    frozen_identity_fn: Callable[..., dict[str, Any]] | None = None,
    grant_path: Path | None = None, expected_candidate_path: Path | None = None,
) -> dict[str, Any]:
    from ci.d12_system_proof_host import verify_host_proof_against_live_environment

    return verify_host_proof_against_live_environment(
        args, raw_argv=raw_argv, repo_root=repo_root, env=env, uname_fn=uname_fn,
        runner=runner, frozen_identity_fn=frozen_identity_fn, grant_path=grant_path,
        expected_candidate_path=expected_candidate_path,
    )
