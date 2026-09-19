"""REPOMAP-CI-PIPE0 staged promotion topology contracts.

Each mutation test proves the corresponding invariant is actually load-bearing:
a check that cannot fail is not a contract.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest

ROOT = Path(__file__).resolve().parents[6]
TOOLS_CI = ROOT / "tools/ci"
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from ci.ci_topology import check_topology
from ci.workflow_model import load_workflow

WORKFLOW_DIR = ROOT / ".github/workflows"
RELEASE_WORKFLOW = WORKFLOW_DIR / "repomap-release-qualification.yml"


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


def test_topology_holds_for_current_workflows() -> None:
    assert check_topology(ROOT) == ()


def test_staging_project_owned_command_appears_exactly_once() -> None:
    occurrences = 0
    for path in WORKFLOW_DIR.iterdir():
        commands = "\n".join(load_workflow(path).run_commands())
        occurrences += commands.count("--suite staging")

    assert occurrences == 1


def test_system_project_owned_command_appears_exactly_once() -> None:
    occurrences = 0
    for path in WORKFLOW_DIR.iterdir():
        commands = "\n".join(load_workflow(path).run_commands())
        occurrences += commands.count("--suite system")

    assert occurrences == 1


def test_canonical_pr_unit_command_appears_exactly_once() -> None:
    occurrences = 0
    for path in WORKFLOW_DIR.iterdir():
        commands = "\n".join(load_workflow(path).run_commands())
        occurrences += commands.count(
            "python3 tools/run_tests.py --suite unit"
        )

    assert occurrences == 1


def test_canonical_test_runner_appears_exactly_three_times() -> None:
    occurrences = 0
    for path in WORKFLOW_DIR.iterdir():
        commands = "\n".join(load_workflow(path).run_commands())
        occurrences += commands.count("python3 tools/run_tests.py")

    assert occurrences == 3


def test_release_qualification_targets_main_pull_requests_only() -> None:
    triggers = load_workflow(RELEASE_WORKFLOW).triggers

    assert set(triggers) == {"pull_request"}
    assert triggers["pull_request"]["branches"] == ["main"]
    assert sorted(triggers["pull_request"]["types"]) == [
        "opened",
        "ready_for_review",
        "reopened",
        "synchronize",
    ]
    assert "paths" not in triggers["pull_request"]


def test_no_workflow_declares_a_duplicate_branch_push_lane() -> None:
    for path in WORKFLOW_DIR.iterdir():
        assert "push" not in load_workflow(path).triggers, path.name


def test_no_workflow_grants_a_write_permission() -> None:
    for path in WORKFLOW_DIR.iterdir():
        for scope, level in load_workflow(path).permissions.items():
            assert level in {"read", "none"}, f"{path.name}:{scope}"


def test_source_and_export_policy_performs_no_expensive_work() -> None:
    workflow = load_workflow(RELEASE_WORKFLOW)
    job = workflow.jobs["source-and-export-policy"]
    commands = "\n".join(str(s["run"]) for s in job["steps"] if "run" in s).lower()

    assert "tools/ci/promotion_policy.py" in commands
    assert "tools/ci/public_export_policy.py" in commands
    for expensive in ("run_tests.py", "docker", "postgres", "pytest", "pip install"):
        assert expensive not in commands


def test_no_workflow_merges_updates_refs_or_closes_pull_requests() -> None:
    forbidden = (
        "git push",
        "git merge",
        "git commit",
        "git tag",
        "git update-ref",
        "gh pr merge",
        "gh pr close",
        "gh pr edit",
        "auto-merge",
        "automerge",
    )
    for path in WORKFLOW_DIR.iterdir():
        commands = "\n".join(load_workflow(path).run_commands()).lower()
        for marker in forbidden:
            assert marker not in commands, f"{path.name}: {marker}"
        for action in load_workflow(path).action_uses():
            assert not action.startswith(("peter-evans/", "actions/github-script"))


def test_no_github_ruleset_or_protection_configuration_is_introduced() -> None:
    for relative in (
        ".github/rulesets",
        ".github/CODEOWNERS",
        "CODEOWNERS",
        "docs/CODEOWNERS",
    ):
        assert not (ROOT / relative).exists(), relative
    for path in WORKFLOW_DIR.iterdir():
        content = path.read_text(encoding="utf-8").lower()
        assert "/protection" not in content
        assert "/rulesets" not in content


def test_immutable_action_pins_and_read_only_checkout_are_preserved() -> None:
    for path in WORKFLOW_DIR.iterdir():
        workflow = load_workflow(path)
        for action in workflow.action_uses():
            name, _, pinned = action.partition("@")
            assert len(pinned) == 40 and all(c in "0123456789abcdef" for c in pinned), name
        for step in workflow.steps():
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False


def test_pre_review_static_preserves_aggregate_check_owner() -> None:
    workflow = load_workflow(RELEASE_WORKFLOW)
    job = workflow.jobs["pre-review-static"]
    commands = "\n".join(str(s["run"]) for s in job["steps"] if "run" in s)

    assert "tools/ci/bootstrap_pre_review.py" in commands
    assert "tools/ci/run_pre_review.py" in commands
    lowered = commands.lower()
    for expensive in ("docker", "postgres", "pytest", "run_tests.py"):
        assert expensive not in lowered


@pytest.mark.parametrize(
    ("name", "old", "new", "expected"),
    [
        (
            "repomap-release-qualification.yml",
            "    branches: [main]",
            "    branches: [staging]",
            "must target 'main' only",
        ),
        (
            "repomap-release-qualification.yml",
            "  pull_request:",
            "  push:\n    branches: [main]\n  pull_request:",
            "no duplicate branch push lane",
        ),
        (
            "repomap-release-qualification.yml",
            "  pull_request:",
            "  workflow_dispatch:\n  pull_request:",
            "must not declare workflow_dispatch",
        ),
        (
            "repomap-release-qualification.yml",
            "    branches: [main]",
            "    branches: [main]\n    paths: ['src/**']",
            "must not declare path filters",
        ),
        (
            "repomap-release-qualification.yml",
            "  pre-review-static:\n"
            "    name: pre-review-static\n"
            "    needs: [source-and-export-policy]\n"
            "    runs-on: ubuntu-latest\n"
            "    timeout-minutes: 40\n"
            "    steps:\n"
            "      - name: Check out repository\n"
            "        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
            "        with:\n"
            "          fetch-depth: 0",
            "  pre-review-static:\n"
            "    name: pre-review-static\n"
            "    needs: [source-and-export-policy]\n"
            "    runs-on: ubuntu-latest\n"
            "    timeout-minutes: 40\n"
            "    steps:\n"
            "      - name: Check out repository\n"
            "        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n"
            "        with:\n"
            "          fetch-depth: 1",
            "complete Git history",
        ),
        (
            "repomap-release-qualification.yml",
            "tools/ci/bootstrap_pre_review.py",
            "tools/ci/removed_pre_review.py",
            "missing pre-review owner",
        ),
        (
            "repomap-release-qualification.yml",
            '          "${RUNNER_TEMP}/repomap-pre-review-tools/python/bin/python" \\\n',
            "          python3 \\\n",
            "missing pre-review owner",
        ),
        (
            "repomap-release-qualification.yml",
            "  contents: read",
            "  contents: write",
            "not read-only",
        ),
        (
            "repomap-release-qualification.yml",
            'python -m pip install --editable ".[test,scale-tools,static-analysis]"',
            'python -m pip install --editable ".[test,scale-tools]"',
            "unit lane must contain",
        ),
        (
            "repomap-release-qualification.yml",
            "      - name: Set up Go for the canonical runner\n"
            "        uses: actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e # v7.0.0\n"
            "        with:\n"
            "          go-version-file: src/main/go/go.mod\n"
            "          cache: false\n\n",
            "",
            "canonical unit runner requires pinned Go",
        ),
        (
            "repomap-release-qualification.yml",
            "run: python3 tools/run_tests.py --suite unit",
            "run: python -m pytest src/test/unit/python",
            "canonical runner",
        ),
        (
            "repomap-release-qualification.yml",
            "run: python3 tools/run_tests.py --suite unit",
            "run: python3 tools/run_tests.py --suite unit --no-coverage",
            "retain its coverage gate",
        ),
    ],
)
def test_topology_contracts_detect_their_own_violation(
    tmp_path: Path, name: str, old: str, new: str, expected: str
) -> None:
    def mutate(root: Path) -> None:
        edit(root, name, old, new)

    violations = violations_after(tmp_path, mutate)

    assert any(expected in violation for violation in violations), violations


def test_retired_workflow_is_rejected(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        (root / ".github/workflows/repomap-static-analysis.yml").write_text("name: test\n", encoding="utf-8")

    violations = violations_after(tmp_path, mutate)
    assert any("retired workflow must not exist" in v for v in violations)


def test_retired_all_invocation_is_rejected(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        path = root / ".github/workflows/repomap-release-qualification.yml"
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n      - name: Sneaky\n        run: python3 tools/run_tests.py --suite all\n",
            encoding="utf-8",
        )

    violations = violations_after(tmp_path, mutate)

    assert any("retired --suite all" in violation for violation in violations)


def test_protection_configuration_is_rejected(tmp_path: Path) -> None:
    def mutate(root: Path) -> None:
        (root / ".github/CODEOWNERS").write_text("* @owner\n", encoding="utf-8")

    violations = violations_after(tmp_path, mutate)

    assert any("JACA broker" in violation for violation in violations)


def test_topology_entrypoint_is_runnable_and_stdlib_only() -> None:
    completed = subprocess.run(
        [sys.executable, "-S", "-E", str(TOOLS_CI / "ci_topology.py"), "--repo-root", str(ROOT)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "CI topology contracts hold" in completed.stdout


def test_static_catalog_import_and_required_check_remain_load_bearing(tmp_path: Path) -> None:
    root = clone_workflows(tmp_path)
    ci_root = root / "tools/ci"
    ci_root.mkdir(parents=True)
    for name in ("run_pre_review.py", "pre_review_checks.py"):
        shutil.copy2(ROOT / "tools/ci" / name, ci_root / name)
    driver = ci_root / "run_pre_review.py"
    original = driver.read_text()
    driver.write_text(original.replace("from ci.pre_review_checks import", "from ci.missing import"))
    assert any("missing check catalog import" in item for item in check_topology(root))
    driver.write_text(original)
    catalog = ci_root / "pre_review_checks.py"
    catalog.write_text(catalog.read_text().replace('"actionlint"', '"removed-check"'))
    assert any("missing 'actionlint'" in item for item in check_topology(root))
