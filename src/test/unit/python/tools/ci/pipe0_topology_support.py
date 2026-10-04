"""Shared support and workflow fixtures for pipe0 topology tests."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[6]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from ci.ci_topology import check_topology

WORKFLOW_DIR = ROOT / ".github/workflows"
STAGING_GATE = WORKFLOW_DIR / "repomap-staging-gate.yml"
MAIN_SYSTEM_GATE = WORKFLOW_DIR / "repomap-main-system-gate.yml"
PUBLIC_QUALIFICATION_GATE = (
    WORKFLOW_DIR / "pipeline.yml"
    if (WORKFLOW_DIR / "pipeline.yml").exists()
    else WORKFLOW_DIR / "repomap-release-qualification.yml"
)
PR_FAST = WORKFLOW_DIR / "repomap-static-analysis.yml"
MAIN_POLICY = WORKFLOW_DIR / "repomap-main-source-policy.yml"

TRUSTED_GATE_CONTRACT = '"${RUNNER_TEMP}/gate_contract.py"'
TRUSTED_GATE_INVOCATION = f"python3 -S -E {TRUSTED_GATE_CONTRACT}"


def clone_workflows(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / ".github/workflows").mkdir(parents=True)
    for path in WORKFLOW_DIR.iterdir():
        shutil.copy(path, root / ".github/workflows" / path.name)
    return root


def edit(root: Path, name: str, old: str, new: str) -> None:
    path = root / ".github/workflows" / name
    content = path.read_text(encoding="utf-8")
    assert old in content, f"{name} no longer contains {old!r}"
    path.write_text(content.replace(old, new, 1), encoding="utf-8")


def violations_after(tmp_path: Path, mutate: Callable[[Path], None]) -> tuple[str, ...]:
    root = clone_workflows(tmp_path)
    mutate(root)
    return check_topology(root)


GATE_VIOLATION_CASES: list[tuple[str, str, str, str]] = [
    (
        "repomap-staging-gate.yml",
        "on:\n  workflow_dispatch:",
        "on:\n  pull_request:\n  workflow_dispatch:",
        "explicit ",
    ),
    (
        "repomap-staging-gate.yml",
        "  pull-requests: read",
        "  pull-requests: write",
        "not read-only",
    ),
    (
        "repomap-staging-gate.yml",
        "        run: df -B1 /\n\n      - name: Run the staging smoke and integration gate",
        "        run: git push origin HEAD\n\n      - name: Run the staging smoke and integration gate",
        "not git",
    ),
    (
        "repomap-staging-gate.yml",
        "uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
        "uses: actions/upload-artifact@v7",
        "40-hex SHA pin",
    ),
    (
        "repomap-staging-gate.yml",
        "      - name: Record free disk before the staging suite\n",
        "      - name: Duplicate host Go setup\n"
        "        uses: actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e\n"
        "        with:\n"
        '          go-version: "1.25"\n\n'
        "      - name: Record free disk before the staging suite\n",
        "must not duplicate host toolchain bootstrap",
    ),
    (
        "repomap-staging-gate.yml",
        "      - name: Record free disk before the staging suite\n",
        "      - name: Duplicate host Python test environment\n"
        '        run: python -m pip install --editable ".[test,scale-tools,static-analysis]"\n\n'
        "      - name: Record free disk before the staging suite\n",
        "must not duplicate host toolchain bootstrap",
    ),
    (
        "repomap-staging-gate.yml",
        "      - name: Record free disk before the staging suite\n",
        "      - name: Duplicate host linter install\n"
        "        run: go install github.com/golangci/golangci-lint/v2/cmd/golangci-lint@v2.6.2\n\n"
        "      - name: Record free disk before the staging suite\n",
        "must not duplicate host toolchain bootstrap",
    ),
    (
        "repomap-staging-gate.yml",
        "            --sandbox \\\n",
        "",
        "must use --sandbox",
    ),
    (
        "repomap-staging-gate.yml",
        'python3 -S -E "${RUNNER_TEMP}/gate_contract.py" verify',
        "python3 -S -E tools/ci/gate_contract.py verify",
        "trusted gate contract",
    ),
    (
        "repomap-staging-gate.yml",
        'python3 -S -E "${RUNNER_TEMP}/gate_contract.py" record',
        'python3 "${RUNNER_TEMP}/gate_contract.py" record',
        "trusted gate contract",
    ),
    (
        "repomap-staging-gate.yml",
        '--executor-ref "${GITHUB_REF}"',
        '--executor-ref "refs/heads/staging"',
        "trusted executor ref/SHA inputs",
    ),
    (
        "repomap-staging-gate.yml",
        "          ref: ${{ github.sha }}",
        "          ref: refs/heads/feature",
        "capture trusted staging semantics",
    ),
    (
        "repomap-staging-gate.yml",
        '          cp tools/ci/gate_contract_bindings.py "${RUNNER_TEMP}/ci/gate_contract_bindings.py"\n',
        "",
        "missing copy command",
    ),
    (
        "repomap-main-system-gate.yml",
        "      - name: Run the main system gate\n"
        "        id: system\n"
        "        env:\n"
        "          APPROVAL_ID: ${{ inputs.approval_id }}",
        "      - name: Run the main system gate\n"
        "        id: system\n"
        "        env:\n"
        "          APPROVAL_ID: ${{ inputs.request_kind }}",
        "exact step environment",
    ),
    (
        "repomap-main-system-gate.yml",
        '          cp tools/ci/gate_contract_bindings.py "${RUNNER_TEMP}/ci/gate_contract_bindings.py"\n',
        "",
        "missing copy command",
    ),
]
