"""Stdlib-only Route B system-hold prerequisite, grant, and host admission proof orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from ci.d12_system_grant import (
    DEFAULT_CANDIDATE_RELPATH,
    DEFAULT_GRANT_RELPATH,
    D12SystemGrantError,
    MAX_SYSTEM_GRANT_BYTES,
    build_system_admission_proof,
    load_and_validate_system_build_grant,
    read_regular_json_object,
    write_system_admission_proof,
)
from ci.d12_system_proof_host import (
    SYSTEM_HOLD_REFUSAL_SCHEMA,
    _compute_live_sdk_recipe_sha256 as _lower_compute_live_sdk_recipe_sha256,
    _default_uname as _lower_default_uname,
    _git_rev as _git_rev,
    validate_expected_candidate_record,
    validate_host_system_event_and_git as _lower_validate_host_system_event_and_git,
    verify_host_proof_against_live_environment as _lower_verify_host_proof_against_live_environment,
)
from repomap_kg.runtime.release import DYNAMIC_PACKAGE_MANIFEST, PSYCOPG_LIBPQ_VERSION
from repomap_kg.runtime.release_manifest import (
    D12_CANDIDATE_LIBPQ_VERSION,
    D12_CANDIDATE_PACKAGE_MANIFEST,
)
from repomap_test_support.d12_recipe import frozen_identity
from tools.system.candidate_image import require_release_prerequisites_resolved

_REDACT_RE = re.compile(
    r"(/" + r"Users/[^\s\"']+|/home/[^\s\"']+|ghp_[A-Za-z0-9_]+|PRIVATE_KEY[^\s\"']*)"
)


def _redact_text(text: str, repo_root: Path) -> str:
    cleaned = text.replace(str(repo_root), "<repo_root>")
    return _REDACT_RE.sub("<redacted>", cleaned)


def _default_uname() -> tuple[str, str]:
    return _lower_default_uname()


def _compute_live_sdk_recipe_sha256(repo_root: Path) -> str:
    return _lower_compute_live_sdk_recipe_sha256(repo_root)


def validate_host_system_event_and_git(
    repo_root: Path,
    *,
    grant: Mapping[str, Any],
    environ: Mapping[str, str],
    uname_fn: Callable[[], tuple[str, str]] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    return _lower_validate_host_system_event_and_git(
        repo_root,
        grant=grant,
        environ=environ,
        uname_fn=_default_uname if uname_fn is None else uname_fn,
        runner=subprocess.run if runner is None else runner,
    )


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
    return _lower_verify_host_proof_against_live_environment(
        args,
        raw_argv=raw_argv,
        repo_root=repo_root,
        env=os.environ if env is None else env,
        uname_fn=_default_uname if uname_fn is None else uname_fn,
        runner=subprocess.run if runner is None else runner,
        frozen_identity_fn=frozen_identity if frozen_identity_fn is None else frozen_identity_fn,
        grant_path=grant_path,
        expected_candidate_path=expected_candidate_path,
    )


def run_system_hold(
    repo_root: Path, *,
    candidate_sha: str, candidate_tree: str,
    candidate_base_parent: str, candidate_head_parent: str,
    output_json: Path,
    proof_json: Path | None = None,
    grant_json: Path | None = None,
    expected_json: Path | None = None,
    target_arch: str = "amd64",
    libpq_version: object = ...,
    package_manifest: object = ...,
    env: Mapping[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    uname_fn: Callable[[], tuple[str, str]] | None = None,
    frozen_identity_fn: Callable[..., dict[str, Any]] | None = None,
    require_prerequisites_fn: Callable[..., Any] | None = None,
) -> tuple[dict[str, Any], int]:
    """Verify release prerequisites and Route B grant before any system SDK or candidate build."""
    eff_frozen = frozen_identity if frozen_identity_fn is None else frozen_identity_fn
    eff_prereq = (
        require_release_prerequisites_resolved
        if require_prerequisites_fn is None
        else require_prerequisites_fn
    )
    eff_uname = _default_uname if uname_fn is None else uname_fn
    eff_runner = subprocess.run if runner is None else runner
    frozen = eff_frozen(repo_root, f"linux/{target_arch}")
    reasons: list[str] = []
    if proof_json is not None:
        eff_libpq = D12_CANDIDATE_LIBPQ_VERSION if libpq_version is ... else libpq_version
        eff_manifest = (
            D12_CANDIDATE_PACKAGE_MANIFEST if package_manifest is ... else package_manifest
        )
    else:
        eff_libpq = PSYCOPG_LIBPQ_VERSION if libpq_version is ... else libpq_version
        eff_manifest = (
            DYNAMIC_PACKAGE_MANIFEST if package_manifest is ... else package_manifest
        )

    resolved_libpq = D12_CANDIDATE_LIBPQ_VERSION
    if isinstance(eff_libpq, int) and not isinstance(eff_libpq, bool):
        resolved_libpq = eff_libpq
    resolved_packages: Any = None
    try:
        prereq_res = eff_prereq(
            target_arch, libpq_version=eff_libpq, package_manifest=eff_manifest
        )
        if isinstance(prereq_res, tuple) and len(prereq_res) == 2:
            ver_part, resolved_packages = prereq_res
            if isinstance(ver_part, int) and not isinstance(ver_part, bool):
                resolved_libpq = ver_part
    except Exception as error:
        reasons.append(_redact_text(str(error), repo_root))

    if proof_json is not None and not reasons:
        environ = os.environ if env is None else env
        try:
            cand_file = expected_json or (repo_root / DEFAULT_CANDIDATE_RELPATH)
            grant_file = grant_json or (repo_root / DEFAULT_GRANT_RELPATH)
            cand_raw, _cb, cand_sha = read_regular_json_object(
                cand_file, label="expected candidate JSON", max_bytes=MAX_SYSTEM_GRANT_BYTES
            )
            expected_cand = validate_expected_candidate_record(cand_raw)
            grant, grant_sha = load_and_validate_system_build_grant(
                grant_file, expected_candidate=expected_cand, frozen_identity=frozen
            )
            if _compute_live_sdk_recipe_sha256(repo_root) != grant["sdk_recipe_sha256"]:
                raise D12SystemGrantError("live SDK recipe SHA256 disagrees with system build grant")
            live = validate_host_system_event_and_git(
                repo_root, grant=grant, environ=environ, uname_fn=eff_uname, runner=eff_runner
            )
            if (
                candidate_sha.strip().lower() != live["candidate_sha"]
                or candidate_tree.strip().lower() != live["candidate_tree"]
                or candidate_base_parent.strip().lower() != live["candidate_base_parent"]
                or candidate_head_parent.strip().lower() != live["candidate_head_parent"]
            ):
                raise D12SystemGrantError("system-hold CLI candidate/parent arguments disagree with live Git")
            proof_payload = build_system_admission_proof(
                grant=grant,
                grant_sha256=grant_sha,
                expected_candidate_sha256=cand_sha,
                raw_event_sha256=live["raw_event_sha256"],
                after=live["after"],
                candidate_sha=live["candidate_sha"],
                candidate_tree=live["candidate_tree"],
                candidate_base_parent=live["candidate_base_parent"],
                candidate_head_parent=live["candidate_head_parent"],
                run_id=live["run_id"],
                native_host=live["native_host"],
                libpq_version=resolved_libpq,
                amd64_packages=resolved_packages,
            )
            write_system_admission_proof(proof_json, proof_payload)
        except Exception as error:
            proof_json.unlink(missing_ok=True)
            reasons.append(_redact_text(str(error), repo_root))

    payload: dict[str, Any] = {
        "schema": SYSTEM_HOLD_REFUSAL_SCHEMA,
        "gate_kind": "main-system",
        "target_arch": target_arch,
        "result": "refused_release_prerequisites_unresolved" if reasons else "prerequisites_resolved",
        "qualified": False,
        "sdk_builds_started": 0,
        "application_candidate_builds_started": 0,
        "managed_system_candidate_image_build_count": 0,
        "candidate_sha": candidate_sha,
        "candidate_tree": candidate_tree,
        "candidate_base_parent": candidate_base_parent,
        "candidate_head_parent": candidate_head_parent,
        "d12_source_sha256": frozen["source_sha256"],
        "d12_recipe_sha256": frozen["recipe_sha256"],
        "d12_dockerfile_sha256": frozen["dockerfile_sha256"],
        "reasons": reasons,
    }
    output_json.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output_json.parent.name == "repomap-d12-system-admission":
        os.chmod(output_json.parent, 0o700)
    output_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload, (1 if reasons else 0)
