"""Topology contracts and verified qualification workflow validation."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[6]
TOOLS_ROOT = ROOT / "tools"
TOOLS_CI = TOOLS_ROOT / "ci"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from ci.ci_topology import check_topology
from ci.ci_topology_contracts import (
    RELEASE_WORKFLOW,
    RETIRED_WORKFLOWS,
    TRUSTED_GATE_COPY_SET,
    check_trusted_gate_copy_set,
)
from ci.ci_topology_gates import _check_main_system_gate, _check_staging_gate
from ci.workflow_model import load_workflow

WORKFLOWS_DIR = ROOT / ".github/workflows"
RELEASE_WORKFLOW_PATH = WORKFLOWS_DIR / RELEASE_WORKFLOW


def test_production_release_qualification_workflow_satisfies_topology_contracts() -> None:
    violations = check_topology(ROOT)
    assert violations == (), f"topology violations: {violations}"

    release_wf = load_workflow(RELEASE_WORKFLOW_PATH)
    staging_violations = _check_staging_gate(release_wf)
    assert staging_violations == [], f"staging gate violations: {staging_violations}"

    main_violations = _check_main_system_gate(release_wf)
    assert main_violations == [], f"main system gate violations: {main_violations}"


def test_retired_workflows_remain_absent() -> None:
    for retired in RETIRED_WORKFLOWS:
        assert not (WORKFLOWS_DIR / retired).exists(), f"Retired workflow {retired} must not exist"


def test_candidate_bindings_and_gate_request_present_in_release_workflow() -> None:
    workflow = load_workflow(RELEASE_WORKFLOW_PATH)
    commands = "\n".join(workflow.run_commands())
    assert "git rev-parse HEAD" in commands
    assert "git rev-parse 'HEAD^{tree}'" in commands
    assert "git rev-parse 'HEAD^1'" in commands
    assert "git rev-parse 'HEAD^2'" in commands
    assert "export CANDIDATE_SHA CANDIDATE_TREE CANDIDATE_BASE_PARENT CANDIDATE_HEAD_PARENT" in commands
    assert "repomap-ci-gate-request-v1" in commands
    assert "gate-request.json" in commands


def test_release_qualification_bind_step_execution_in_git_repo_without_prior_env() -> None:
    workflow = load_workflow(RELEASE_WORKFLOW_PATH)
    bind_step = next(s for s in workflow.steps() if s.get("id") == "bind")
    script = bind_step["run"]

    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir) / "repo"
        repo_dir.mkdir()
        env_file = Path(tmpdir) / "github_env"
        runner_temp = Path(tmpdir) / "runner_temp"
        runner_temp.mkdir()

        git_env = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
        }
        subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True, env=git_env)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True, env=git_env)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True, env=git_env)
        (repo_dir / "base.txt").write_text("base content\n", encoding="utf-8")
        subprocess.run(["git", "add", "base.txt"], cwd=repo_dir, check=True, env=git_env)
        subprocess.run(["git", "commit", "-m", "base parent"], cwd=repo_dir, check=True, capture_output=True, env=git_env)
        base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True, capture_output=True, text=True, env=git_env).stdout.strip()

        subprocess.run(["git", "checkout", "-b", "staging"], cwd=repo_dir, check=True, capture_output=True, env=git_env)
        (repo_dir / "staging.txt").write_text("staging content\n", encoding="utf-8")
        subprocess.run(["git", "add", "staging.txt"], cwd=repo_dir, check=True, env=git_env)
        subprocess.run(["git", "commit", "-m", "staging head"], cwd=repo_dir, check=True, capture_output=True, env=git_env)
        head_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True, capture_output=True, text=True, env=git_env).stdout.strip()

        subprocess.run(["git", "checkout", "main"], cwd=repo_dir, check=True, capture_output=True, env=git_env)
        subprocess.run(["git", "merge", "--no-ff", "staging", "-m", "merge candidate"], cwd=repo_dir, check=True, capture_output=True, env=git_env)
        merge_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True, capture_output=True, text=True, env=git_env).stdout.strip()
        merge_tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=repo_dir, check=True, capture_output=True, text=True, env=git_env).stdout.strip()

        env = git_env.copy()
        for k in ("CANDIDATE_SHA", "CANDIDATE_TREE", "CANDIDATE_BASE_PARENT", "CANDIDATE_HEAD_PARENT"):
            env.pop(k, None)
        env["GITHUB_ENV"] = str(env_file)
        env["RUNNER_TEMP"] = str(runner_temp)
        env["PR_NUMBER"] = "11"
        env["GITHUB_REPOSITORY"] = "example/repo-map"

        res = subprocess.run(["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script], cwd=repo_dir, env=env, capture_output=True, text=True)
        assert res.returncode == 0, f"script failed with rc {res.returncode}:\nstderr: {res.stderr}\nstdout: {res.stdout}"

        req_path = runner_temp / "gate-request.json"
        assert req_path.is_file(), "gate-request.json was not created"
        req_data = json.loads(req_path.read_text(encoding="utf-8"))
        assert req_data["schema"] == "repomap-ci-gate-request-v1"
        assert req_data["gate_kind"] == "main-system"
        assert req_data["pr_number"] == 11
        assert req_data["base_sha"] == base_sha
        assert req_data["head_sha"] == head_sha
        assert req_data["approval_id"] == "pr-11"
        assert req_data["repository"] == "example/repo-map"

        env_contents = env_file.read_text(encoding="utf-8")
        assert f"CANDIDATE_SHA={merge_sha}" in env_contents
        assert f"CANDIDATE_TREE={merge_tree}" in env_contents
        assert f"CANDIDATE_BASE_PARENT={base_sha}" in env_contents
        assert f"CANDIDATE_HEAD_PARENT={head_sha}" in env_contents


def test_check_trusted_gate_copy_set_detects_missing_directory() -> None:
    steps: list[Mapping[str, object]] = [
        {"run": "cp tools/ci/gate_contract.py \"${RUNNER_TEMP}/gate_contract.py\""}
    ]
    violations = check_trusted_gate_copy_set("test.yml", steps, 0)
    assert any("must create ci directory" in v for v in violations)


@pytest.mark.parametrize("missing_src,missing_dst", TRUSTED_GATE_COPY_SET)
def test_check_trusted_gate_copy_set_detects_missing_command(
    missing_src: str, missing_dst: str
) -> None:
    lines = ['mkdir -p "${RUNNER_TEMP}/ci"']
    for src, dst in TRUSTED_GATE_COPY_SET:
        if src != missing_src:
            lines.append(f"cp {src} {dst}")
    steps: list[Mapping[str, object]] = [{"run": "\n".join(lines)}]

    violations = check_trusted_gate_copy_set("test.yml", steps, 0)
    expected = f"missing copy command: cp {missing_src} {missing_dst}"
    assert any(expected in v for v in violations), violations


def test_check_trusted_gate_copy_set_detects_reversed_order() -> None:
    lines = ['mkdir -p "${RUNNER_TEMP}/ci"']
    for src, dst in reversed(TRUSTED_GATE_COPY_SET):
        lines.append(f"cp {src} {dst}")
    steps: list[Mapping[str, object]] = [{"run": "\n".join(lines)}]

    violations = check_trusted_gate_copy_set("test.yml", steps, 0)
    assert any("order is invalid" in v for v in violations), violations


def test_check_trusted_gate_copy_set_empty_when_no_preserve_step() -> None:
    assert check_trusted_gate_copy_set("test.yml", [], None) == []


@pytest.mark.parametrize("extra", (
    'cp candidate.py "${RUNNER_TEMP}/ci/gate_contract_bindings.py"',
    'cp tools/ci/*.py "${RUNNER_TEMP}/ci/"',
))
def test_trusted_copy_set_rejects_extra_or_overwriting_commands(extra: str) -> None:
    lines = ['mkdir -p "${RUNNER_TEMP}/ci"']
    lines.extend(f"cp {source} {destination}" for source, destination in TRUSTED_GATE_COPY_SET)
    steps: list[Mapping[str, object]] = [{"run": "\n".join([*lines, extra])}]
    assert any("exact declared copy set" in item
               for item in check_trusted_gate_copy_set("test.yml", steps, 0))
