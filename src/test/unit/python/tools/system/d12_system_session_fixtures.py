"""Synthetic historical CI72 session fixtures; no native or image qualification evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from ci.d12_hosted_evidence import validate_expected_candidate_record
from ci.d12_system_grant import (
    DEFAULT_CANDIDATE_RELPATH, DEFAULT_GRANT_RELPATH, build_system_admission_proof,
    load_and_validate_system_build_grant, write_system_admission_proof,
)
from repomap_kg.runtime.release import GO_RELEASE_IMAGE, POSTGRES_RELEASE_IMAGE, PYTHON_RELEASE_IMAGE
from repomap_kg.runtime.release_manifest import D12_CANDIDATE_LIBPQ_VERSION, D12_CANDIDATE_PACKAGE_MANIFEST
from tools.system import d12_system_session as session_mod
from tools.system.config import SystemTestConfig
from tools.system.d12_system_session import D12SystemSession

REPO_ROOT = Path(__file__).resolve().parents[6]
BASE_SHA = "24d15650a2d4563d188acb8bbf34a0dabf8f3d65"


def _active_run_id() -> str:
    return str(r.ledger.identity.run_id) if (r := session_mod.active_resource_run()) is not None else "run-d12-session"


def _make_valid_proof(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    live_cand_path, grant_path = REPO_ROOT / DEFAULT_CANDIDATE_RELPATH, REPO_ROOT / DEFAULT_GRANT_RELPATH
    raw_grant, _ = load_and_validate_system_build_grant(grant_path)
    live_cand = validate_expected_candidate_record(json.loads(live_cand_path.read_text(encoding="utf-8")))
    expected_cand = validate_expected_candidate_record({**live_cand, "d12_context": dict(raw_grant["d12_context"])})
    tmp_path.mkdir(parents=True, exist_ok=True)
    cand_raw = (json.dumps(expected_cand, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (tmp_path / "ci72-candidate.json").write_bytes(cand_raw)
    cand_sha = hashlib.sha256(cand_raw).hexdigest()
    grant, grant_sha = load_and_validate_system_build_grant(
        grant_path, expected_candidate=expected_cand, frozen_identity=dict(expected_cand["d12_context"])
    )
    (ev := tmp_path / "event.json").write_text(json.dumps({"number": 13, "draft": True}), encoding="utf-8")
    proof = build_system_admission_proof(
        grant=grant, grant_sha256=grant_sha, expected_candidate_sha256=cand_sha,
        raw_event_sha256=hashlib.sha256(ev.read_bytes()).hexdigest(),
        after="d" * 40, candidate_sha="a" * 40, candidate_tree="b" * 40,
        candidate_base_parent=str(grant["base"]), candidate_head_parent="d" * 40, run_id="12345678",
        native_host={"runner_os": "Linux", "runner_arch": "X64", "host_kernel": "Linux", "host_arch": "x86_64"},
    )
    write_system_admission_proof(proof_file := tmp_path / "proof-dir" / "proof.json", proof)
    return proof_file, dict(expected_cand["d12_context"])


def _fake_git(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
    mapping = {"HEAD": "a" * 40, "HEAD^{tree}": "b" * 40, "HEAD^1": BASE_SHA, "HEAD^2": "d" * 40}
    return subprocess.CompletedProcess(cmd, 0, mapping[cmd[-1]] + "\n", "")


def _matching_preflight_report(d12_ctx: dict[str, Any]) -> dict[str, Any]:
    pkg = D12_CANDIDATE_PACKAGE_MANIFEST["amd64"]
    zero_counts = dict.fromkeys(
        ("managed_system_candidate_image_build_count", "product_or_build_profile_build_count",
         "unmanaged_build_count", "unmanaged_pull_count"), 0,
    )
    return {
        "mode": "exploration", "result": "observed", "refusals": [],
        "availability": {"platform": "linux/amd64", "execution": "native", "builder_platforms": ["linux/amd64"]},
        "bases": {
            POSTGRES_RELEASE_IMAGE: {"id": "sha256:" + "1" * 64},
            PYTHON_RELEASE_IMAGE: {"id": "sha256:" + "2" * 64},
            GO_RELEASE_IMAGE: {"id": "sha256:" + "3" * 64},
        },
        "bindings": {"run_id": _active_run_id(), "daemon_id": "daemon-1"},
        "identity": dict(d12_ctx),
        "steps": {
            "libpq5_version": pkg.libpq5_version,
            "candidate": {
                "architecture": "amd64", "manifest": pkg._asdict(), "libpq_version": D12_CANDIDATE_LIBPQ_VERSION,
                "package_forecast": D12_CANDIDATE_LIBPQ_VERSION,
                "libpq_label": "runtime PQlibVersion; forecast is equality only", "written_to_source": False,
                "valid": True,
            },
            "libpq_runtime": {
                "api": D12_CANDIDATE_LIBPQ_VERSION,
                "library": {
                    "path": pkg.libpq_path, "sha256": pkg.libpq_sha256, "package": "libpq5",
                    "version": pkg.libpq5_version, "architecture": "amd64",
                },
            },
        },
        "server_inventory": {
            "files": [{"role": "libpq", "owner": "libpq5", "resolved": pkg.libpq_path, "sha256": pkg.libpq_sha256}],
            "packages": [["libpq5", pkg.libpq5_version, "amd64"]],
        },
        "cleanup": {
            "server": "removed", "containers": "baseline_verified",
            "budget": dict(zero_counts), "zero_build": dict(zero_counts),
        },
    }


def _make_config(report_dir: Path, run_id: str | None = None) -> SystemTestConfig:
    return SystemTestConfig.create(
        timeout_seconds=1500, report_dir=report_dir, candidate_tree_sha="b" * 40,
        run_id=run_id or _active_run_id(), gate_kind="main-system", approval_id="pr-13", pr_number="13",
        repository="Knowledge-Forge-AI/repo-map", approved_base_branch="main", approved_base_sha=BASE_SHA,
        approved_head_branch="staging", approved_head_sha="d" * 40, candidate_commit_sha="a" * 40,
        candidate_base_parent=BASE_SHA, candidate_head_parent="d" * 40, execution_mode="hosted_qualification",
    )


def _establish(
    tmp_path: Path, report_dir: Path | None = None, **overrides: Any,
) -> tuple[D12SystemSession, dict[str, Any]]:
    proof_file, d12_ctx = _make_valid_proof(tmp_path)
    overrides.setdefault("expected_candidate_path", tmp_path / "ci72-candidate.json")
    return D12SystemSession.establish(
        repo_root=REPO_ROOT, config=_make_config(report_dir or (tmp_path / "report")),
        proof_json_arg=str(proof_file), target_arch_fn=lambda: "amd64", tree_sha_fn=lambda _r: "b" * 40,
        frozen_identity_fn=lambda _r, _p: dict(d12_ctx), run_git_fn=_fake_git, **overrides,
    ), d12_ctx
