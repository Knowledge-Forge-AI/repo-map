"""REPOMAP-CI-PIPE0 staged promotion topology contracts.

Each mutation test proves the corresponding invariant is actually load-bearing:
a check that cannot fail is not a contract.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[6]
TOOLS_CI = ROOT / "tools/ci"
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from ci.ci_topology import check_topology
from ci.workflow_model import load_workflow
from src.test.unit.python.tools.ci.pipe0_topology_support import (
    MAIN_POLICY,
    PR_FAST,
    PUBLIC_QUALIFICATION_GATE,
    WORKFLOW_DIR,
    clone_workflows,
    edit,
    violations_after,
)


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


def test_pr_fast_targets_staging_pull_requests_only() -> None:
    if not PR_FAST.exists():
        rel = PUBLIC_QUALIFICATION_GATE
        if rel.exists():
            triggers = load_workflow(rel).triggers
            assert triggers["pull_request"]["branches"] == ["main"]
            return
        pytest.skip("withheld in public projection: PR_FAST and release qualification absent")
    triggers = load_workflow(PR_FAST).triggers

    assert set(triggers) == {"pull_request", "workflow_dispatch"}
    assert triggers["pull_request"]["branches"] == ["staging"]
    assert sorted(triggers["pull_request"]["types"]) == [
        "opened",
        "ready_for_review",
        "reopened",
        "synchronize",
    ]


def test_no_workflow_declares_a_duplicate_branch_push_lane() -> None:
    for path in WORKFLOW_DIR.iterdir():
        assert "push" not in load_workflow(path).triggers, path.name


def test_no_workflow_grants_a_write_permission() -> None:
    for path in WORKFLOW_DIR.iterdir():
        for scope, level in load_workflow(path).permissions.items():
            assert level in {"read", "none"}, f"{path.name}:{scope}"


def test_main_policy_applies_only_to_pull_requests_targeting_main() -> None:
    if not MAIN_POLICY.exists():
        rel = PUBLIC_QUALIFICATION_GATE
        if rel.exists():
            triggers = load_workflow(rel).triggers
            assert triggers["pull_request"]["branches"] == ["main"]
            return
        pytest.skip("withheld in public projection: MAIN_POLICY absent")
    triggers = load_workflow(MAIN_POLICY).triggers

    assert triggers["pull_request"]["branches"] == ["main"]
    assert "push" not in triggers


def test_invalid_main_source_performs_no_expensive_work() -> None:
    if not MAIN_POLICY.exists():
        rel = PUBLIC_QUALIFICATION_GATE
        if not rel.exists():
            pytest.skip("withheld in public projection: MAIN_POLICY and release qualification absent")
        workflow = load_workflow(rel)
        job = workflow.jobs["source-and-export-policy"]
        commands = "\n".join(str(s["run"]) for s in job["steps"] if "run" in s).lower()
        assert "tools/ci/promotion_policy.py" in commands
        for expensive in ("run_tests.py", "docker", "postgres", "pytest", "pip install"):
            assert expensive not in commands
        return
    workflow = load_workflow(MAIN_POLICY)
    commands = "\n".join(workflow.run_commands()).lower()

    assert "tools/ci/promotion_policy.py" in "\n".join(workflow.run_commands())
    for expensive in ("run_tests.py", "docker", "postgres", "pytest", "pip install"):
        assert expensive not in commands
    assert all(
        not use.startswith("actions/setup-") for use in workflow.action_uses()
    )


def test_no_workflow_merges_updates_refs_or_closes_pull_requests() -> None:
    forbidden = (
        "git push", "git merge", "git commit", "git tag", "git update-ref",
        "gh pr merge", "gh pr close", "gh pr edit", "auto-merge", "automerge",
    )
    for path in WORKFLOW_DIR.iterdir():
        commands = "\n".join(load_workflow(path).run_commands()).lower()
        for marker in forbidden:
            assert marker not in commands, f"{path.name}: {marker}"
        for action in load_workflow(path).action_uses():
            assert not action.startswith(("peter-evans/", "actions/github-script"))


def test_no_github_ruleset_or_protection_configuration_is_introduced() -> None:
    for relative in (".github/rulesets", ".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS"):
        assert not (ROOT / relative).exists(), relative
    for path in WORKFLOW_DIR.iterdir():
        content = path.read_text(encoding="utf-8").lower()
        assert "/protection" not in content and "/rulesets" not in content


def test_immutable_action_pins_and_read_only_checkout_are_preserved() -> None:
    for path in WORKFLOW_DIR.iterdir():
        workflow = load_workflow(path)
        for action in workflow.action_uses():
            name, _, pinned = action.partition("@")
            assert len(pinned) == 40 and all(c in "0123456789abcdef" for c in pinned), name
        for step in workflow.steps():
            if str(step.get("uses", "")).startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False


def test_pr_fast_preserves_the_aggregate_check_owner() -> None:
    if not PR_FAST.exists():
        rel = PUBLIC_QUALIFICATION_GATE
        if not rel.exists():
            pytest.skip("withheld in public projection: PR_FAST and release qualification absent")
        workflow = load_workflow(rel)
        job = workflow.jobs["pre-review-static"]
        commands = "\n".join(str(s["run"]) for s in job["steps"] if "run" in s)
        assert "tools/ci/bootstrap_pre_review.py" in commands
        assert "tools/ci/run_pre_review.py" in commands
        lowered = commands.lower()
        for expensive in ("docker", "postgres", "pytest", "run_tests.py"):
            assert expensive not in lowered
        return
    commands = "\n".join(load_workflow(PR_FAST).run_commands())

    assert "tools/ci/bootstrap_pre_review.py" in commands
    assert "tools/ci/run_pre_review.py" in commands
    lowered = commands.lower()
    for expensive in ("docker", "postgres", "pytest", "run_tests.py"):
        assert expensive not in lowered


@pytest.mark.parametrize(
    ("name", "old", "new", "expected"),
    [
        (
            "repomap-static-analysis.yml",
            "    branches: [staging]",
            "    branches: [main]",
            "PR Fast must target",
        ),
        (
            "repomap-static-analysis.yml",
            "  workflow_dispatch:",
            "  push:\n    branches: [main]\n  workflow_dispatch:",
            "no duplicate branch push lane",
        ),
        (
            "repomap-main-source-policy.yml",
            "    branches: [main]",
            "    branches: [staging]",
            "must apply only to PRs targeting",
        ),
        (
            "repomap-main-source-policy.yml",
            "        run: python3 tools/ci/promotion_policy.py",
            "        run: |\n          python3 tools/ci/promotion_policy.py\n          docker pull alpine:latest",
            "must cost nothing",
        ),
        (
            "repomap-static-analysis.yml",
            "          fetch-depth: 0",
            "          fetch-depth: 1",
            "complete Git history",
        ),
        (
            "repomap-static-analysis.yml",
            "python3 tools/ci/bootstrap_pre_review.py",
            "python3 tools/ci/removed_pre_review.py",
            "missing pre-review owner",
        ),
        (
            "repomap-static-analysis.yml",
            '          "${RUNNER_TEMP}/repomap-pre-review-tools/python/bin/python" \\\n',
            "          python3 \\\n",
            "missing pre-review owner",
        ),
        (
            "repomap-static-analysis.yml",
            "      - name: Materialize the pinned pre-review toolchain\n",
            "      - name: Duplicate host static install\n"
            '        run: python -m pip install --editable ".[static-analysis]"\n\n'
            "      - name: Materialize the pinned pre-review toolchain\n",
            "must not be installed into host Python",
        ),
        (
            "repomap-unit-tests.yml",
            "    branches: [staging]",
            "    branches: [main]",
            "unit lane must target",
        ),
        (
            "repomap-unit-tests.yml",
            '      - "src/main/go/**"\n',
            "",
            "unit lane paths must be",
        ),
        (
            "repomap-unit-tests.yml",
            "  contents: read",
            "  contents: write",
            "not read-only",
        ),
        (
            "repomap-unit-tests.yml",
            'python -m pip install --editable ".[test,scale-tools,static-analysis]"',
            'python -m pip install --editable ".[test,scale-tools]"',
            "unit lane must contain",
        ),
        (
            "repomap-unit-tests.yml",
            "python -m pip install --require-hashes --no-deps --requirement "
            "tools/ci/project_dependencies.lock",
            "python -m pip install psycopg",
            "unit lane must contain",
        ),
        (
            "repomap-unit-tests.yml",
            "      - name: Set up Go for the canonical runner\n"
            "        uses: actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e # v7.0.0\n"
            "        with:\n"
            "          go-version-file: src/main/go/go.mod\n"
            "          cache: false\n\n",
            "",
            "canonical unit runner requires pinned Go",
        ),
        (
            "repomap-unit-tests.yml",
            "        run: python3 tools/run_tests.py --suite unit",
            "        run: python -m pytest src/test/unit/python",
            "canonical runner",
        ),
        (
            "repomap-unit-tests.yml",
            "        run: python3 tools/run_tests.py --suite unit",
            "        run: |\n"
            "          python3 tools/run_tests.py --suite unit\n"
            "          python3 tools/run_tests.py --suite int",
            "must not contain '--suite int'",
        ),
    ],
)
def test_topology_contracts_detect_their_own_violation(
    tmp_path: Path, name: str, old: str, new: str, expected: str
) -> None:
    if not (WORKFLOW_DIR / name).exists():
        pytest.skip(f"withheld in public projection: workflow {name} absent")
    violations = violations_after(tmp_path, lambda root: edit(root, name, old, new))
    assert any(expected in violation for violation in violations), violations


def test_retired_all_invocation_is_rejected(tmp_path: Path) -> None:
    target = PR_FAST if PR_FAST.exists() else PUBLIC_QUALIFICATION_GATE

    def mutate(root: Path) -> None:
        path = root / ".github/workflows" / target.name
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n      - name: S\n        run: python3 tools/run_tests.py --suite all\n",
            encoding="utf-8",
        )

    violations = violations_after(tmp_path, mutate)
    assert any("the retired --suite all command must not appear" in v for v in violations)


def test_retired_workflow_is_rejected(tmp_path: Path) -> None:
    if PR_FAST.exists():
        pytest.skip("withheld in private workspace: PR_FAST present")

    def mutate(root: Path) -> None:
        (root / ".github/workflows/repomap-static-analysis.yml").write_text("name: test\n", encoding="utf-8")

    assert any("retired workflow must not exist" in v for v in violations_after(tmp_path, mutate))


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
