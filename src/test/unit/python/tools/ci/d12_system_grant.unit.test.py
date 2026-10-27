"""Unit tests for Route B D12 system build grant and host admission proof contracts."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from ci.d12_hosted_evidence import validate_expected_candidate_record
from ci.d12_system_grant import (
    DEFAULT_CANDIDATE_RELPATH,
    DEFAULT_GRANT_RELPATH,
    EXPECTED_APPROVAL_SHA256,
    EXPECTED_BASE_SHA,
    EXPECTED_BEFORE_SHA,
    EXPECTED_LEDGER_BEFORE_SHA256,
    EXPECTED_PHASE_ID,
    SPENT_CI69_NONCE,
    SPENT_CI69_RESERVATION_SHA256,
    SPENT_CI70_NONCE,
    SPENT_CI70_RESERVATION_SHA256,
    D12SystemGrantError,
    SYSTEM_ADMISSION_PROOF_SCHEMA,
    SYSTEM_BUILD_GRANT_SCHEMA,
    build_system_admission_proof,
    load_and_validate_system_admission_proof,
    load_and_validate_system_build_grant,
    validate_system_admission_proof,
    validate_system_build_grant,
    verify_host_system_proof_for_dispatch,
    write_system_admission_proof,
)

REPO_ROOT = Path(__file__).resolve().parents[6]


def _event_payload(grant: dict[str, Any], *, draft: object = True) -> dict[str, Any]:
    pr: dict[str, Any] = {
        "number": 13,
        "base": {
            "ref": "main",
            "sha": grant["base"],
            "repo": {"full_name": grant["repository"], "fork": False},
        },
        "head": {
            "ref": "staging",
            "sha": "d" * 40,
            "repo": {"full_name": grant["repository"], "fork": False},
        },
    }
    if draft is not ...:
        pr["draft"] = draft
    return {
        "action": "synchronize",
        "before": grant["before"],
        "after": "d" * 40,
        "number": 13,
        "pull_request": pr,
    }


def _make_proof(
    grant: dict[str, Any],
    grant_sha: str,
    cand_sha: str,
    *,
    raw_event_sha256: str | None = None,
) -> dict[str, Any]:
    ev_sha = raw_event_sha256 or hashlib.sha256(
        json.dumps(_event_payload(grant)).encode("utf-8")
    ).hexdigest()
    return build_system_admission_proof(
        grant=grant,
        grant_sha256=grant_sha,
        expected_candidate_sha256=cand_sha,
        raw_event_sha256=ev_sha,
        after="d" * 40,
        candidate_sha="a" * 40,
        candidate_tree="b" * 40,
        candidate_base_parent=str(grant["base"]),
        candidate_head_parent="d" * 40,
        run_id="12345678",
        native_host={
            "runner_os": "Linux",
            "runner_arch": "X64",
            "host_kernel": "Linux",
            "host_arch": "x86_64",
        },
    )


def test_load_tracked_system_build_grant_matches_candidate_record() -> None:
    cand_path = REPO_ROOT / DEFAULT_CANDIDATE_RELPATH
    grant_path = REPO_ROOT / DEFAULT_GRANT_RELPATH
    expected_cand = validate_expected_candidate_record(
        json.loads(cand_path.read_text(encoding="utf-8"))
    )
    grant, grant_sha = load_and_validate_system_build_grant(
        grant_path,
        expected_candidate=expected_cand,
        frozen_identity=dict(expected_cand["d12_context"]),
    )
    assert EXPECTED_PHASE_ID == "REPOMAP-PRODUCT6-NAVIGATION47-CI70FIX1"
    assert SPENT_CI70_NONCE == "2ca8d5a3ad7645798437728db064e8d4"
    assert SPENT_CI70_RESERVATION_SHA256 == (
        "aba49e31a10db6bb6326e48f0fd681ede763e3be0fa86f37ddda1bae0df76a91"
    )
    assert grant["schema"] == SYSTEM_BUILD_GRANT_SCHEMA
    assert grant["platform"] == "linux/amd64"
    assert grant["owner"] == "main-system-gate"
    assert grant["workflow_ordinal"] == 71
    assert grant["workflow_attempt"] == 1
    assert grant["maximum_total"] == 3
    assert grant["maximum_per_platform"] == 3
    assert grant["before"] == EXPECTED_BEFORE_SHA
    assert grant["base"] == EXPECTED_BASE_SHA
    assert grant["approval_sha256"] == EXPECTED_APPROVAL_SHA256
    assert grant["ledger_before_sha256"] == EXPECTED_LEDGER_BEFORE_SHA256
    assert grant["pull_request"] == 13
    assert len(grant_sha) == 64


def test_validate_system_build_grant_rejects_boolean_or_tampered_fields() -> None:
    grant_path = REPO_ROOT / DEFAULT_GRANT_RELPATH
    grant, grant_sha = load_and_validate_system_build_grant(grant_path)
    bad_bool = dict(grant, maximum_per_platform=True)
    with pytest.raises(D12SystemGrantError, match="maximum_per_platform"):
        validate_system_build_grant(bad_bool)

    bad_owner = dict(grant, owner="wrong-owner")
    with pytest.raises(D12SystemGrantError, match="owner"):
        validate_system_build_grant(bad_owner)

    for field, bad_val in (
        ("workflow_ordinal", 69),
        ("workflow_ordinal", 70),
        ("workflow_ordinal", 72),
        ("workflow_attempt", 2),
        ("maximum_per_platform", 1),
        ("maximum_per_platform", 2),
        ("maximum_total", 1),
        ("maximum_total", 2),
        ("nonce", SPENT_CI69_NONCE),
        ("reservation_sha256", SPENT_CI69_RESERVATION_SHA256),
        ("nonce", SPENT_CI70_NONCE),
        ("reservation_sha256", SPENT_CI70_RESERVATION_SHA256),
        ("nonce", str(grant["nonce"]) + "\n"),
        ("before", str(grant["before"]) + "\n"),
        ("reservation_sha256", str(grant["reservation_sha256"]) + "\n"),
        ("before", "51a3e055b3ea35dc4e9f0bba7966e4799881b159"),
        ("before", "1" * 40),
        ("base", "2" * 40),
        ("approval_sha256", "88a3672196430bf30091672621771af4160fa22c28fe35b671145e2ed4e870b1"),
        ("approval_sha256", "3" * 64),
        ("ledger_before_sha256", "1cc8dea0eed060628e427f052df5968118e91d015b8fc3c8792516314b84f6d5"),
        ("ledger_before_sha256", "4" * 64),
    ):
        with pytest.raises(D12SystemGrantError):
            validate_system_build_grant({**grant, field: bad_val})

    cand_sha = hashlib.sha256((REPO_ROOT / DEFAULT_CANDIDATE_RELPATH).read_bytes()).hexdigest()
    proof = _make_proof(grant, grant_sha, cand_sha)
    assert "maximum_total" not in proof and "maximum_per_platform" not in proof
    for max_key in ("maximum_total", "maximum_per_platform"):
        with pytest.raises(D12SystemGrantError, match="closed schema"):
            validate_system_admission_proof({**proof, max_key: 3})
    for proof_field, bad_proof_val in (
        ("workflow_ordinal", 69),
        ("workflow_ordinal", 70),
        ("workflow_ordinal", 72),
        ("workflow_attempt", 2),
        ("nonce", SPENT_CI69_NONCE),
        ("reservation_sha256", SPENT_CI69_RESERVATION_SHA256),
        ("nonce", SPENT_CI70_NONCE),
        ("reservation_sha256", SPENT_CI70_RESERVATION_SHA256),
        ("nonce", str(proof["nonce"]) + "\n"),
        ("before", str(proof["before"]) + "\n"),
        ("reservation_sha256", str(proof["reservation_sha256"]) + "\n"),
        ("before", "51a3e055b3ea35dc4e9f0bba7966e4799881b159"),
        ("before", "1" * 40),
        ("base", "2" * 40),
    ):
        with pytest.raises(D12SystemGrantError):
            validate_system_admission_proof({**proof, proof_field: bad_proof_val})


def test_write_and_load_system_admission_proof_enforces_0600_and_no_overwrite(
    tmp_path: Path,
) -> None:
    cand_path = REPO_ROOT / DEFAULT_CANDIDATE_RELPATH
    grant_path = REPO_ROOT / DEFAULT_GRANT_RELPATH
    cand_sha = hashlib.sha256(cand_path.read_bytes()).hexdigest()
    grant, grant_sha = load_and_validate_system_build_grant(grant_path)
    proof = _make_proof(grant, grant_sha, cand_sha)
    assert proof["schema"] == SYSTEM_ADMISSION_PROOF_SCHEMA
    proof_dir = tmp_path / "repomap-d12-system-admission"
    proof_file = proof_dir / "d12-system-admission-proof.json"
    written_sha = write_system_admission_proof(proof_file, proof)
    assert len(written_sha) == 64
    assert stat.S_IMODE(proof_dir.lstat().st_mode) == 0o700
    assert stat.S_IMODE(proof_file.lstat().st_mode) == 0o600

    with pytest.raises(D12SystemGrantError, match="already exists"):
        write_system_admission_proof(proof_file, proof)

    loaded, _raw, loaded_sha = load_and_validate_system_admission_proof(
        proof_file,
        grant=grant,
        grant_sha256=grant_sha,
        expected_candidate_sha256=cand_sha,
        require_mode_0600=True,
        require_parent_mode_0700=True,
    )
    assert loaded_sha == written_sha
    assert loaded["approval_id"] == "pr-13"

    os.chmod(proof_file, 0o644)
    with pytest.raises(D12SystemGrantError, match="mode 0600"):
        load_and_validate_system_admission_proof(proof_file, require_mode_0600=True)


def test_validate_system_admission_proof_rejects_non_native_host() -> None:
    cand_path = REPO_ROOT / DEFAULT_CANDIDATE_RELPATH
    grant_path = REPO_ROOT / DEFAULT_GRANT_RELPATH
    cand_sha = hashlib.sha256(cand_path.read_bytes()).hexdigest()
    grant, grant_sha = load_and_validate_system_build_grant(grant_path)
    proof = _make_proof(grant, grant_sha, cand_sha)
    bad = dict(proof, native_host={**proof["native_host"], "host_arch": "aarch64"})
    with pytest.raises(D12SystemGrantError, match="native_host"):
        validate_system_admission_proof(bad)


def test_verify_host_system_proof_for_dispatch_validates_live_bindings(tmp_path: Path) -> None:
    cand_path = REPO_ROOT / DEFAULT_CANDIDATE_RELPATH
    grant_path = REPO_ROOT / DEFAULT_GRANT_RELPATH
    cand_sha = hashlib.sha256(cand_path.read_bytes()).hexdigest()
    expected_cand = validate_expected_candidate_record(
        json.loads(cand_path.read_text(encoding="utf-8"))
    )
    grant, grant_sha = load_and_validate_system_build_grant(grant_path)
    event_file = tmp_path / "event.json"
    event_file.write_text(json.dumps(_event_payload(grant, draft=True)), encoding="utf-8")
    raw_event_sha256 = hashlib.sha256(event_file.read_bytes()).hexdigest()
    proof_file = tmp_path / "proof-dir" / "proof.json"
    proof = _make_proof(grant, grant_sha, cand_sha, raw_event_sha256=raw_event_sha256)
    write_system_admission_proof(proof_file, proof)
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_REPOSITORY": str(grant["repository"]),
        "GITHUB_BASE_REF": "main",
        "GITHUB_HEAD_REF": "staging",
        "GITHUB_WORKFLOW_REF": f"{grant['repository']}/{grant['workflow_path']}@refs/pull/13/merge",
        "GITHUB_RUN_NUMBER": str(grant["workflow_ordinal"]),
        "GITHUB_RUN_ID": "12345678",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_EVENT_PATH": str(event_file),
        "RUNNER_OS": "Linux",
        "RUNNER_ARCH": "X64",
    }

    def fake_git(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        rev = cmd[-1]
        mapping = {
            "HEAD": "a" * 40,
            "HEAD^{tree}": "b" * 40,
            "HEAD^1": str(grant["base"]),
            "HEAD^2": "d" * 40,
        }
        if rev == "HEAD^3":
            return subprocess.CompletedProcess(cmd, 1, "", "no parent 3")
        return subprocess.CompletedProcess(cmd, 0, mapping[rev] + "\n", "")

    args = SimpleNamespace(
        d12_system_proof_json=str(proof_file),
        candidate_sha="a" * 40,
        candidate_tree="b" * 40,
        candidate_base_parent=str(grant["base"]),
        candidate_head_parent="d" * 40,
        approval_id="pr-13",
        pr_number="13",
        repository=str(grant["repository"]),
    )
    verified = verify_host_system_proof_for_dispatch(
        args,
        repo_root=REPO_ROOT,
        env=env,
        uname_fn=lambda: ("Linux", "x86_64"),
        runner=fake_git,
        frozen_identity_fn=lambda _r, _p: dict(expected_cand["d12_context"]),
        grant_path=grant_path,
        expected_candidate_path=cand_path,
    )
    assert verified["grant_sha256"] == grant_sha
    assert verified["raw_event_sha256"] == raw_event_sha256

    event_file.write_text(json.dumps(_event_payload(grant, draft=True), indent=2), encoding="utf-8")
    with pytest.raises(D12SystemGrantError, match="raw_event_sha256"):
        verify_host_system_proof_for_dispatch(
            args,
            repo_root=REPO_ROOT,
            env=env,
            uname_fn=lambda: ("Linux", "x86_64"),
            runner=fake_git,
            frozen_identity_fn=lambda _r, _p: dict(expected_cand["d12_context"]),
            grant_path=grant_path,
            expected_candidate_path=cand_path,
        )
