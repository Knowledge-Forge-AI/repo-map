"""Unit tests for pure Route B host-proof verification, pure D12 recipe identity, and lower import boundaries."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from ci import d12_hosted_evidence, d12_system_hold, d12_system_proof_host
from ci.d12_system_grant import (
    DEFAULT_CANDIDATE_RELPATH,
    DEFAULT_GRANT_RELPATH,
    D12SystemGrantError,
    build_system_admission_proof,
    load_and_validate_system_build_grant,
    verify_host_system_proof_for_dispatch,
    write_system_admission_proof,
)
from repomap_test_support import d12_core_image, d12_recipe

REPO_ROOT = Path(__file__).resolve().parents[6]


def _build_fixture_proof(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[str, Any], dict[str, str], Any]:
    cand_path = REPO_ROOT / DEFAULT_CANDIDATE_RELPATH
    grant_path = REPO_ROOT / DEFAULT_GRANT_RELPATH
    cand_raw = json.loads(cand_path.read_text(encoding="utf-8"))
    expected_cand = d12_system_proof_host.validate_expected_candidate_record(cand_raw)
    cand_sha = hashlib.sha256(cand_path.read_bytes()).hexdigest()
    grant, grant_sha = load_and_validate_system_build_grant(grant_path)
    event_file = tmp_path / "event.json"
    event_file.write_text(
        json.dumps(
            {
                "action": "synchronize",
                "before": grant["before"],
                "after": "d" * 40,
                "number": 13,
                "pull_request": {
                    "number": 13,
                    "draft": True,
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
                },
            }
        ),
        encoding="utf-8",
    )
    raw_event_sha256 = hashlib.sha256(event_file.read_bytes()).hexdigest()
    proof_file = tmp_path / "proof-dir" / "proof.json"
    proof = build_system_admission_proof(
        grant=grant,
        grant_sha256=grant_sha,
        expected_candidate_sha256=cand_sha,
        raw_event_sha256=raw_event_sha256,
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

    return cand_path, grant_path, proof_file, dict(expected_cand["d12_context"]), env, fake_git


def test_candidate_validator_and_constant_equivalence() -> None:
    assert (
        d12_hosted_evidence.validate_expected_candidate_record
        is d12_system_proof_host.validate_expected_candidate_record
    )
    assert d12_hosted_evidence.HostedD12EvidenceError is d12_system_proof_host.HostedD12EvidenceError
    assert d12_hosted_evidence.SYSTEM_HOLD_REFUSAL_SCHEMA == d12_system_proof_host.SYSTEM_HOLD_REFUSAL_SCHEMA
    assert d12_hosted_evidence.EXPECTED_CANDIDATE_SCHEMA == d12_system_proof_host.EXPECTED_CANDIDATE_SCHEMA
    assert d12_hosted_evidence.EXPECTED_PLATFORM == d12_system_proof_host.EXPECTED_PLATFORM
    assert d12_hosted_evidence.EXPECTED_SDK_IMAGE_TAG == d12_system_proof_host.EXPECTED_SDK_IMAGE_TAG
    assert (
        d12_hosted_evidence.EXPECTED_SDK_DOCKERFILE_SHA256
        == d12_system_proof_host.EXPECTED_SDK_DOCKERFILE_SHA256
    )
    assert (
        d12_hosted_evidence.EXPECTED_SDK_HELPER_SHA256
        == d12_system_proof_host.EXPECTED_SDK_HELPER_SHA256
    )

    cand_raw = json.loads((REPO_ROOT / DEFAULT_CANDIDATE_RELPATH).read_text(encoding="utf-8"))
    from_host = d12_system_proof_host.validate_expected_candidate_record(cand_raw)
    from_evidence = d12_hosted_evidence.validate_expected_candidate_record(cand_raw)
    assert from_host == from_evidence

    with pytest.raises(d12_hosted_evidence.HostedD12EvidenceError, match="self-referential commit"):
        d12_system_proof_host.validate_expected_candidate_record({**cand_raw, "commit_sha": "a" * 40})


def _git_context(root: Path) -> Path:
    files = (
        ("pyproject.toml", "[project]\n"),
        ("README.md", "# Sample\n"),
        ("src/main/python/pkg/a.py", "A = 1\n"),
        ("src/main/go/go.mod", "module sample\n"),
        ("src/main/resources/x.sql", "SELECT 1;\n"),
        ("docs/out.md", "outside\n"),
    )
    for rel, text in files:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def test_pure_d12_recipe_and_core_wrapper_identity_equivalence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_context(tmp_path / "repo")
    assert d12_core_image.D12ProfileError is d12_recipe.D12ProfileError
    assert d12_core_image.CONTEXT_PATHS == d12_recipe.CONTEXT_PATHS
    assert d12_core_image.context_files is d12_recipe.context_files
    assert d12_core_image.digest_files is d12_recipe.digest_files
    assert "docs/out.md" not in d12_recipe.context_files(repo)
    assert d12_recipe.recipe_digest("linux/amd64") == d12_core_image.recipe_digest("linux/amd64")
    pure_id = d12_recipe.frozen_identity(repo, "linux/amd64")
    core_id = d12_core_image.frozen_identity(repo, "linux/amd64")
    assert pure_id == core_id
    assert pure_id["context_file_count"] == 5

    custom_digest = d12_recipe.compute_recipe_digest(
        "linux/amd64",
        dockerfile_text="FROM scratch\n",
        platform_build_args={"TARGETOS": "linux", "TARGETARCH": "amd64"},
    )
    custom_identity = d12_recipe.compute_frozen_identity(
        repo,
        "linux/amd64",
        context_files_fn=lambda _root: ("README.md",),
        digest_files_fn=d12_recipe.digest_files,
        recipe_digest_fn=lambda _platform: custom_digest,
        recipe_text_fn=lambda: "FROM scratch\n",
    )
    assert custom_identity["recipe_sha256"] == custom_digest
    assert custom_identity["context_file_count"] == 1

    monkeypatch.setattr(d12_core_image, "recipe_text", lambda: "FROM scratch\n")
    patched_core_id = d12_core_image.frozen_identity(repo, "linux/amd64")
    assert patched_core_id["recipe_sha256"] == custom_digest
    assert d12_recipe.frozen_identity(repo, "linux/amd64") == pure_id


def test_direct_host_proof_verification_and_facade_equivalence(tmp_path: Path) -> None:
    cand_path, grant_path, proof_file, d12_ctx, env, fake_git = _build_fixture_proof(tmp_path)
    args = SimpleNamespace(
        d12_system_proof_json=str(proof_file),
        candidate_sha="a" * 40,
        candidate_tree="b" * 40,
        candidate_base_parent=str(json.loads(grant_path.read_text(encoding="utf-8"))["base"]),
        candidate_head_parent="d" * 40,
        approval_id="pr-13",
        pr_number="13",
        repository="Knowledge-Forge-AI/repo-map",
    )
    common_kwargs: dict[str, Any] = {
        "repo_root": REPO_ROOT,
        "env": env,
        "uname_fn": lambda: ("Linux", "x86_64"),
        "runner": fake_git,
        "frozen_identity_fn": lambda _r, _p: d12_ctx,
        "grant_path": grant_path,
        "expected_candidate_path": cand_path,
    }
    verified_lower = d12_system_proof_host.verify_host_proof_against_live_environment(
        args, **common_kwargs
    )
    verified_hold = d12_system_hold.verify_host_proof_against_live_environment(
        args, **common_kwargs
    )
    verified_dispatch = verify_host_system_proof_for_dispatch(args, **common_kwargs)
    assert verified_lower == verified_hold == verified_dispatch
    assert verified_lower["pull_request"] == 13


def test_host_event_and_git_requires_exact_draft_true_and_strict_env_event_facts(
    tmp_path: Path,
) -> None:
    _cand_path, grant_path, _proof_file, _d12_ctx, env, fake_git = _build_fixture_proof(tmp_path)
    grant, _ = load_and_validate_system_build_grant(grant_path)
    event_file = Path(env["GITHUB_EVENT_PATH"])
    valid_event = json.loads(event_file.read_text(encoding="utf-8"))

    live_lower = d12_system_proof_host.validate_host_system_event_and_git(
        REPO_ROOT, grant=grant, environ=env, uname_fn=lambda: ("Linux", "x86_64"), runner=fake_git
    )
    live_facade = d12_system_hold.validate_host_system_event_and_git(
        REPO_ROOT, grant=grant, environ=env, uname_fn=lambda: ("Linux", "x86_64"), runner=fake_git
    )
    assert live_lower == live_facade
    assert live_lower["raw_event_sha256"] == hashlib.sha256(event_file.read_bytes()).hexdigest()

    for bad_draft in (False, None, 0, 1, "true", ...):
        bad_pr = dict(valid_event["pull_request"])
        if bad_draft is ...:
            bad_pr.pop("draft", None)
        else:
            bad_pr["draft"] = bad_draft
        event_file.write_text(json.dumps({**valid_event, "pull_request": bad_pr}), encoding="utf-8")
        for fn in (
            d12_system_proof_host.validate_host_system_event_and_git,
            d12_system_hold.validate_host_system_event_and_git,
        ):
            with pytest.raises(D12SystemGrantError, match="pull_request\\.draft is True"):
                fn(
                    REPO_ROOT,
                    grant=grant,
                    environ=env,
                    uname_fn=lambda: ("Linux", "x86_64"),
                    runner=fake_git,
                )

    for bad_event, match_re in (
        ({k: v for k, v in valid_event.items() if k != "number"}, "number"),
        ({**valid_event, "number": True}, "number"),
        ({**valid_event, "number": 14}, "number"),
        ({k: v for k, v in valid_event.items() if k != "before"}, "event\\.before"),
        ({k: v for k, v in valid_event.items() if k != "after"}, "event\\.after"),
        (
            {
                **valid_event,
                "pull_request": {
                    **valid_event["pull_request"],
                    "base": {"ref": "main", "repo": valid_event["pull_request"]["base"]["repo"]},
                },
            },
            "pull_request\\.base\\.sha",
        ),
        (
            {
                **valid_event,
                "pull_request": {
                    **valid_event["pull_request"],
                    "head": {"ref": "staging", "repo": valid_event["pull_request"]["head"]["repo"]},
                },
            },
            "pull_request\\.head\\.sha",
        ),
    ):
        event_file.write_text(json.dumps(bad_event), encoding="utf-8")
        with pytest.raises(D12SystemGrantError, match=match_re):
            d12_system_proof_host.validate_host_system_event_and_git(
                REPO_ROOT,
                grant=grant,
                environ=env,
                uname_fn=lambda: ("Linux", "x86_64"),
                runner=fake_git,
            )

    event_file.write_text(json.dumps(valid_event), encoding="utf-8")
    for env_override, match_re in (
        ({"GITHUB_BASE_REF": ""}, "GITHUB_BASE_REF"),
        ({"GITHUB_HEAD_REF": ""}, "GITHUB_HEAD_REF"),
        ({"GITHUB_SHA": ""}, "GITHUB_SHA"),
        ({"GITHUB_WORKFLOW_REF": ""}, "GITHUB_WORKFLOW_REF"),
        ({"GITHUB_WORKFLOW_REF": str(grant["workflow_path"])}, "GITHUB_WORKFLOW_REF"),
        (
            {"GITHUB_WORKFLOW_REF": f"{grant['workflow_path']}@refs/pull/13/merge"},
            "GITHUB_WORKFLOW_REF",
        ),
        (
            {"GITHUB_WORKFLOW_REF": f"{grant['repository']}/{grant['workflow_path']}"},
            "GITHUB_WORKFLOW_REF",
        ),
        (
            {"GITHUB_WORKFLOW_REF": f"{grant['repository']}/{grant['workflow_path']}@"},
            "GITHUB_WORKFLOW_REF",
        ),
        (
            {"GITHUB_WORKFLOW_REF": f"{grant['workflow_path']}.bak@refs/pull/13/merge"},
            "GITHUB_WORKFLOW_REF",
        ),
        (
            {"GITHUB_WORKFLOW_REF": f"evil/repo/{grant['workflow_path']}@refs/pull/13/merge"},
            "GITHUB_WORKFLOW_REF",
        ),
        ({"GITHUB_WORKFLOW_REF": f"{grant['workflow_path']}@"}, "GITHUB_WORKFLOW_REF"),
    ):
        with pytest.raises(D12SystemGrantError, match=match_re):
            d12_system_proof_host.validate_host_system_event_and_git(
                REPO_ROOT,
                grant=grant,
                environ={**env, **env_override},
                uname_fn=lambda: ("Linux", "x86_64"),
                runner=fake_git,
            )


def test_lower_layer_modules_do_not_import_upper_or_resource_owners() -> None:
    lower_paths = (
        REPO_ROOT / "src/test/support/python/repomap_test_support/d12_recipe.py",
        REPO_ROOT / "tools/ci/d12_system_grant.py",
        REPO_ROOT / "tools/ci/d12_system_proof_host.py",
    )
    forbidden_exact = {
        "ci.d12_hosted_evidence",
        "ci.d12_hosted_qualification",
        "ci.d12_hosted_reports",
        "ci.d12_system_hold",
        "d12_hosted_evidence",
        "d12_hosted_qualification",
        "d12_hosted_reports",
        "d12_system_hold",
        "repomap_test_support.d12_core_image",
        "repomap_test_support.d12_image_probes",
        "tools.d12_dependency_preflight",
        "d12_core_image",
        "d12_dependency_preflight",
        "d12_image_probes",
    }
    forbidden_prefixes = (
        "repomap_test_support.resource_",
        "tools.system.",
    )
    for path in lower_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                for alias in node.names:
                    imported.add(f"{node.module}.{alias.name}")
        assert not (imported & forbidden_exact), f"{path} imported forbidden {imported & forbidden_exact}"
        assert not any(
            mod.startswith(forbidden_prefixes) for mod in imported
        ), f"{path} imported forbidden prefix in {imported}"
